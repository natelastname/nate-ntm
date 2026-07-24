"""Runtime-only configuration for an already materialized swarm."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values, find_dotenv

__all__ = ["RuntimeConfig", "load_runtime_config"]

_DEFAULT_CONTROL_HOST = "127.0.0.1"
_DEFAULT_CONTROL_PORT = 8765


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    project_path: Path
    swarm_id: str
    control_api_host: str = _DEFAULT_CONTROL_HOST
    control_api_port: int = _DEFAULT_CONTROL_PORT
    nate_oha_executable: str = "nate-oha"
    nate_oha_runtime_mode: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    prompt_soul_content: str | None = None


def load_runtime_config(
    *,
    project_path: Path | str,
    swarm_id: str,
    control_api_host: str | None = None,
    control_api_port: int | str | None = None,
    nate_oha_executable: str | None = None,
    nate_oha_runtime_mode: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    prompt_soul_content: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Combine persisted swarm identity with runtime-only overrides."""

    values = _environment(env)
    project = _project_path(project_path)
    if not swarm_id or swarm_id != swarm_id.strip():
        raise ValueError("swarm_id must be non-empty without surrounding whitespace")

    return RuntimeConfig(
        project_path=project,
        swarm_id=swarm_id,
        control_api_host=(
            control_api_host
            if control_api_host is not None
            else values.get("NATE_NTM_CONTROL_HOST") or _DEFAULT_CONTROL_HOST
        ),
        control_api_port=_control_port(
            control_api_port
            if control_api_port is not None
            else values.get("NATE_NTM_CONTROL_PORT")
        ),
        nate_oha_executable=_optional(
            nate_oha_executable
            if nate_oha_executable is not None
            else values.get("NATE_NTM_NATE_OHA_EXECUTABLE")
        )
        or "nate-oha",
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


def _project_path(raw: Path | str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Project path does not exist or is not a directory: {path}")
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
