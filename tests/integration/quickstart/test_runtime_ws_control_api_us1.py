"""Integration coverage for the resume-only runtime control API."""

from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

from nate_oha.config import build_default_config

from nate_ntm.api.client import JsonRpcHttpClient
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.acp_client import AcpAgentStatus, BaseAcpClient
from nate_ntm.runtime.acp_update_stream import ReceivedSessionUpdate
from nate_ntm.runtime.adapters import RuntimeAdapters
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.runner import create_runtime_control_context, serve_runtime_control_api
from nate_ntm.runtime.state import AgentStatus, RuntimeStatus
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


class StubAcpClient(BaseAcpClient):
    async def start_agent(self, agent_id: str, *, metadata: AgentState) -> None:
        pass

    async def stop_agent(self, agent_id: str) -> None:
        pass

    async def prompt(self, agent_id: str, prompt: str | None = None) -> str | None:
        return None

    async def interrupt(self, agent_id: str) -> None:
        pass

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        return AcpAgentStatus(agent_id=agent_id, state="idle")

    @asynccontextmanager
    async def subscribe_acp_updates(
        self, agent_id: str
    ) -> AsyncIterator[AsyncIterator[ReceivedSessionUpdate]]:
        async def updates() -> AsyncIterator[ReceivedSessionUpdate]:
            if False:
                yield  # pragma: no cover

        yield updates()


def test_runtime_control_api_status_and_shutdown(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = MetadataStore(uuid4().hex)
    now = datetime.now(timezone.utc)
    swarm = SwarmState(
        swarm_id=store.swarm_id,
        project_path=project,
        created_at=now,
        last_updated_at=now,
        agents={
            "nav-1": AgentState(
                agent_id="nav-1",
                display_name="Navigator 1",
                nate_oha_config=build_default_config(),
            )
        },
    )
    store.save_swarm_state(swarm)

    async def main() -> None:
        config = load_runtime_config(
            project_path=swarm.project_path,
            swarm_id=swarm.swarm_id,
            env={},
        )
        context = create_runtime_control_context(
            config,
            swarm,
            host="127.0.0.1",
            port=0,
            adapters=RuntimeAdapters(agent_mail=None, acp=StubAcpClient()),
        )
        serve_task = asyncio.create_task(serve_runtime_control_api(context))

        for _ in range(50):
            if context.bound_port:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("Control API server did not bind to a port")

        client = JsonRpcHttpClient(
            host="127.0.0.1",
            port=context.bound_port,
            timeout=5.0,
        )
        status = await client.call_for_result("runtime.get_status", {})
        assert status == {
            "status": RuntimeStatus.RUNNING.value,
            "project_path": str(project.resolve()),
            "swarm_id": store.swarm_id,
            "agent_counts": {
                "total": 1,
                "starting": 0,
                "idle": 1,
                "running": 0,
                "waiting": 0,
                "failed": 0,
            },
        }

        shutdown = await client.call_for_result(
            "runtime.shutdown", {"timeout_seconds": 5}
        )
        assert shutdown["accepted"] is True
        assert shutdown["status"] == RuntimeStatus.SHUTTING_DOWN.value

        await asyncio.wait_for(serve_task, timeout=5.0)
        assert context.daemon.state.status is RuntimeStatus.STOPPED
        assert context.daemon.state.agents["nav-1"].status is AgentStatus.IDLE

    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)
