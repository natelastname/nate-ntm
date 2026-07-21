"""Runtime configuration model and loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values, find_dotenv

__all__ = ["RuntimeConfig", "load_runtime_config"]

_DEFAULT_CONTROL_HOST = "127.0.0.1"
_DEFAULT_CONTROL_PORT = 8765
_DEFAULT_SWARM_ID = "default"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    project_path: Path
    metadata_dir: Path
    control_api_host: str = _DEFAULT_CONTROL_HOST
    control_api_port: int = _DEFAULT_CONTROL_PORT
    swarm_id: str = _DEFAULT_SWARM_ID
    agent_mail_project: str | None = None
    agent_mail_upstream_url: str | None = None
    nate_oha_executable: str = "nate-oha"
    nate_oha_config_path: Path | None = None
    nate_oha_runtime_mode: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    prompt_soul_content: str | None = None
    agent_mail_enabled: bool | None = None


def load_runtime_config(
    *,
    project_path: Path | str | None = None,
    metadata_dir: Path | str | None = None,
    control_api_host: str | None = None,
    control_api_port: int | str | None = None,
    swarm_id: str | None = None,
    agent_mail_project: str | None = None,
    agent_mail_upstream_url: str | None = None,
    nate_oha_executable: str | None = None,
    nate_oha_config_path: Path | str | None = None,
    nate_oha_runtime_mode: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    prompt_soul_content: str | None = None,
    agent_mail_enabled: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Resolve explicit values, environment values, and stable defaults."""

    values = _environment(env)
    project = _project_path(project_path or values.get("NATE_NTM_PROJECT_DIR"))
    metadata = _metadata_dir(
        metadata_dir or values.get("NATE_NTM_METADATA_DIR"), project
    )
    return RuntimeConfig(
        project_path=project,
        metadata_dir=metadata,
        control_api_host=(
            control_api_host
            or values.get("NATE_NTM_CONTROL_HOST")
            or _DEFAULT_CONTROL_HOST
        ),
        control_api_port=_control_port(
            control_api_port or values.get("NATE_NTM_CONTROL_PORT")
        ),
        swarm_id=swarm_id or values.get("NATE_NTM_SWARM_ID") or _DEFAULT_SWARM_ID,
        agent_mail_project=_optional(
            agent_mail_project
            if agent_mail_project is not None
            else values.get("NATE_NTM_AGENT_MAIL_PROJECT")
            or values.get("AGENT_MAIL_PROJECT")
        ),
        agent_mail_upstream_url=_optional(
            agent_mail_upstream_url
            if agent_mail_upstream_url is not None
            else values.get("NATE_NTM_AGENT_MAIL_URL")
            or values.get("AGENT_MAIL_UPSTREAM_URL")
            or values.get("AGENT_MAIL_URL")
        ),
        nate_oha_executable=_optional(
            nate_oha_executable
            if nate_oha_executable is not None
            else values.get("NATE_NTM_NATE_OHA_EXECUTABLE")
        )
        or "nate-oha",
        nate_oha_config_path=_optional_path(
            nate_oha_config_path
            if nate_oha_config_path is not None
            else values.get("NATE_NTM_NATE_OHA_CONFIG"),
            project,
        ),
        nate_oha_runtime_mode=_optional(
            nate_oha_runtime_mode
            if nate_oha_runtime_mode is not None
            else values.get("NATE_NTM_NATE_OHA_RUNTIME_MODE")
        ),
        llm_model=_optional(
            llm_model if llm_model is not None else values.get("NATE_NTM_LLM_MODEL")
        ),
        llm_api_key=_optional(
            llm_api_key
            if llm_api_key is not None
            else values.get("NATE_NTM_LLM_API_KEY")
        ),
        prompt_soul_content=_optional(
            prompt_soul_content
            if prompt_soul_content is not None
            else values.get("NATE_NTM_PROMPT_SOUL_CONTENT")
        ),
        agent_mail_enabled=_optional_bool(
            agent_mail_enabled,
            values.get("NATE_NTM_AGENT_MAIL_ENABLED"),
        ),
    )


def _environment(env: Mapping[str, str] | None) -> Mapping[str, str]:
    if env is not None:
        return env
    path = find_dotenv(usecwd=True)
    values = {
        key: value
        for key, value in (dotenv_values(path).items() if path else ())
        if value is not None
    }
    values.update(os.environ)
    return values


def _project_path(raw: Path | str | None) -> Path:
    path = Path(raw or os.getcwd()).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Project path does not exist or is not a directory: {path}")
    return path


def _metadata_dir(raw: Path | str | None, project: Path) -> Path:
    path = Path(raw) if raw is not None else project / ".nate_ntm"
    path = (project / path).resolve() if not path.is_absolute() else path.expanduser().resolve()
    try:
        path.relative_to(project)
    except ValueError:
        if path.parent != project.parent:
            raise ValueError(
                "metadata_dir must be under the project or adjacent to it"
            )
    return path


def _control_port(raw: int | str | None) -> int:
    try:
        port = int(raw) if raw is not None else _DEFAULT_CONTROL_PORT
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid control API port value: {raw!r}") from exc
    if not 1024 < port <= 65535:
        raise ValueError("Control API port must be between 1025 and 65535")
    return port


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _optional_path(value: Path | str | None, project: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return (project / path).resolve() if not path.is_absolute() else path.expanduser().resolve()


def _optional_bool(value: bool | None, raw: str | None) -> bool | None:
    if value is not None:
        return value
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw!r}")
