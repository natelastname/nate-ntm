"""Macro test for the complete production ACP transport path.

The test uses the real nate-oha and Agent Mail adapters. It skips when either
external service is unavailable, but otherwise exercises one materialized swarm
through ACP attach, prompt, interrupt, detach, persistence, and resume.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import acp
import pytest
from acp.connection import StreamDirection, StreamEvent
from nate_oha.config import NateOHAConfig

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.acp_types import SessionNotification
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_acp_client import SwarmACPClient
from nate_ntm.runtime.swarm_acp_mux import SwarmACPMux
from nate_ntm.runtime.swarm_acp_server import (
    ConnectionExternalACPConnection,
    SwarmACPConnection,
    SwarmACPServerSession,
)
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_ntm.swarm_constructors import ConstructionContext, agent_mail_constructor

_AGENT_MAIL_URL = "http://127.0.0.1:8765/api"


@dataclass
class _Callbacks:
    notifications: list[SessionNotification] = field(default_factory=list)

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        self.notifications.append(SessionNotification(session_id=session_id, update=update))


async def _start_swarm_server(
    daemon: RuntimeDaemon,
    client: NateOhaAcpClient,
) -> tuple[asyncio.AbstractServer, asyncio.Future[SwarmACPMux]]:
    mux_future: asyncio.Future[SwarmACPMux] = asyncio.get_running_loop().create_future()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        external = ConnectionExternalACPConnection()
        session = SwarmACPServerSession(
            daemon=daemon,
            agent_client=client,
            external_connection=external,
            external_session_id="external-1",
        )
        if not mux_future.done():
            mux_future.set_result(session.mux)

        connection = SwarmACPConnection(
            session=session,
            writer=writer,
            reader=reader,
            receive_timeout=10.0,
        )
        external.bind(connection)

        async def serve(_: SwarmACPServerSession) -> None:
            await connection.main_loop()

        async def close() -> None:
            await connection.close()
            writer.close()
            await writer.wait_closed()

        await session.run_connection(serve, close_transport=close)

    return await asyncio.start_server(handle, "127.0.0.1", 0), mux_future


def _materialize_swarm(tmp_path: Path) -> tuple[RuntimeConfig, SwarmState, MetadataStore]:
    project = tmp_path / "project"
    project.mkdir()
    profile = Path(__file__).resolve().parents[3] / "nate-oha-profiles" / "profile1.json"
    base = NateOHAConfig.model_validate_json(profile.read_text(encoding="utf-8"))
    swarm_id = uuid4().hex
    now = datetime.now(timezone.utc)
    swarm = SwarmState(
        swarm_id=swarm_id,
        project_path=project,
        created_at=now,
        last_updated_at=now,
        agents={
            agent_id: AgentState(
                agent_id=agent_id,
                display_name=agent_id.replace("-", " ").title(),
                nate_oha_config=base.model_copy(deep=True),
            )
            for agent_id in ("agent-1", "agent-2")
        },
    )
    swarm = agent_mail_constructor(
        swarm,
        ConstructionContext(agent_mail_url=_AGENT_MAIL_URL),
    )
    store = MetadataStore(swarm_id)
    store.save_swarm_state(swarm)
    config = load_runtime_config(
        project_path=project,
        swarm_id=swarm_id,
        nate_oha_runtime_mode="echo",
        env={},
    )
    return config, swarm, store


def _require_external_services(config: RuntimeConfig) -> None:
    if shutil.which(config.nate_oha_executable) is None:
        pytest.skip(f"{config.nate_oha_executable!r} is not installed")
    parsed = urlparse(_AGENT_MAIL_URL)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=1):
            pass
    except OSError:
        pytest.skip(f"mcp_agent_mail is not reachable at {parsed.hostname}:{parsed.port}")


def _notification_texts(callbacks: _Callbacks, start: int) -> list[str]:
    texts: list[str] = []
    for notification in callbacks.notifications[start:]:
        payload = notification.update.model_dump(mode="json", by_alias=True)
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            texts.append(content["text"])
    return texts


async def _wait_for_text(callbacks: _Callbacks, expected: str, start: int) -> None:
    async with asyncio.timeout(20):
        while not any(expected in text for text in _notification_texts(callbacks, start)):
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_real_runtime_create_swarm_acp_and_resume(tmp_path: Path) -> None:
    config, swarm, store = _materialize_swarm(tmp_path)
    _require_external_services(config)

    try:
        adapters = create_runtime_adapters(config, swarm)
        daemon = RuntimeDaemon.resume(config, swarm, adapters=adapters)
        internal = daemon.acp_client
        assert isinstance(internal, NateOhaAcpClient)

        for agent_id, metadata in daemon.swarm_state.agents.items():
            await internal.start_agent(agent_id, metadata=metadata)
        daemon.start()

        server, mux_future = await _start_swarm_server(daemon, internal)
        host, port = server.sockets[0].getsockname()[:2]
        callbacks = _Callbacks()
        wire: list[tuple[str, Any]] = []

        def observe(event: StreamEvent) -> None:
            if event.direction is not StreamDirection.INCOMING:
                return
            message = event.message
            if "id" in message and "method" not in message:
                wire.append(("response", message.get("result")))
            elif "method" in message and "id" not in message:
                wire.append(("notification", message["method"]))

        external = await SwarmACPClient.connect(
            callbacks,
            host,
            port,
            session_id="external-1",
            receive_timeout=10,
            observers=[observe],
        )
        mux = await asyncio.wait_for(mux_future, timeout=5)

        try:
            assert len((await external.swarm_status()).swarm["agents"]) == 2
            detail = await external.agent_detail("agent-1")
            assert detail.agent["agent_mail_identity"]

            await external.attach("agent-1")
            first = "end-to-end prompt for agent one"
            start = len(callbacks.notifications)
            assert (await external.prompt_text(first)).stop_reason == "end_turn"
            await _wait_for_text(callbacks, first, start)

            attach_response = next(
                i
                for i, item in enumerate(wire)
                if item[0] == "response"
                and isinstance(item[1], dict)
                and item[1].get("attached_agent_id") == "agent-1"
            )
            first_update = next(
                i
                for i, item in enumerate(wire)
                if item == ("notification", acp.CLIENT_METHODS["session_update"])
            )
            assert first_update > attach_response

            await external.interrupt()
            await external.attach("agent-2")
            second = "end-to-end prompt for agent two"
            start = len(callbacks.notifications)
            await external.prompt_text(second)
            await _wait_for_text(callbacks, second, start)
            assert mux.attached_agent_id == "agent-2"
            assert (await external.detach()).detached is True
        finally:
            await external.close()
            server.close()
            await server.wait_closed()
            for agent_id in daemon.swarm_state.agents:
                await internal.stop_agent(agent_id)
            daemon.request_shutdown()
            daemon.mark_stopped()

        persisted = {
            agent_id: store.load_agent_state(agent_id).conversation_id
            for agent_id in daemon.swarm_state.agents
        }
        assert all(persisted.values())

        resumed_state = store.load_swarm_state()
        resumed = RuntimeDaemon.resume(
            config,
            resumed_state,
            adapters=create_runtime_adapters(config, resumed_state),
        )
        assert set(resumed.swarm_state.agents) == set(persisted)
        for agent_id, conversation_id in persisted.items():
            assert resumed.get_agent_detail(agent_id)["conversation_id"] == conversation_id
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)
