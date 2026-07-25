"""Command-line interface for nate-ntm."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import json5
import typer
from dotenv import load_dotenv
from nate_oha.config import NateOHAConfig
from pydantic import ValidationError

from .api.client import JsonRpcClientError, JsonRpcHttpClient
from .api.models import AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult
from .config.runtime_config import load_runtime_config
from .runtime.daemon import MetadataMissingError
from .runtime.metadata_store import MetadataStore, validate_swarm_id
from .runtime.runner import run_runtime_with_control_api
from .runtime.swarm_state import AgentState, SwarmState
from .swarm_constructors import ConstructionContext, apply_constructors

load_dotenv()

app = typer.Typer(help="nate_ntm command-line interface")
runtime_app = typer.Typer(help="Runtime daemon commands")
swarm_app = typer.Typer(help="Swarm metadata commands")
api_app = typer.Typer(help="Runtime control API commands")
app.add_typer(runtime_app, name="runtime")
app.add_typer(swarm_app, name="swarm")
app.add_typer(api_app, name="api")


def _parse_agent_spec(value: str) -> tuple[str, Path]:
    agent_id, separator, raw_path = value.partition(":")
    agent_id = agent_id.strip()
    raw_path = raw_path.strip()
    if not separator or not agent_id or not raw_path:
        raise typer.BadParameter(
            f"invalid --agent {value!r}; expected AGENT_ID:CONFIG_PATH"
        )
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise typer.BadParameter(f"agent config does not exist or is not a file: {path}")
    return agent_id, path


@swarm_app.command("create")
def swarm_create(
    agent: list[str] = typer.Option(
        ...,
        "--agent",
        metavar="AGENT_ID:CONFIG_PATH",
        help="Explicit agent ID and nate-oha JSON5 config path.",
    ),
    project: Path | None = typer.Option(
        None, "--project", "-p", exists=True, file_okay=False, dir_okay=True
    ),
    constructor: list[str] = typer.Option([], "--constructor"),  # type: ignore[assignment]
    swarm_id: str | None = typer.Option(None, "--swarm-id"),
    agent_mail_project_id: str | None = typer.Option(None, "--agent-mail-project-id"),
    agent_mail_url: str | None = typer.Option(None, "--agent-mail-url"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Materialize one swarm from explicitly identified nate-oha configurations."""

    effective_swarm_id = validate_swarm_id(swarm_id or uuid4().hex)
    effective_project = (project or Path.cwd()).expanduser().resolve()
    if not effective_project.is_dir():
        raise typer.BadParameter(
            f"project does not exist or is not a directory: {effective_project}"
        )
    if (
        agent_mail_project_id is not None or agent_mail_url is not None
    ) and "agent-mail" not in constructor:
        raise typer.BadParameter("Agent Mail options require --constructor agent-mail")

    store = MetadataStore(effective_swarm_id)
    if store.exists() and not force:
        raise typer.BadParameter(f"swarm metadata already exists: {store.swarm_path}")

    agents: dict[str, AgentState] = {}
    for spec in agent:
        agent_id, path = _parse_agent_spec(spec)
        if agent_id in agents:
            raise typer.BadParameter(f"duplicate agent id {agent_id!r}")
        try:
            nate_oha_config = NateOHAConfig.model_validate(
                json5.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise typer.BadParameter(f"invalid agent config {path}: {exc}") from exc
        agents[agent_id] = AgentState(
            agent_id=agent_id,
            display_name=agent_id.replace("-", " ").replace("_", " ").title(),
            nate_oha_config=nate_oha_config,
        )

    if not agents:
        raise typer.BadParameter("at least one --agent config is required")

    now = datetime.now(timezone.utc)
    swarm = apply_constructors(
        SwarmState(
            swarm_id=effective_swarm_id,
            project_path=effective_project,
            created_at=now,
            last_updated_at=now,
            agents=agents,
        ),
        constructor,
        ConstructionContext(
            agent_mail_project_id=agent_mail_project_id,
            agent_mail_url=agent_mail_url,
        ),
    )

    if dry_run:
        typer.echo(json5.dumps(swarm.model_dump(mode="json"), indent=2))
        return

    try:
        store.save_swarm_state(swarm, overwrite=force)
    except FileExistsError as exc:
        raise typer.BadParameter(
            f"swarm metadata already exists: {store.swarm_path}"
        ) from exc
    typer.echo(f"Created swarm {swarm.swarm_id!r} with {len(agents)} agents")
    typer.echo(f"Swarm ID: {swarm.swarm_id}")
    typer.echo(f"Metadata: {store.swarm_path}")


@runtime_app.command("start")
def runtime_start(
    swarm_id: str = typer.Option(..., "--swarm-id"),
    nate_oha_runtime_mode: str | None = typer.Option(None, "--nate-oha-runtime-mode"),
    llm_model: str | None = typer.Option(None, "--llm-model"),
    llm_api_key: str | None = typer.Option(
        None, "--llm-api-key", envvar="NATE_NTM_LLM_API_KEY"
    ),
    prompt_soul_content: str | None = typer.Option(None, "--prompt-soul-content"),
    acp_host: str = typer.Option("127.0.0.1", "--acp-host", envvar="NATE_NTM_ACP_HOST"),
    acp_port: int = typer.Option(8766, "--acp-port", envvar="NATE_NTM_ACP_PORT"),
    control_host: str | None = typer.Option(None, "--control-host"),
    control_port: int | None = typer.Option(None, "--control-port"),
) -> None:
    """Start an existing materialized swarm by ID."""

    if not 0 <= acp_port <= 65535:
        raise typer.BadParameter("--acp-port must be between 0 and 65535")

    effective_swarm_id = validate_swarm_id(swarm_id)
    store = MetadataStore(effective_swarm_id)
    try:
        swarm = store.load_swarm_state()
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"swarm not found: {effective_swarm_id}") from exc

    config = load_runtime_config(
        project_path=swarm.project_path,
        swarm_id=swarm.swarm_id,
        nate_oha_runtime_mode=nate_oha_runtime_mode,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        prompt_soul_content=prompt_soul_content,
    )

    typer.echo(f"Swarm ACP: tcp://{acp_host}:{acp_port}", err=True)
    typer.echo(
        f"Control API: http://{control_host or config.control_api_host}:"
        f"{control_port if control_port is not None else config.control_api_port}",
        err=True,
    )
    try:
        run_runtime_with_control_api(
            config,
            swarm,
            host=control_host,
            port=control_port,
            acp_host=acp_host,
            acp_port=acp_port,
        )
    except MetadataMissingError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Failed to start runtime: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _parse_params(pairs: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for item in pairs:
        if "=" not in item:
            raise typer.BadParameter(
                f"Invalid parameter {item!r}; expected key=value syntax."
            )
        key, raw = (part.strip() for part in item.split("=", 1))
        if not key:
            raise typer.BadParameter("Parameter key must not be empty")
        try:
            params[key] = json5.loads(raw)
        except ValueError:
            params[key] = raw
    return params


@api_app.command("call")
def api_call(
    method: str = typer.Argument(...),
    param: list[str] = typer.Option([], "--param", "-P"),  # type: ignore[assignment]
    host: str = typer.Option("127.0.0.1", "--host", envvar="NATE_NTM_CONTROL_HOST"),
    port: int = typer.Option(8765, "--port", envvar="NATE_NTM_CONTROL_PORT"),
) -> None:
    """Invoke one runtime control API method."""

    client = JsonRpcHttpClient(host=host, port=port)
    try:
        result = asyncio.run(client.call_for_result(method, _parse_params(param)))
    except JsonRpcClientError as exc:
        payload: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.data is not None:
            payload["data"] = exc.data
        typer.echo(json5.dumps(payload, indent=2), err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Error calling runtime API: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    model = {
        "runtime.get_status": RuntimeStatusResult,
        "swarm.get_overview": SwarmOverviewResult,
        "agent.get_detail": AgentDetailResult,
    }.get(method)
    payload = model.model_validate(result).model_dump() if model else result
    typer.echo(json5.dumps(payload, indent=2))


@app.command("console")
def console(
    host: str = typer.Option("127.0.0.1", "--host", envvar="NATE_NTM_CONTROL_HOST"),
    port: int = typer.Option(8765, "--port", envvar="NATE_NTM_CONTROL_PORT"),
) -> None:
    """Launch the Textual runtime console."""

    from .api.runtime_client import RuntimeClient
    from .tui.app import ConsoleApp
    from .tui.runtime_session import RuntimeSession

    async def run() -> None:
        session = RuntimeSession(client=RuntimeClient(host=host, port=port))
        await session.connect()
        try:
            await ConsoleApp(session=session).run_async()
        finally:
            await session.disconnect()

    try:
        asyncio.run(run())
    except Exception as exc:
        typer.echo(f"Failed to connect to runtime at {host}:{port}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def cli() -> None:
    app()
