"""Agent subprocess launch and lifecycle supervision primitives (skeleton).

This module provides the *internal* interfaces for managing agents within a
single-swarm runtime process. It is intentionally conservative for US1:

* It wires :class:`AgentMetadata` from the persisted swarm description
  into :class:`AgentRuntimeState` entries in :class:`RuntimeState`.
* It creates per-agent :class:`~nate_ntm.runtime.events.AgentEventStream`
  instances so that later user stories can attach event streaming without
  changing the basic wiring.
* It does **not** yet launch real subprocesses or ACP connections; those
  behaviors are added in follow-up work for FR-004/FR-005.

This keeps the core runtime data structures and responsibilities aligned
with the spec (see ``data-model.md`` §3) without over-committing to a
particular scheduler or process model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..config.runtime_config import RuntimeConfig
from .events import AgentEventStream
from .metadata_store import AgentMetadata, SwarmMetadata
from .state import AgentRuntimeState, AgentStatus, RuntimeState

__all__ = ["AgentSupervisor"]


@dataclass(slots=True)
class AgentSupervisor:
    """Manage in-memory runtime state for agents.

    For US1 this focuses on establishing and maintaining the mapping
    between persisted :class:`AgentMetadata` records and
    :class:`AgentRuntimeState` entries in :class:`RuntimeState`.

    Later phases will extend this class to:

    * Launch and supervise agent subprocesses.
    * Establish and refresh ACP connections.
    * Surface subprocess/ACP events into the scheduler.
    * Apply restart policies based on :class:`AgentMetadata.restart_policy`.
    """

    config: RuntimeConfig
    state: RuntimeState
    swarm_metadata: SwarmMetadata

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def iter_configured_agents(self) -> Iterable[AgentMetadata]:
        """Iterate over :class:`AgentMetadata` records from the swarm.

        This is a thin wrapper over ``swarm_metadata.agents.values()``
        that exists primarily to keep the call-sites within this module
        clear and testable.
        """

        return self.swarm_metadata.agents.values()

    def ensure_agent_runtime_state(self, metadata: AgentMetadata) -> AgentRuntimeState:
        """Ensure that ``RuntimeState.agents`` has an entry for ``metadata``.

        If a runtime state for this agent already exists, it is returned
        unchanged. Otherwise a new :class:`AgentRuntimeState` instance is
        created with a default ``Starting`` status and attached
        :class:`AgentEventStream`.
        """

        agent_id = metadata.agent_id

        existing = self.state.agents.get(agent_id)
        if existing is not None:
            return existing

        runtime_state = AgentRuntimeState(
            agent_id=agent_id,
            status=AgentStatus.STARTING,
            event_stream=AgentEventStream(agent_id=agent_id),
        )
        self.state.agents[agent_id] = runtime_state
        return runtime_state

    def ensure_agents_registered(self) -> None:
        """Ensure all configured agents have a runtime state entry.

        This is the primary entry point used by the scheduler/daemon
        during startup. It walks the agents defined in
        :class:`SwarmMetadata` and ensures that each has a corresponding
        :class:`AgentRuntimeState` in :class:`RuntimeState`.

        Existing runtime entries are left untouched so that tests (and
        later, the real scheduler) can seed richer state before
        registration occurs.
        """

        for metadata in self.iter_configured_agents():
            self.ensure_agent_runtime_state(metadata)

    # ------------------------------------------------------------------
    # Placeholders for future lifecycle management
    # ------------------------------------------------------------------

    # The following methods capture *intended* responsibilities but are
    # deliberately left as no-ops or minimal stubs for US1. They are
    # included to clarify ownership and to keep call sites stable as we
    # iterate on the scheduler and adapter implementations.

    def launch_all_agents(self) -> None:
        """Launch all configured agents (stub for US1).

        In the full implementation, this will:

        * Inspect each :class:`AgentMetadata.launch_config`.
        * Start a subprocess per agent.
        * Populate ``AgentRuntimeState.subprocess_handle`` and initial
          ACP connection state.

        For now, we limit ourselves to ensuring that runtime state
        entries exist; subprocess management is deferred to a later
        revision of T016.
        """

        self.ensure_agents_registered()

    # Additional lifecycle hooks (e.g. ``handle_subprocess_exit``) will
    # be introduced alongside concrete scheduler and ACP integrations.
