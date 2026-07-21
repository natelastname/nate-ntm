from __future__ import annotations

from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState, RuntimeStatus


def _config(tmp_path: Path) -> RuntimeConfig:
    return load_runtime_config(project_path=tmp_path)


def test_runtime_state_defaults(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state = RuntimeState(config=config)
    assert state.config is config
    assert state.status is RuntimeStatus.STARTING
    assert state.shutdown_requested is False
    assert state.agents == {}


def test_agent_runtime_state_defaults() -> None:
    agent = AgentRuntimeState(agent_id="agent-1")
    assert agent.agent_id == "agent-1"
    assert agent.status is AgentStatus.STARTING
    assert agent.last_error is None


def test_runtime_state_registers_and_updates_agents(tmp_path: Path) -> None:
    state = RuntimeState(config=_config(tmp_path))
    agent = AgentRuntimeState(agent_id="agent-1")
    state.agents[agent.agent_id] = agent

    assert state.get_agent("agent-1") is agent
    assert state.get_agent("missing") is None
    state.set_agent_status("agent-1", AgentStatus.RUNNING)
    assert agent.status is AgentStatus.RUNNING


def test_set_agent_status_rejects_unknown_agent(tmp_path: Path) -> None:
    state = RuntimeState(config=_config(tmp_path))
    with pytest.raises(KeyError):
        state.set_agent_status("unknown", AgentStatus.RUNNING)
