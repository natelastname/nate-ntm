"""Build nate-oha process launches from materialized agent state."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import json5
from nate_oha.config import NateOHAConfig

from ..config.runtime_config import RuntimeConfig
from .swarm_state import AgentState

__all__ = [
    "NateOhaLaunchSpec",
    "build_nate_oha_launch_spec",
    "materialize_nate_oha_config",
]


@dataclass(frozen=True, slots=True)
class NateOhaLaunchSpec:
    executable: str
    base_config: Path
    cwd: Path
    runtime_mode: str
    conversation_id: str | None = None
    model: str | None = None
    api_key: str | None = None
    prompt_soul_content: str | None = None
    extra_overrides: Mapping[str, str] = field(default_factory=dict)

    def iter_overrides(self) -> Sequence[str]:
        values: dict[str, str] = {"runtime.mode": self.runtime_mode}
        if self.model:
            values["llm.model"] = self.model
        if self.api_key:
            values["llm.api_key"] = self.api_key
        if self.prompt_soul_content is not None:
            values["prompt.soul_content"] = self.prompt_soul_content
        conflicts = values.keys() & self.extra_overrides.keys()
        if conflicts:
            raise ValueError(
                "extra_overrides may not replace structured paths: "
                + ", ".join(sorted(conflicts))
            )
        values.update({str(key): str(value) for key, value in self.extra_overrides.items()})
        return [f"{key}={values[key]}" for key in sorted(values)]

    def to_argv(self) -> Sequence[str]:
        argv = [self.executable, "acp", "--config", str(self.base_config)]
        if self.conversation_id:
            argv.extend(["--resume", self.conversation_id])
        for override in self.iter_overrides():
            argv.extend(["--set", override])
        return argv


def build_nate_oha_launch_spec(
    *,
    config: RuntimeConfig,
    metadata: AgentState,
) -> NateOhaLaunchSpec:
    """Launch from the complete configuration persisted for this agent."""

    persisted = metadata.nate_oha_config
    runtime_mode = config.nate_oha_runtime_mode or str(persisted.runtime.mode.value)
    return NateOhaLaunchSpec(
        executable=config.nate_oha_executable,
        base_config=materialize_nate_oha_config(config=persisted),
        cwd=config.project_path,
        runtime_mode=runtime_mode,
        conversation_id=metadata.conversation_id or None,
        model=config.llm_model,
        api_key=config.llm_api_key,
        prompt_soul_content=config.prompt_soul_content,
    )


def materialize_nate_oha_config(
    *,
    config: NateOHAConfig,
    prefix: str = "nate-ntm-nate-oha-config-",
) -> Path:
    """Write one complete nate-oha configuration to a temporary JSON5 file."""

    path = Path(tempfile.mkdtemp(prefix=prefix)) / "nate-oha-config.json"
    path.write_text(
        json5.dumps(config.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
