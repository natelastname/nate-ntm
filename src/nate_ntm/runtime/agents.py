"""In-memory agent lifecycle supervision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..config.runtime_config import RuntimeConfig
from .state import AgentRuntimeState, AgentStatus, RuntimeState
from .swarm_state import AgentState, SwarmState

__all__ = ["AgentSupervisor"]


@dataclass(slots=True)
class AgentSupervisor:
    """Maintain runtime lifecycle state for configured agents."""

    config: RuntimeConfig
    state: RuntimeState
    swarm_state: SwarmState

    def iter_configured_agents(self) -> Iterable[AgentState]:
        return self.swarm_state.agents.values()

    def ensure_agent_runtime_state(self, agent_state: AgentState) -> AgentRuntimeState:
        existing = self.state.agents.get(agent_state.agent_id)
        if existing is not None:
            return existing

        runtime_state = AgentRuntimeState(agent_id=agent_state.agent_id)
        self.state.agents[agent_state.agent_id] = runtime_state
        return runtime_state

    def ensure_agents_registered(self) -> None:
        for agent_state in self.iter_configured_agents():
            self.ensure_agent_runtime_state(agent_state)

    def mark_agent_failed(
        self, agent_id: str, *, error: str | None = None
    ) -> AgentRuntimeState:
        runtime_state = self._require_agent(agent_id)
        runtime_state.status = AgentStatus.FAILED
        runtime_state.last_error = error
        return runtime_state

    def restart_agent(self, agent_id: str) -> AgentRuntimeState:
        runtime_state = self._require_agent(agent_id)
        runtime_state.status = AgentStatus.STARTING
        runtime_state.last_error = None
        runtime_state.subprocess_handle = object()
        runtime_state.status = AgentStatus.IDLE
        return runtime_state

    def launch_all_agents(self) -> None:
        existing_ids = set(self.state.agents)
        self.ensure_agents_registered()
        for agent_id, runtime_state in self.state.agents.items():
            if (
                agent_id not in existing_ids
                and runtime_state.status is AgentStatus.STARTING
                and runtime_state.subprocess_handle is None
            ):
                runtime_state.subprocess_handle = object()
                runtime_state.status = AgentStatus.IDLE

    def _require_agent(self, agent_id: str) -> AgentRuntimeState:
        runtime_state = self.state.agents.get(agent_id)
        if runtime_state is None:
            raise KeyError(f"Unknown agent_id: {agent_id!r}")
        return runtime_state
