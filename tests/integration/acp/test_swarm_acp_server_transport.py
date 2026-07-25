"""Macro test for the complete production ACP transport path."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, TypeVar
from uuid import uuid4

import acp
import json5
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

_OPERATION_TIMEOUT = 60.0
_CLEANUP_TIMEOUT = 5.0
T = TypeVar("T")


async def _bounded(awaitable: Awaitable[T], *, timeout: float = _OPERATION_TIMEOUT) -> T:
    return await asyncio.wait_for(awaitable, timeout=timeout)


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

        connection = SwarmACPConnection(session=session, writer=writer, reader=reader)
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
    base = NateOHAConfig.model_validate(json5.loads(profile.read_text(encoding="utf-8")))
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
    store = MetadataStore(swarm_id)
    store.save_swarm_state(swarm)
    config = load_runtime_config(
        project_path=project,
        swarm_id=swarm_id,
        nate_oha_runtime_mode="echo",
        env={},
    )
    return config, swarm, store


def _require_nate_oha(config: RuntimeConfig) -> None:
    if shutil.which(config.nate_oha_executable) is None:
        pytest.skip(f"{config.nate_oha_executable!r} is not installed")


def _notification_texts(callbacks: _Callbacks, start: int) -> list[str]:
    texts: list[str] = []
    for notification in callbacks.notifications[start:]:
        payload = notification.update.model_dump(mode="json", by_alias=True)
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            texts.append(content["text"])
    return texts


async def _wait_for_text(callbacks: _Callbacks, expected: str, start: int) -> None:
    async with asyncio.timeout(_OPERATION_TIMEOUT):
        while not any(expected in text for text in _notification_texts(callbacks, start)):
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_real_runtime_create_swarm_acp_and_resume(tmp_path: Path) -> None:
    config, swarm, store = _materialize_swarm(tmp_path)
    _require_nate_oha(config)

    internal: NateOhaAcpClient | None = None
    external: SwarmACPClient | None = None
    server: asyncio.AbstractServer | None = None
    daemon: RuntimeDaemon | None = None

    try:
        adapters = create_runtime_adapters(config, swarm)
        daemon = RuntimeDaemon.resume(config, swarm, adapters=adapters)
        internal = daemon.acp_client
        assert isinstance(internal, NateOhaAcpClient)

        for agent_id, metadata in daemon.swarm_state.agents.items():
            await _bounded(internal.start_agent(agent_id, metadata=metadata))
        daemon.start()

        server, mux_future = await _bounded(_start_swarm_server(daemon, internal))
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

        external = await _bounded(
            SwarmACPClient.connect(
                callbacks,
                host,
                port,
                session_id="external-1",
                observers=[observe],
            )
        )
        mux = await _bounded(mux_future, timeout=5)

        assert len((await _bounded(external.swarm_status())).swarm["agents"]) == 2
        detail = await _bounded(external.agent_detail("agent-1"))
        assert detail.agent["agent_id"] == "agent-1"

        await _bounded(external.attach("agent-1"))
        first = "end-to-end prompt for agent one"
        start = len(callbacks.notifications)
        assert (await _bounded(external.prompt_text(first))).stop_reason == "end_turn"
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

        await _bounded(external.interrupt())
        await _bounded(external.attach("agent-2"))
        second = "end-to-end prompt for agent two"
        start = len(callbacks.notifications)
        await _bounded(external.prompt_text(second))
        await _wait_for_text(callbacks, second, start)
        assert mux.attached_agent_id == "agent-2"
        assert (await _bounded(external.detach())).detached is True

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
        if external is not None:
            try:
                await _bounded(external.close(), timeout=_CLEANUP_TIMEOUT)
            except Exception:
                pass
        if server is not None:
            server.close()
            try:
                await _bounded(server.wait_closed(), timeout=_CLEANUP_TIMEOUT)
            except Exception:
                pass
        if internal is not None and daemon is not None:
            for agent_id in daemon.swarm_state.agents:
                try:
                    await _bounded(internal.stop_agent(agent_id), timeout=_CLEANUP_TIMEOUT)
                except Exception:
                    pass
        if daemon is not None:
            daemon.request_shutdown()
            daemon.mark_stopped()
        shutil.rmtree(store.metadata_dir, ignore_errors=True)
