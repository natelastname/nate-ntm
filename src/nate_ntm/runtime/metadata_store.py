"""Centralized file-based persistence for complete swarm state."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import json5

from .swarm_state import AgentState as PersistedAgentState, SwarmState as PersistedSwarmState

__all__ = ["MetadataStore", "validate_swarm_id"]


def validate_swarm_id(value: str) -> str:
    """Return a safe swarm ID unchanged or raise ``ValueError``."""

    if not value or value != value.strip():
        raise ValueError("swarm_id must be a non-empty value without surrounding whitespace")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"invalid swarm_id path component: {value!r}")
    return value


def _atomic_write_json(
    path: Path,
    data: Mapping[str, Any],
    *,
    overwrite: bool,
) -> None:
    """Atomically create or replace one JSON5 file in its target directory."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json5.dump(data, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        if overwrite:
            os.replace(tmp_path, path)
        else:
            os.link(tmp_path, path)
            tmp_path.unlink()
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


@dataclass(frozen=True, slots=True)
class MetadataStore:
    """Authoritative store for one swarm under ``~/.nate-ntm/swarms``."""

    swarm_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "swarm_id", validate_swarm_id(self.swarm_id))

    @property
    def metadata_dir(self) -> Path:
        return Path.home() / ".nate-ntm" / "swarms" / self.swarm_id

    @property
    def swarm_path(self) -> Path:
        return self.metadata_dir / "swarm.json"

    def exists(self) -> bool:
        return self.swarm_path.exists()

    def load_swarm_state(self) -> PersistedSwarmState:
        state = PersistedSwarmState.from_json(
            self.swarm_path.read_text(encoding="utf-8")
        )
        state.validate(expected_swarm_id=self.swarm_id)
        return state

    def load_agent_state(self, agent_id: str) -> PersistedAgentState:
        state = self.load_swarm_state()
        try:
            agent_state = state.agents[agent_id]
        except KeyError as exc:
            raise FileNotFoundError(
                f"Agent state not found for {agent_id!r}"
            ) from exc
        if agent_state.agent_id != agent_id:
            raise ValueError(
                f"Agent state for id {agent_id!r} contains agent_id "
                f"{agent_state.agent_id!r}"
            )
        return agent_state

    def save_agent_state(self, agent_state: PersistedAgentState) -> None:
        if not agent_state.agent_id:
            raise ValueError("AgentState.agent_id must not be empty")
        try:
            state = self.load_swarm_state()
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Swarm state not found; cannot save agent state before the swarm has been created."
            ) from exc
        state.agents[agent_state.agent_id] = agent_state
        state.last_updated_at = datetime.utcnow()
        self.save_swarm_state(state)

    def load_all_agent_states(self) -> Dict[str, PersistedAgentState]:
        try:
            return dict(self.load_swarm_state().agents)
        except FileNotFoundError:
            return {}

    def save_all_agent_states(self, agents: Iterable[PersistedAgentState]) -> None:
        try:
            state = self.load_swarm_state()
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Swarm state not found; cannot save agent state before the swarm has been created."
            ) from exc

        updated = False
        for agent_state in agents:
            if not agent_state.agent_id:
                raise ValueError("AgentState.agent_id must not be empty")
            state.agents[agent_state.agent_id] = agent_state
            updated = True
        if updated:
            state.last_updated_at = datetime.utcnow()
            self.save_swarm_state(state)

    def save_swarm_state(
        self,
        state: PersistedSwarmState,
        *,
        overwrite: bool = True,
    ) -> None:
        state.validate(expected_swarm_id=self.swarm_id)
        _atomic_write_json(
            self.swarm_path,
            state.model_dump(mode="json"),
            overwrite=overwrite,
        )
