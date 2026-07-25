from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import json5
from nate_oha.config import build_default_config
from typer.testing import CliRunner

from nate_ntm.api.server import RuntimeApiServer
from nate_ntm.cli import app
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.acp_client import AcpAgentStatus, BaseAcpClient
from nate_ntm.runtime.acp_update_stream import ReceivedSessionUpdate
from nate_ntm.runtime.adapters import RuntimeAdapters
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.state import RuntimeStatus
from nate_ntm.runtime.swarm_state import AgentState

runner = CliRunner()


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
        async def empty() -> AsyncIterator[ReceivedSessionUpdate]:
            if False:
                yield  # pragma: no cover

        yield empty()


def test_resume_reuses_materialized_project_and_agent_configuration(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    agent_path = tmp_path / "shared.json"
    agent_path.write_text(
        json5.dumps(build_default_config().model_dump(mode="json")),
        encoding="utf-8",
    )
    swarm_id = uuid4().hex
    store = MetadataStore(swarm_id)

    try:
        result = runner.invoke(
            app,
            [
                "swarm",
                "create",
                "--project",
                str(project),
                "--swarm-id",
                swarm_id,
                "--agent",
                f"planner:{agent_path}",
                "--constructor",
                "agent-mail",
                "--agent-mail-url",
                "https://agent-mail.invalid",
            ],
        )
        assert result.exit_code == 0, result.output

        persisted = store.load_swarm_state()
        persisted.agents["planner"].conversation_id = "conversation-1"
        store.save_swarm_state(persisted)
        expected_config = persisted.agents["planner"].nate_oha_config.model_copy(deep=True)

        config = load_runtime_config(
            project_path=persisted.project_path,
            swarm_id=persisted.swarm_id,
            env={},
        )
        daemon = RuntimeDaemon.resume(
            config,
            persisted,
            adapters=RuntimeAdapters(agent_mail=None, acp=StubAcpClient()),
        )
        daemon.start()

        assert daemon.state.status is RuntimeStatus.RUNNING
        assert daemon.swarm_state.project_path == project.resolve()
        assert daemon.swarm_state.agents["planner"].conversation_id == "conversation-1"
        assert daemon.swarm_state.agents["planner"].nate_oha_config == expected_config

        server = RuntimeApiServer(daemon=daemon)
        status = server.get_runtime_status()
        assert status["swarm_id"] == swarm_id
        assert status["project_path"] == str(project.resolve())
        assert status["agent_counts"]["total"] == 1
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)
