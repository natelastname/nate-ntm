from __future__ import annotations

"""Macro integration tests for the external Swarm ACP transport."""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import acp
import pytest
import pytest_asyncio
from acp.connection import StreamDirection, StreamEvent

from nate_ntm.config.runtime_config import AdapterKind, RuntimeConfig, load_runtime_config
from nate_ntm.runtime.acp_client import AcpAgentSession, NateOhaAcpClient
from nate_ntm.runtime.acp_types import SessionNotification
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.nate_oha_launch import build_effective_nate_oha_config
from nate_ntm.runtime.swarm_acp_client import SwarmACPClient
from nate_ntm.runtime.swarm_acp_mux import SwarmACPMux
from nate_ntm.runtime.swarm_acp_server import (
    ConnectionExternalACPConnection,
    SwarmACPConnection,
    SwarmACPServerSession,
)
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


@dataclass
class RealSwarm:
    config: RuntimeConfig
    store: MetadataStore
    daemon: RuntimeDaemon
    acp_client: NateOhaAcpClient
    agent_a: str
    agent_b: str


@dataclass
class RecordingCallbacks:
    """Only the client-side behavior this transport suite needs to observe."""

    notifications: list[SessionNotification] = field(default_factory=list)

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        self.notifications.append(SessionNotification(session_id=session_id, update=update))


@dataclass
class ConnectedSwarm:
    swarm: RealSwarm
    server: asyncio.AbstractServer
    client: SwarmACPClient
    callbacks: RecordingCallbacks
    wire_events: list[tuple[str, Any]]
    mux: SwarmACPMux



def _make_real_echo_config(tmp_path: Path) -> RuntimeConfig:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]

    env = dict(os.environ)
    env.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
            "NATE_NTM_NATE_OHA_CONFIG": str(
                repo_root / "nate-oha-profiles" / "profile1.json"
            ),
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
        }
    )
    return load_runtime_config(project_path=project, env=env)


@pytest_asyncio.fixture
async def real_swarm(tmp_path: Path) -> AsyncIterator[RealSwarm]:
    config = _make_real_echo_config(tmp_path)
    store = MetadataStore(config=config)
    now = datetime.utcnow()
    nate_oha_config = build_effective_nate_oha_config(config=config)
    agent_a = "swarm-real-a"
    agent_b = "swarm-real-b"

    states = {
        agent_id: AgentState(
            agent_id=agent_id,
            display_name=display_name,
            conversation_id="",
            nate_oha_config=nate_oha_config,
        )
        for agent_id, display_name in (
            (agent_a, "Swarm Real Agent A"),
            (agent_b, "Swarm Real Agent B"),
        )
    }
    store.save_swarm_state(
        SwarmState(
            swarm_id=config.swarm_id,
            project_path=config.project_path,
            agent_mail_project_id=str(config.project_path),
            created_at=now,
            last_updated_at=now,
            agents=states,
        )
    )

    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.acp, NateOhaAcpClient)
    daemon = RuntimeDaemon.resume(config, adapters=adapters)
    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    await acp_client.start_agent_async(agent_a, metadata=store.load_agent_state(agent_a))
    await acp_client.start_agent_async(agent_b, metadata=store.load_agent_state(agent_b))
    daemon.start()

    try:
        yield RealSwarm(config, store, daemon, acp_client, agent_a, agent_b)
    finally:
        for agent_id in (agent_a, agent_b):
            try:
                await acp_client.stop_agent_async(agent_id, timeout=10.0)
            except Exception:
                pass
        daemon.request_shutdown()
        daemon.mark_stopped()


async def _start_swarm_acp_server_for_daemon(
    daemon: RuntimeDaemon,
) -> tuple[asyncio.AbstractServer, asyncio.Future[SwarmACPMux]]:
    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)
    mux_future: asyncio.Future[SwarmACPMux] = asyncio.get_running_loop().create_future()

    async def handle_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        external = ConnectionExternalACPConnection()
        session = SwarmACPServerSession(
            daemon=daemon,
            agent_client=acp_client,
            external_connection=external,
            external_session_id="external-1",
        )
        if not mux_future.done():
            mux_future.set_result(session.mux)

        connection = SwarmACPConnection(
            session=session,
            writer=writer,
            reader=reader,
            receive_timeout=5.0,
        )
        external.bind(connection)

        async def serve_inbound(current: SwarmACPServerSession) -> None:
            assert current is session
            await connection.main_loop()

        async def close_transport() -> None:
            try:
                await connection.close()
            finally:
                writer.close()
                await writer.wait_closed()

        await session.run_connection(serve_inbound, close_transport=close_transport)

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    return server, mux_future


@pytest_asyncio.fixture
async def connected_swarm(real_swarm: RealSwarm) -> AsyncIterator[ConnectedSwarm]:
    server, mux_future = await _start_swarm_acp_server_for_daemon(real_swarm.daemon)
    host, port = server.sockets[0].getsockname()[:2]
    callbacks = RecordingCallbacks()
    wire_events: list[tuple[str, Any]] = []

    def observe(event: StreamEvent) -> None:
        if event.direction is not StreamDirection.INCOMING:
            return
        message = event.message
        if "id" in message and "method" not in message:
            wire_events.append(("response", message.get("result")))
        elif "method" in message and "id" not in message:
            wire_events.append(
                ("notification", message["method"], message.get("params"))
            )

    client = await SwarmACPClient.connect(
        callbacks,
        host,
        port,
        session_id="external-1",
        receive_timeout=5.0,
        observers=[observe],
    )
    mux = await asyncio.wait_for(mux_future, timeout=5.0)
    connected = ConnectedSwarm(real_swarm, server, client, callbacks, wire_events, mux)

    try:
        yield connected
    finally:
        try:
            await client.close()
        finally:
            server.close()
            await server.wait_closed()
        assert mux._closed is True  # type: ignore[attr-defined]
        assert mux._attachment is None  # type: ignore[attr-defined]



def _notification_texts(callbacks: RecordingCallbacks, start: int = 0) -> list[str]:
    texts: list[str] = []
    for notification in callbacks.notifications[start:]:
        payload = notification.update.model_dump(mode="json", by_alias=True)
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return texts


async def _wait_for_text(
    callbacks: RecordingCallbacks,
    expected: str,
    *,
    start: int,
    timeout: float = 15.0,
) -> None:
    async with asyncio.timeout(timeout):
        while not any(expected in text for text in _notification_texts(callbacks, start)):
            await asyncio.sleep(0.05)



def _normalise_prompt(prompt: Any) -> str:
    if isinstance(prompt, list) and prompt:
        return str(getattr(prompt[0], "text", ""))
    return "" if prompt is None else str(prompt)


@pytest.mark.asyncio
async def test_attach_prompt_interrupt_detach(
    connected_swarm: ConnectedSwarm,
) -> None:
    swarm = connected_swarm.swarm
    client = connected_swarm.client
    callbacks = connected_swarm.callbacks
    mux = connected_swarm.mux

    status = await client.swarm_status()
    assert status.attached_agent_id is None
    assert status.swarm == swarm.daemon.get_swarm_status()

    detail = await client.agent_detail(swarm.agent_a, max_events=5)
    expected_detail = swarm.daemon.get_agent_detail(agent_id=swarm.agent_a, max_events=5)
    assert detail.attached is False
    assert detail.agent == expected_detail["agent"]
    assert detail.events == expected_detail["events"]

    prompt_calls: list[tuple[str, str]] = []
    interrupt_calls: list[str] = []
    original_prompt = swarm.acp_client.prompt
    original_interrupt = swarm.acp_client.interrupt

    async def prompt(agent_id: str, value: Any = None) -> str | None:
        text = _normalise_prompt(value)
        prompt_calls.append((agent_id, text))
        return await original_prompt(agent_id, text)

    async def interrupt(agent_id: str) -> None:
        interrupt_calls.append(agent_id)
        await original_interrupt(agent_id)

    swarm.acp_client.prompt = prompt  # type: ignore[assignment]
    swarm.acp_client.interrupt = interrupt  # type: ignore[assignment]
    try:
        attached = await client.attach(swarm.agent_a)
        assert attached.attached_agent_id == swarm.agent_a
        assert mux.attached_agent_id == swarm.agent_a

        text = "attach-prompt-detach: hello from external client"
        start = len(callbacks.notifications)
        response = await client.prompt_text(text)
        assert response.stop_reason == "end_turn"
        await _wait_for_text(callbacks, text, start=start)
        assert (swarm.agent_a, text) in prompt_calls

        await client.interrupt()
        async with asyncio.timeout(10.0):
            while not interrupt_calls:
                await asyncio.sleep(0.05)
        assert interrupt_calls[-1] == swarm.agent_a
    finally:
        swarm.acp_client.prompt = original_prompt  # type: ignore[assignment]
        swarm.acp_client.interrupt = original_interrupt  # type: ignore[assignment]

    assert (await client.detach()).detached is True
    assert (await client.detach()).detached is True
    assert mux.attached_agent_id is None

    session = swarm.acp_client._sessions.get(swarm.agent_a)  # type: ignore[attr-defined]
    assert isinstance(session, AcpAgentSession)
    baseline = len(callbacks.notifications)
    await swarm.acp_client.prompt(swarm.agent_a, "direct-after-detach")
    await asyncio.sleep(0.1)
    assert len(callbacks.notifications) == baseline
    assert session.status in {"starting", "running", "waiting"}


@pytest.mark.asyncio
async def test_switching_reroutes_and_preserves_attach_order(
    connected_swarm: ConnectedSwarm,
) -> None:
    swarm = connected_swarm.swarm
    client = connected_swarm.client
    callbacks = connected_swarm.callbacks
    prompt_calls: list[tuple[str, str]] = []
    interrupt_calls: list[str] = []
    original_prompt = swarm.acp_client.prompt
    original_interrupt = swarm.acp_client.interrupt

    async def prompt(agent_id: str, value: Any = None) -> str | None:
        text = _normalise_prompt(value)
        prompt_calls.append((agent_id, text))
        return await original_prompt(agent_id, text)

    async def interrupt(agent_id: str) -> None:
        interrupt_calls.append(agent_id)
        await original_interrupt(agent_id)

    swarm.acp_client.prompt = prompt  # type: ignore[assignment]
    swarm.acp_client.interrupt = interrupt  # type: ignore[assignment]
    try:
        await client.attach(swarm.agent_a)
        text_a = "switching: hello from agent A"
        start = len(callbacks.notifications)
        await client.prompt_text(text_a)
        await _wait_for_text(callbacks, text_a, start=start)

        attach_index = next(
            index
            for index, event in enumerate(connected_swarm.wire_events)
            if event[0] == "response"
            and isinstance(event[1], dict)
            and event[1].get("attached_agent_id") == swarm.agent_a
        )
        update_index = next(
            index
            for index, event in enumerate(connected_swarm.wire_events)
            if event[0] == "notification"
            and event[1] == acp.CLIENT_METHODS["session_update"]
        )
        assert update_index > attach_index

        await client.attach(swarm.agent_b)
        text_b = "switching: hello from agent B"
        start = len(callbacks.notifications)
        await client.prompt_text(text_b)
        await _wait_for_text(callbacks, text_b, start=start)
        assert prompt_calls[-2:] == [(swarm.agent_a, text_a), (swarm.agent_b, text_b)]

        await client.interrupt()
        async with asyncio.timeout(10.0):
            while not interrupt_calls:
                await asyncio.sleep(0.05)
        assert interrupt_calls[-1] == swarm.agent_b
    finally:
        swarm.acp_client.prompt = original_prompt  # type: ignore[assignment]
        swarm.acp_client.interrupt = original_interrupt  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_unknown_agent_error_mapping(connected_swarm: ConnectedSwarm) -> None:
    with pytest.raises(acp.RequestError) as exc_info:
        await connected_swarm.client.attach("missing-agent")

    assert isinstance(exc_info.value.data, dict)
    assert exc_info.value.data.get("mux_code") == "MUX_UNKNOWN_AGENT"
