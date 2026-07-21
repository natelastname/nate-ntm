"""Minimal runtime scheduler facade."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config.runtime_config import RuntimeConfig
from .agents import AgentSupervisor
from .state import RuntimeState
from .swarm_state import SwarmState

__all__ = ["RuntimeScheduler"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeScheduler:
    """Register agents and coordinate simple lifecycle transitions."""

    config: RuntimeConfig
    state: RuntimeState
    swarm_state: SwarmState
    agent_supervisor: AgentSupervisor
    running: bool = False

    def start(self) -> None:
        if self.running:
            return
        self.agent_supervisor.launch_all_agents()
        self.running = True
        logger.info(
            "scheduler_started",
            extra={
                "swarm_id": self.swarm_state.swarm_id,
                "project_path": str(self.config.project_path),
                "agent_count": len(self.state.agents),
            },
        )

    def stop(self) -> None:
        self.running = False

    def mark_agent_failed(self, agent_id: str, *, error: str | None = None) -> None:
        self.agent_supervisor.mark_agent_failed(agent_id, error=error)

    def restart_agent(self, agent_id: str) -> None:
        self.agent_supervisor.restart_agent(agent_id)
