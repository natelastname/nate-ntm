"""Unit tests for RuntimeScheduler (runtime/scheduler.py).

These tests exercise the initial T017 scaffolding: a scheduler that
coordinates agent registration via AgentSupervisor but does not yet
implement a full event loop.
"""

from __future__ import annotations

from datetime import datetime

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.agents import AgentSupervisor
from nate_ntm.runtime.metadata_store import AgentMetadata, SwarmMetadata
from nate_ntm.runtime.scheduler import RuntimeScheduler
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState


def _make_runtime_state(config: RuntimeConfig) -> RuntimeState:
    return RuntimeState(config=config)



def _make_config(project_root) -> RuntimeConfig:
    project_root.mkdir(parents=True, exist_ok=True)
    return load_runtime_config(project_path=project_root)


def _make_swarm_metadata(
    config: RuntimeConfig, *, agents: dict[str, AgentMetadata] | None = None
) -> SwarmMetadata:
    now = datetime(2026, 7, 3, 12, 0, 0)
    return SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="",
        created_at=now,
        last_updated_at=now,
        agents=agents or {},
    )


def test_scheduler_start_registers_and_launches_agents_via_supervisor(tmp_path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    state = _make_runtime_state(config)

    a1 = AgentMetadata(agent_id="a1", display_name="Agent One")
    swarm = _make_swarm_metadata(config, agents={"a1": a1})

    supervisor = AgentSupervisor(config=config, state=state, swarm_metadata=swarm)
    scheduler = RuntimeScheduler(
        config=config,
        state=state,
        swarm_metadata=swarm,
        agent_supervisor=supervisor,
    )

    assert scheduler.running is False
    assert state.agents == {}

    scheduler.start()

    # The scheduler should now be marked as running.
    assert scheduler.running is True

    # And the runtime state should contain entries for the configured agents.
    assert set(state.agents.keys()) == {"a1"}
    assert state.agents["a1"].status is AgentStatus.IDLE
    assert state.agents["a1"].subprocess_handle is not None


def test_scheduler_start_is_idempotent(tmp_path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    state = _make_runtime_state(config)

    a1 = AgentMetadata(agent_id="a1", display_name="Agent One")
    swarm = _make_swarm_metadata(config, agents={"a1": a1})

    supervisor = AgentSupervisor(config=config, state=state, swarm_metadata=swarm)
    scheduler = RuntimeScheduler(
        config=config,
        state=state,
        swarm_metadata=swarm,
        agent_supervisor=supervisor,
    )

    scheduler.start()
    first_state = dict(state.agents)

    # Second call should be a no-op because `running` is already True.
    scheduler.start()

    assert scheduler.running is True
    assert state.agents == first_state


def test_scheduler_stop_clears_running_flag(tmp_path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    state = _make_runtime_state(config)

    a1 = AgentMetadata(agent_id="a1", display_name="Agent One")
    swarm = _make_swarm_metadata(config, agents={"a1": a1})

    supervisor = AgentSupervisor(config=config, state=state, swarm_metadata=swarm)
    scheduler = RuntimeScheduler(
        config=config,
        state=state,
        swarm_metadata=swarm,
        agent_supervisor=supervisor,
    )

    scheduler.start()
    assert scheduler.running is True

    scheduler.stop()
    assert scheduler.running is False


def test_scheduler_respects_preseeded_runtime_state(tmp_path) -> None:
    """Scheduler should not overwrite pre-seeded AgentRuntimeState entries.

    This mirrors how the RuntimeDaemon and tests seed state before
    calling start(); scheduler.start() must only *add* missing entries.
    """

    project = tmp_path / "project"
    config = _make_config(project)
    state = _make_runtime_state(config)

    # Two agents are configured in metadata, but one already has runtime state.
    a1 = AgentMetadata(agent_id="a1", display_name="Agent One")
    a2 = AgentMetadata(agent_id="a2", display_name="Agent Two")
    swarm = _make_swarm_metadata(config, agents={"a1": a1, "a2": a2})

    preexisting = AgentRuntimeState(
        agent_id="a1",
        status=AgentStatus.RUNNING,
    )
    state.agents["a1"] = preexisting

    supervisor = AgentSupervisor(config=config, state=state, swarm_metadata=swarm)
    scheduler = RuntimeScheduler(
        config=config,
        state=state,
        swarm_metadata=swarm,
        agent_supervisor=supervisor,
    )

    scheduler.start()

    # Pre-existing entry should be preserved.
    assert state.agents["a1"] is preexisting
    assert state.agents["a1"].status is AgentStatus.RUNNING

    # And the second agent should have been added and launched.
    assert "a2" in state.agents
    assert state.agents["a2"].status is AgentStatus.IDLE
    assert state.agents["a2"].subprocess_handle is not None
