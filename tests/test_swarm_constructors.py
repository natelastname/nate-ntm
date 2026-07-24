from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from nate_oha.config import NateOHAConfig
from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_ntm.swarm_constructors import CONSTRUCTORS, agent_mail_constructor, apply_constructors

runner = CliRunner()


def _config(*, agent_mail: dict[str, object] | None = None) -> NateOHAConfig:
    return NateOHAConfig.model_validate(
        {
            "runtime": {"mode": "agent"},
            "llm": {"model": "openai/test"},
            "openhands": {"confirmation_mode": "llm-approve"},
            "prompt": {},
            "features": {"agent_mail": agent_mail},
        }
    )


def _swarm(project: Path | None = None) -> SwarmState:
    now = datetime.now(timezone.utc)
    return SwarmState(
        swarm_id="demo",
        project_path=project or Path.cwd(),
        created_at=now,
        last_updated_at=now,
        agents={
            "Planner": AgentState(
                agent_id="Planner",
                display_name="Planner",
                nate_oha_config=_config(),
            ),
            "code_reviewer": AgentState(
                agent_id="code_reviewer",
                display_name="Code Reviewer",
                nate_oha_config=_config(),
            ),
        },
    )


def _agent_files(project: Path) -> list[Path]:
    paths = [project / "Planner.json", project / "code_reviewer.json"]
    for path in paths:
        path.write_text(_config().model_dump_json(indent=2), encoding="utf-8")
    return paths


def _create_args(project: Path, paths: list[Path], *extra: str) -> list[str]:
    args = ["swarm", "create", "--project", str(project), "--swarm-id", "demo"]
    for path in paths:
        args.extend(["--agent", str(path)])
    return [*args, *extra]


def test_cli_dry_run_materializes_complete_agent_mail_swarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NATE_NTM_AGENT_MAIL_URL", "http://mail.test")
    paths = _agent_files(tmp_path)

    result = runner.invoke(
        app,
        _create_args(tmp_path, paths, "--constructor", "agent-mail", "--dry-run"),
    )

    assert result.exit_code == 0, result.output
    swarm = SwarmState.model_validate(json.loads(result.stdout))
    assert swarm.agent_mail_project_id == "demo-agent-mail"
    assert swarm.runtime_options["constructors"] == ["agent-mail"]
    assert not (tmp_path / ".nate_ntm" / "swarm.json").exists()

    planner = swarm.agents["Planner"].nate_oha_config.features.agent_mail
    reviewer = swarm.agents["code_reviewer"].nate_oha_config.features.agent_mail
    assert planner is not None and reviewer is not None
    assert planner.project == reviewer.project == Path("demo-agent-mail")
    assert planner.agent_identity == "planner"
    assert reviewer.agent_identity == "code-reviewer"
    assert planner.credentials_ref != reviewer.credentials_ref
    assert planner.upstream_url == reviewer.upstream_url == "http://mail.test"


def test_persisted_constructed_swarm_round_trips(tmp_path: Path) -> None:
    paths = _agent_files(tmp_path)

    result = runner.invoke(
        app,
        _create_args(tmp_path, paths, "--constructor", "agent-mail"),
    )

    assert result.exit_code == 0, result.output
    loaded = MetadataStore(
        load_runtime_config(project_path=tmp_path, swarm_id="demo")
    ).load_swarm_state()
    assert loaded.runtime_options["constructors"] == ["agent-mail"]
    assert loaded.agent_mail_project_id == "demo-agent-mail"
    assert {
        agent.nate_oha_config.features.agent_mail.agent_identity
        for agent in loaded.agents.values()
        if agent.nate_oha_config.features.agent_mail is not None
    } == {"planner", "code-reviewer"}


def test_constructors_run_in_requested_order() -> None:
    def append(name: str):
        def constructor(swarm: SwarmState) -> SwarmState:
            result = swarm.model_copy(deep=True)
            result.runtime_options.setdefault("order", []).append(name)
            return result

        return constructor

    result = apply_constructors(
        _swarm(),
        ["first", "second"],
        registry={"first": append("first"), "second": append("second")},
    )

    assert result.runtime_options["order"] == ["first", "second"]
    assert result.runtime_options["constructors"] == ["first", "second"]


def test_constructor_failure_surfaces_without_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SentinelError(Exception):
        pass

    def explode(swarm: SwarmState) -> SwarmState:
        raise SentinelError("boom")

    monkeypatch.setitem(CONSTRUCTORS, "explode", explode)
    paths = _agent_files(tmp_path)

    result = runner.invoke(app, _create_args(tmp_path, paths, "--constructor", "explode"))

    assert isinstance(result.exception, SentinelError)
    assert not (tmp_path / ".nate_ntm" / "swarm.json").exists()


def test_duplicate_constructor_is_rejected() -> None:
    with pytest.raises(ValueError, match="more than once"):
        apply_constructors(_swarm(), ["agent-mail", "agent-mail"])


def test_conflicting_explicit_agent_mail_identity_is_rejected() -> None:
    swarm = _swarm()
    swarm.agents["Planner"].nate_oha_config = _config(
        agent_mail={
            "enabled": True,
            "project": "demo-agent-mail",
            "agent_identity": "someone-else",
            "credentials_ref": "secret",
            "upstream_url": "http://mail.test",
        }
    )

    with pytest.raises(ValueError, match="conflicting Agent Mail identity"):
        agent_mail_constructor(swarm)
