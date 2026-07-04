"""Event-driven runtime scheduler skeleton.

This module defines a minimal :class:`RuntimeScheduler` abstraction for
US1. Its responsibilities in this slice are intentionally narrow:

* Bridge between :class:`SwarmMetadata` (configured agents) and
  :class:`RuntimeState` by asking :class:`AgentSupervisor` to ensure all
  agents are registered.
* Provide a place for future event loop and integration wiring without
  entangling the :class:`RuntimeDaemon` itself with asynchronous
  mechanics.

It does **not** yet implement a real event loop, Agent Mail polling, or
ACP turn management; those responsibilities are reserved for later
iterations of T016/T017 and follow-on stories.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.runtime_config import RuntimeConfig
from .agents import AgentSupervisor
from .metadata_store import SwarmMetadata
from .state import RuntimeState

__all__ = ["RuntimeScheduler"]


@dataclass(slots=True)
class RuntimeScheduler:
    """Minimal scheduler facade for the runtime.

    In this phase the scheduler is a thin facade owned by the
    :class:`~nate_ntm.runtime.daemon.RuntimeDaemon`. It delegates agent
    registration and (later) subprocess management to
    :class:`AgentSupervisor`.
    """

    config: RuntimeConfig
    state: RuntimeState
    swarm_metadata: SwarmMetadata
    agent_supervisor: AgentSupervisor

    running: bool = False

    def start(self) -> None:
        """Initialize scheduler-managed state.

        For US1 this simply ensures that all agents described in
        :class:`SwarmMetadata` have corresponding entries in
        :class:`RuntimeState.agents`. More sophisticated behavior (event
        loop, timers, ACP/Agent Mail integration) will be layered on in
        future work without changing this high-level entry point.
        """

        if self.running:
            return

        # Ensure that runtime state reflects all configured agents.
        self.agent_supervisor.ensure_agents_registered()

        self.running = True

    def stop(self) -> None:
        """Stop the scheduler (stub).

        In a full implementation this would coordinate graceful
        termination of the event loop and any outstanding work. For now
        it is a simple flag used to mirror the eventual lifecycle.
        """

        self.running = False
