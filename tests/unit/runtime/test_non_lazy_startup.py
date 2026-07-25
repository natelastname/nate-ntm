from types import SimpleNamespace

import pytest

from nate_ntm.runtime.runner import _start_all_agents
from nate_ntm.runtime.state import AgentStatus


class _AgentClient:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def start_agent(self, agent_id: str, *, metadata: object) -> None:
        self.started.append(agent_id)
        if agent_id == "broken":
            raise RuntimeError("cannot start")


class _Daemon:
    def __init__(self) -> None:
        self.acp_client = _AgentClient()
        self.swarm_state = SimpleNamespace(
            agents={"working": object(), "broken": object()}
        )
        self.state = SimpleNamespace(
            agents={
                agent_id: SimpleNamespace(status=AgentStatus.IDLE, last_error=None)
                for agent_id in self.swarm_state.agents
            }
        )

    def mark_agent_failed(self, agent_id: str, error: str | None = None) -> None:
        agent = self.state.agents[agent_id]
        agent.status = AgentStatus.FAILED
        agent.last_error = error


@pytest.mark.asyncio
async def test_non_lazy_start_attempts_every_agent_and_isolates_failures() -> None:
    daemon = _Daemon()

    await _start_all_agents(SimpleNamespace(daemon=daemon))  # type: ignore[arg-type]

    assert set(daemon.acp_client.started) == {"working", "broken"}
    assert daemon.state.agents["working"].status is AgentStatus.RUNNING
    assert daemon.state.agents["broken"].status is AgentStatus.FAILED
    assert daemon.state.agents["broken"].last_error == "cannot start"
