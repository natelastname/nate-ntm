from __future__ import annotations

from datetime import datetime

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.agents import AgentSupervisor
from nate_ntm.runtime.scheduler import RuntimeScheduler
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_oha.config import build_default_config


def _scheduler(
    tmp_path,
    agents: dict[str, AgentState],
) -> tuple[RuntimeScheduler, RuntimeState]:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config: RuntimeConfig = load_runtime_config(project_path=project)
    state = RuntimeState(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="",
        created_at=now,
        last_updated_at=now,
        agents=agents,
    )
    supervisor = AgentSupervisor(config, state, swarm)
    return RuntimeScheduler(config, state, swarm, supervisor), state


def _agent(agent_id: str) -> AgentState:
    return AgentState(
        agent_id=agent_id,
        display_name=agent_id,
        nate_oha_config=build_default_config(),
    )


def test_start_registers_and_launches_agents(tmp_path) -> None:
    scheduler, state = _scheduler(tmp_path, {"a1": _agent("a1")})

    scheduler.start()

    assert scheduler.running is True
    assert state.agents["a1"].status is AgentStatus.IDLE
    assert state.agents["a1"].subprocess_handle is not None


def test_start_is_idempotent_and_preserves_existing_state(tmp_path) -> None:
    scheduler, state = _scheduler(
        tmp_path,
        {"a1": _agent("a1"), "a2": _agent("a2")},
    )
    existing = AgentRuntimeState(agent_id="a1", status=AgentStatus.RUNNING)
    state.agents["a1"] = existing

    scheduler.start()
    first_handles = {
        agent_id: runtime.subprocess_handle
        for agent_id, runtime in state.agents.items()
    }
    scheduler.start()

    assert scheduler.running is True
    assert state.agents["a1"] is existing
    assert state.agents["a1"].status is AgentStatus.RUNNING
    assert state.agents["a2"].status is AgentStatus.IDLE
    assert {
        agent_id: runtime.subprocess_handle
        for agent_id, runtime in state.agents.items()
    } == first_handles


def test_stop_clears_running_flag(tmp_path) -> None:
    scheduler, _ = _scheduler(tmp_path, {"a1": _agent("a1")})
    scheduler.start()
    scheduler.stop()
    assert scheduler.running is False


def test_failure_and_restart_delegate_to_supervisor(tmp_path) -> None:
    scheduler, state = _scheduler(tmp_path, {"a1": _agent("a1")})
    scheduler.agent_supervisor.ensure_agents_registered()
    runtime = state.agents["a1"]

    scheduler.mark_agent_failed("a1", error="boom")
    assert runtime.status is AgentStatus.FAILED
    assert runtime.last_error == "boom"

    scheduler.restart_agent("a1")
    assert runtime.status is AgentStatus.IDLE
    assert runtime.last_error is None
    assert runtime.subprocess_handle is not None


def test_scheduler_has_no_observability_or_mail_event_dependency(tmp_path) -> None:
    scheduler, _ = _scheduler(tmp_path, {"a1": _agent("a1")})
    assert not hasattr(scheduler, "agent_mail_client")
    assert not hasattr(scheduler.agent_supervisor, "on_agent_event")
