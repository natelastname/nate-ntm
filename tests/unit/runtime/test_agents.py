from __future__ import annotations

from datetime import datetime

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.agents import AgentSupervisor
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_oha.config import build_default_config


def _config(tmp_path) -> RuntimeConfig:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return load_runtime_config(project_path=project)


def _swarm(
    config: RuntimeConfig,
    agents: dict[str, AgentState] | None = None,
) -> SwarmState:
    now = datetime(2026, 7, 3, 12, 0, 0)
    return SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="",
        created_at=now,
        last_updated_at=now,
        agents=agents or {},
    )


def _agent(agent_id: str, display_name: str) -> AgentState:
    return AgentState(
        agent_id=agent_id,
        display_name=display_name,
        nate_oha_config=build_default_config(),
    )


def _supervisor(tmp_path, agents: dict[str, AgentState]) -> tuple[AgentSupervisor, RuntimeState]:
    config = _config(tmp_path)
    state = RuntimeState(config=config)
    return AgentSupervisor(config, state, _swarm(config, agents)), state


def test_iter_configured_agents(tmp_path) -> None:
    a1 = _agent("a1", "Agent One")
    a2 = _agent("a2", "Agent Two")
    supervisor, _ = _supervisor(tmp_path, {"a1": a1, "a2": a2})
    assert list(supervisor.iter_configured_agents()) == [a1, a2]


def test_ensure_agent_runtime_state_creates_starting_entry(tmp_path) -> None:
    metadata = _agent("agent-1", "Agent One")
    supervisor, state = _supervisor(tmp_path, {metadata.agent_id: metadata})

    runtime = supervisor.ensure_agent_runtime_state(metadata)

    assert runtime is state.agents[metadata.agent_id]
    assert runtime.agent_id == metadata.agent_id
    assert runtime.status is AgentStatus.STARTING
    assert not hasattr(runtime, "event_stream")


def test_ensure_agent_runtime_state_preserves_existing_entry(tmp_path) -> None:
    metadata = _agent("agent-1", "Agent One")
    supervisor, state = _supervisor(tmp_path, {metadata.agent_id: metadata})
    existing = AgentRuntimeState(
        agent_id=metadata.agent_id,
        status=AgentStatus.RUNNING,
        last_error="boom",
    )
    state.agents[metadata.agent_id] = existing

    assert supervisor.ensure_agent_runtime_state(metadata) is existing
    assert existing.status is AgentStatus.RUNNING
    assert existing.last_error == "boom"


def test_ensure_agents_registered_is_additive(tmp_path) -> None:
    a1 = _agent("a1", "Agent One")
    a2 = _agent("a2", "Agent Two")
    supervisor, state = _supervisor(tmp_path, {"a1": a1, "a2": a2})
    existing = AgentRuntimeState(agent_id="a1", status=AgentStatus.RUNNING)
    state.agents["a1"] = existing

    supervisor.ensure_agents_registered()

    assert state.agents["a1"] is existing
    assert state.agents["a2"].status is AgentStatus.STARTING


def test_launch_all_agents_initializes_new_agents_once(tmp_path) -> None:
    a1 = _agent("a1", "Agent One")
    a2 = _agent("a2", "Agent Two")
    supervisor, state = _supervisor(tmp_path, {"a1": a1, "a2": a2})

    supervisor.launch_all_agents()
    first_handles = {
        agent_id: runtime.subprocess_handle
        for agent_id, runtime in state.agents.items()
    }

    assert set(state.agents) == {"a1", "a2"}
    assert all(runtime.status is AgentStatus.IDLE for runtime in state.agents.values())
    assert all(handle is not None for handle in first_handles.values())

    state.agents["a1"].status = AgentStatus.RUNNING
    supervisor.launch_all_agents()

    assert {
        agent_id: runtime.subprocess_handle
        for agent_id, runtime in state.agents.items()
    } == first_handles
    assert state.agents["a1"].status is AgentStatus.RUNNING
    assert state.agents["a2"].status is AgentStatus.IDLE


def test_mark_failed_and_restart_update_lifecycle_state(tmp_path) -> None:
    metadata = _agent("agent-1", "Agent One")
    supervisor, state = _supervisor(tmp_path, {metadata.agent_id: metadata})
    supervisor.ensure_agents_registered()
    runtime = state.agents[metadata.agent_id]

    assert supervisor.mark_agent_failed(metadata.agent_id, error="boom") is runtime
    assert runtime.status is AgentStatus.FAILED
    assert runtime.last_error == "boom"

    assert supervisor.restart_agent(metadata.agent_id) is runtime
    assert runtime.status is AgentStatus.IDLE
    assert runtime.last_error is None
    assert runtime.subprocess_handle is not None
