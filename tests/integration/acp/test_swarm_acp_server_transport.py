from __future__ import annotations

"""Integration tests: Swarm ACP server over a real ACP transport (US3 Addendum).

These tests exercise the concrete JSON-RPC adapter path that binds
:class:`SwarmACPServerSession` and :class:`SwarmACPMux` to an ACP
:class:`acp.connection.Connection` using the production
:class:`ConnectionExternalACPConnection` and :class:`SwarmACPConnection`
helpers.

The goal, per T027.2 in ``specs/009-swarm-acp-mux/tasks.md``, is to
validate at the wire level that:

* reserved requests such as ``_swarm_status``, ``_agent_detail``,
  ``_attach``, and ``_detach`` are decoded and encoded correctly; 
* the ``_attach`` success response is observed *before* any retained or
  live agent updates reach the external client; 
* ordinary ``session/prompt`` and ``session/cancel`` operations reach
  only the currently attached agent; 
* switching and detaching change routing as specified by the mux
  contract; 
* mux/domain failures are surfaced to the client as ACP
  :class:`RequestError` instances carrying the expected logical
  ``MUX_*`` codes in ``error.data``; and 
* connection shutdown leaves no forwarding tasks or Epic 008
  subscriptions active for the external session.

These tests deliberately reuse the real Epic 008 typed update path:

``AcpAgentSession.update_stream``
    → :meth:`NateOhaAcpClient.subscribe_acp_updates`
    → :class:`SwarmACPMux`
    → :class:`ConnectionExternalACPConnection`
    → :class:`SwarmACPConnection` / :class:`acp.connection.Connection`.

No alternative telemetry paths are introduced; all agent output flows
through the typed update layer defined in Epic 008.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import acp
import pytest
from acp import schema as acp_schema
from acp.agent.router import AGENT_METHODS
from acp.connection import Connection, StreamDirection, StreamEvent

from nate_ntm.config.runtime_config import (
    AdapterKind,
    RuntimeConfig,
    load_runtime_config,
)
from nate_ntm.runtime.acp_client import AcpAgentSession, NateOhaAcpClient
from nate_ntm.runtime.acp_types import SessionNotification
from nate_ntm.runtime.acp_update_stream import (
    AcpSessionUpdateStream,
    ReceivedSessionUpdate,
)
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.nate_oha_launch import build_effective_nate_oha_config
from nate_ntm.runtime.swarm_acp_mux import SwarmACPMux
from nate_ntm.runtime.swarm_acp_server import (
    ConnectionExternalACPConnection,
    SwarmACPConnection,
    SwarmACPServerSession,
)
from nate_ntm.runtime.swarm_state import AgentState, SwarmState

# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


@dataclass
class _FakeSwarmState:
    agents: dict[str, object]


class _FakeDaemon:
    """Minimal daemon stub exposing durable swarm membership and views.

    SwarmACPMux validates durable membership via ``daemon.swarm_state``
    and, for reserved-control operations, reuses ``get_swarm_status``
    and ``get_agent_detail`` to implement mux-level views without
    depending on the real :class:`RuntimeDaemon` implementation.
    """

    def __init__(
        self,
        agent_ids: Iterable[str] = (),
        *,
        swarm_status: dict[str, object] | None = None,
        agent_details: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.swarm_state = _FakeSwarmState(agents={aid: object() for aid in agent_ids})
        self._swarm_status = dict(swarm_status or {})
        self._agent_details = {k: dict(v) for k, v in (agent_details or {}).items()}
        self.max_events_calls: list[tuple[str, int]] = []

    def get_swarm_status(self) -> dict[str, object]:
        return dict(self._swarm_status)

    def get_agent_detail(self, *, agent_id: str, max_events: int) -> dict[str, object]:
        self.max_events_calls.append((agent_id, max_events))
        detail = self._agent_details[agent_id]
        events = list(detail.get("events", []))
        return {
            "agent": detail["agent"],
            "events": events[:max_events],
        }


def _make_config(tmp_path: Path) -> RuntimeConfig:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return load_runtime_config(project_path=project)


def _publish_info(stream: AcpSessionUpdateStream, title: str) -> acp_schema.SessionInfoUpdate:
    """Publish a concrete ``SessionInfoUpdate`` on the Epic 008 stream.

    Using a real ACP SDK update model ensures that
    :class:`SessionNotification` can be constructed without violating its
    discriminated-union constraints.
    """

    update = acp_schema.SessionInfoUpdate(title=title, session_update="session_info_update")
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    stream.publish(update, received_at=t0)
    return update


async def _anext_with_timeout(
    it: AsyncIterator[ReceivedSessionUpdate], timeout: float = 1.0
) -> ReceivedSessionUpdate:
    return await asyncio.wait_for(it.__anext__(), timeout=timeout)


class _RecordingClient:
    """Thin wrapper around :class:`acp.connection.Connection` for tests.

    The client records all `session/update` notifications and a coarse
    event log so that tests can assert on wire-level ordering between the
    `_attach` success response and subsequent forwarded updates.

    It also owns the underlying TCP transport so that tests can shut down
    cleanly without leaking :class:`asyncio.StreamWriter` instances when
    the event loop closes.
    """

    def __init__(
        self,
        conn: Connection,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._conn = conn
        self._writer = writer
        # High-level, decoded notifications and coarse-grained client events.
        self.notifications: list[SessionNotification] = []
        self.events: list[tuple[str, Any]] = []
        # Low-level stream events observed directly at the JSON-RPC layer.
        # Each entry is either:
        #
        #   ("response", result_obj)
        #   ("notification", method, params)
        #
        # captured in the exact order the Connection processes incoming
        # messages. Tests use this to assert wire-level ordering between the
        # `_attach` response and subsequent `session/update` notifications.
        self.stream_events: list[tuple[str, Any]] = []

    @classmethod
    async def connect(cls, host: str, port: int) -> "_RecordingClient":
        reader, writer = await asyncio.open_connection(host, port)

        async def handler(method: str, params: Any | None, is_notification: bool) -> Any:
            if is_notification and method == acp.CLIENT_METHODS["session_update"]:
                notif = SessionNotification.model_validate(params or {})
                self_ref.notifications.append(notif)
                self_ref.events.append(("update", notif))
                return None

            # No server-initiated requests or other notifications are
            # expected in these tests.
            if not is_notification:
                raise acp.RequestError.method_not_found(method)

            return None

        # Use a small receive timeout to ensure tests fail promptly if the
        # server stops responding.
        self_ref: "_RecordingClient"

        def observer(event: StreamEvent) -> None:
            # Capture the exact order of incoming responses and notifications
            # as they cross the JSON-RPC boundary. This is used to assert
            # that the `_attach` success response is observed before any
            # forwarded `session/update` notifications.
            if event.direction is not StreamDirection.INCOMING:
                return
            message = event.message
            if "id" in message and "method" not in message:
                # Ordinary JSON-RPC response.
                self_ref.stream_events.append(("response", message.get("result")))
            elif "method" in message and "id" not in message:
                # Server-initiated notification.
                self_ref.stream_events.append(("notification", message["method"], message.get("params")))

        conn = Connection(
            handler=handler,
            writer=writer,
            reader=reader,
            receive_timeout=5.0,
            observers=[observer],
        )
        self_ref = cls(conn, writer)
        return self_ref

    # ----- High-level ACP operations ---------------------------------

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        result = await self._conn.send_request(method, params or {})
        # Record only the reserved control responses we care about.
        if method.startswith("_"):
            self.events.append(("reserved_result", method, result))
        elif method in (AGENT_METHODS["session_prompt"], AGENT_METHODS["session_cancel"]):
            self.events.append(("agent_result", method, result))
        return result

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._conn.send_notification(method, params or {})

    async def attach(self, agent_id: str) -> dict[str, Any]:
        result = await self.request("_attach", {"agent_id": agent_id})
        self.events.append(("attach_result", result))
        return result

    async def detach(self) -> dict[str, Any]:
        return await self.request("_detach", {})

    async def swarm_status(self) -> dict[str, Any]:
        return await self.request("_swarm_status", {})

    async def agent_detail(self, agent_id: str, max_events: int) -> dict[str, Any]:
        return await self.request("_agent_detail", {"agent_id": agent_id, "max_events": max_events})

    async def prompt(self, text: str) -> dict[str, Any]:
        """Send a minimal but valid ACP PromptRequest for this test session."""

        method = AGENT_METHODS["session_prompt"]
        request = acp_schema.PromptRequest(
            session_id="session-1",
            prompt=[acp_schema.TextContentBlock(type="text", text=text)],
        )
        params = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        return await self.request(method, params)

    async def interrupt(self) -> None:
        """Send a minimal but valid ACP CancelNotification for this test session."""

        method = AGENT_METHODS["session_cancel"]
        cancel = acp_schema.CancelNotification(session_id="session-1")
        params = cancel.model_dump(mode="json", by_alias=True, exclude_none=True)
        await self.notify(method, params)

    async def close(self) -> None:
        await self._conn.close()
        # Ensure the underlying TCP transport is closed so that the
        # event loop does not report unclosed StreamWriter instances
        # when pytest tears it down.
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            # During error-path tests the loop may already be shutting
            # down; failures here must not mask the real assertions.
            pass


# ---------------------------------------------------------------------------
# Helper to start a one-shot Swarm ACP server over TCP
# ---------------------------------------------------------------------------


async def _start_swarm_acp_server(
    *,
    agent_id: str,
    daemon: _FakeDaemon,
    acp_client: NateOhaAcpClient,
    extra_agent_ids: Iterable[str] = (),
) -> tuple[asyncio.AbstractServer, AcpSessionUpdateStream, "asyncio.Future[SwarmACPMux]"]:
    """Start a single-connection Swarm ACP server backed by real Epic 008 plumbing.

    The returned server listens on an ephemeral port and accepts exactly
    one connection in these tests. A future for the underlying
    :class:`SwarmACPMux` instance is returned so that callers can inspect
    its state after the connection has terminated.

    When ``extra_agent_ids`` are supplied, additional synthetic
    :class:`AcpAgentSession` instances are created for those agents so
    that tests can exercise mux behaviour when switching attachments
    between multiple agents.
    """

    # Create a synthetic live AcpAgentSession with a real
    # AcpSessionUpdateStream, mirroring the setup in the Epic 008 tests.
    session = AcpAgentSession(
        agent_id=agent_id,
        conversation_id="conv-1",
        process=object(),
        connection=object(),
        protocol_client=object(),
        status="running",
        stderr_task=None,
        exit_monitor_task=None,
    )
    acp_client._sessions[agent_id] = session  # type: ignore[attr-defined]
    stream = session.update_stream

    # Optionally seed additional sessions so that SwarmACPMux can attach to
    # multiple agents in a single test scenario.
    for extra_id in extra_agent_ids:
        extra_session = AcpAgentSession(
            agent_id=extra_id,
            conversation_id=f"conv-{extra_id}",
            process=object(),
            connection=object(),
            protocol_client=object(),
            status="running",
            stderr_task=None,
            exit_monitor_task=None,
        )
        acp_client._sessions[extra_id] = extra_session  # type: ignore[attr-defined]

    loop = asyncio.get_running_loop()
    mux_future: asyncio.Future[SwarmACPMux] = loop.create_future()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        external = ConnectionExternalACPConnection()
        server_session = SwarmACPServerSession(
            daemon=daemon,  # type: ignore[arg-type]
            agent_client=acp_client,  # type: ignore[arg-type]
            external_connection=external,  # type: ignore[arg-type]
            external_session_id="external-1",
        )
        if not mux_future.done():
            mux_future.set_result(server_session.mux)

        conn = SwarmACPConnection(
            session=server_session,
            writer=writer,
            reader=reader,
            receive_timeout=5.0,
        )
        external.bind(conn)

        async def serve_inbound(sess: SwarmACPServerSession) -> None:
            assert sess is server_session
            await conn.main_loop()

        async def close_transport() -> None:
            try:
                await conn.close()
            finally:
                writer.close()
                await writer.wait_closed()

        await server_session.run_connection(serve_inbound, close_transport=close_transport)

    server = await asyncio.start_server(handle_client, host="127.0.0.1", port=0)
    return server, stream, mux_future


async def _start_swarm_acp_server_for_daemon(
    *,
    daemon: RuntimeDaemon,
) -> tuple[asyncio.AbstractServer, "asyncio.Future[SwarmACPMux]"]:
    """Start a single-connection Swarm ACP server bound to a real daemon.

    This helper mirrors :func:`_start_swarm_acp_server` but reuses the
    production :class:`RuntimeDaemon` and its REAL
    :class:`NateOhaAcpClient`/ACP wiring instead of constructing synthetic
    :class:`AcpAgentSession` instances. It is used by the end-to-end
    macro test that launches real nate-oha processes for two agents and
    exercises attachment + switching over a concrete ACP transport.
    """

    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    loop = asyncio.get_running_loop()
    mux_future: asyncio.Future[SwarmACPMux] = loop.create_future()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        external = ConnectionExternalACPConnection()
        server_session = SwarmACPServerSession(
            daemon=daemon,  # type: ignore[arg-type]
            agent_client=acp_client,  # type: ignore[arg-type]
            external_connection=external,  # type: ignore[arg-type]
            external_session_id="external-1",
        )
        if not mux_future.done():
            mux_future.set_result(server_session.mux)

        conn = SwarmACPConnection(
            session=server_session,
            writer=writer,
            reader=reader,
            receive_timeout=5.0,
        )
        external.bind(conn)

        async def serve_inbound(sess: SwarmACPServerSession) -> None:
            assert sess is server_session
            await conn.main_loop()

        async def close_transport() -> None:
            try:
                await conn.close()
            finally:
                writer.close()
                await writer.wait_closed()

        await server_session.run_connection(serve_inbound, close_transport=close_transport)

    server = await asyncio.start_server(handle_client, host="127.0.0.1", port=0)
    return server, mux_future


# ---------------------------------------------------------------------------
# T027.2 [US3] Macro-level adapter behaviour over real ACP transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swarm_acp_server_transport_attach_prompt_and_detach(tmp_path: Path) -> None:
    """Happy-path attach, prompt, and detach over a real ACP transport.

    This scenario verifies that:

    * reserved requests are decoded and encoded correctly at the wire
      level;
    * the `_attach` success response is observed before any
      `session/update` notifications;
    * prompt and interrupt target only the attached agent; and
    * detaching stops forwarding while leaving the Epic 008 stream and
      agent session intact.
    """

    config = _make_config(tmp_path)
    acp_client = NateOhaAcpClient(config=config)

    agent_id = "agent-1"
    swarm_status = {"status": "ok"}
    agent_detail = {"agent": {"agent_id": agent_id}, "events": ["e1", "e2", "e3"]}

    daemon = _FakeDaemon(
        agent_ids=[agent_id],
        swarm_status=swarm_status,
        agent_details={agent_id: agent_detail},
    )

    server, stream, mux_future = await _start_swarm_acp_server(
        agent_id=agent_id,
        daemon=daemon,
        acp_client=acp_client,
    )

    host, port = server.sockets[0].getsockname()[:2]

    try:
        client = await _RecordingClient.connect(host, port)
        mux = await asyncio.wait_for(mux_future, timeout=1.0)

        # Patch prompt/interrupt on the real NateOhaAcpClient so we can
        # assert routing without performing any external I/O.
        prompt_calls: list[tuple[str, str | None]] = []
        interrupt_calls: list[str] = []

        async def fake_prompt(agent: str, prompt: object | None = None) -> str | None:
            # The real NateOhaAcpClient passes through the PromptRequest
            # ``prompt`` blocks; we only care about the first text block's
            # payload for routing assertions.
            prompt_calls.append((agent, prompt))
            text_value: str | None = None
            if isinstance(prompt, list) and prompt:
                first = prompt[0]
                text_value = getattr(first, "text", None)
            return f"reply:{agent}:{text_value}"

        async def fake_interrupt(agent: str) -> None:
            interrupt_calls.append(agent)

        acp_client.prompt = fake_prompt  # type: ignore[assignment]
        acp_client.interrupt = fake_interrupt  # type: ignore[assignment]

        # ------------------------------------------------------------------
        # Reserved controls before attachment
        # ------------------------------------------------------------------

        status = await client.swarm_status()
        assert status == {"attached_agent_id": None, "swarm": swarm_status}

        detail = await client.agent_detail(agent_id=agent_id, max_events=2)
        assert detail["attached"] is False
        assert detail["agent"] == agent_detail["agent"]
        assert detail["events"] == agent_detail["events"][:2]
        assert daemon.max_events_calls == [(agent_id, 2)]

        # ------------------------------------------------------------------
        # Attach: ack-before-forwarding at the wire level
        # ------------------------------------------------------------------

        # Retained updates published before attachment.
        pre1 = _publish_info(stream, "pre1")
        pre2 = _publish_info(stream, "pre2")

        # Attach from the external ACP client's perspective.
        attach_result = await client.attach(agent_id)
        assert attach_result == {"attached_agent_id": agent_id}

        # Wait until the first forwarded update has been observed.
        async def _wait_for_first_update() -> None:
            while not any(
                kind == "notification" and method == acp.CLIENT_METHODS["session_update"]
                for kind, method, *_rest in client.stream_events
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_first_update(), timeout=1.0)

        # At the JSON-RPC layer, the `_attach` success response must be
        # observed before any `session/update` notifications. We assert this
        # directly against the Connection's incoming message stream rather
        # than relying on when the client coroutine that awaited
        # `send_request` happens to resume.
        attach_response_index: int | None = None
        first_update_index: int | None = None
        for i, event in enumerate(client.stream_events):
            kind = event[0]
            if kind == "response" and attach_response_index is None:
                result = event[1]
                if isinstance(result, dict) and result.get("attached_agent_id") == agent_id:
                    attach_response_index = i
            elif kind == "notification" and first_update_index is None:
                method = event[1]
                if method == acp.CLIENT_METHODS["session_update"]:
                    first_update_index = i
            if attach_response_index is not None and first_update_index is not None:
                break

        assert attach_response_index is not None
        assert first_update_index is not None
        assert first_update_index > attach_response_index

        # The forwarded notifications must reflect the retained history in
        # order.

        # Wait until at least the two retained updates have been observed.
        async def _wait_for_notifications(count: int) -> None:
            while len(client.notifications) < count:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_notifications(2), timeout=1.0)

        titles = [n.update.title for n in client.notifications]  # type: ignore[attr-defined]
        assert titles[0] == "pre1"
        assert titles[1] == "pre2"

        # ------------------------------------------------------------------
        # Prompt and interrupt reach only the attached agent
        # ------------------------------------------------------------------

        prompt_result = await client.prompt("hello")
        # The concrete response is an ACP PromptResponse JSON object.
        pr = acp_schema.PromptResponse.model_validate(prompt_result)
        assert pr.stop_reason == "end_turn"
        assert pr.field_meta == {"swarm_output": f"reply:{agent_id}:hello"}

        await client.interrupt()

        # The prompt should have been routed to the attached agent with
        # the expected text content encoded in the ACP PromptRequest.
        assert len(prompt_calls) == 1
        called_agent, called_prompt = prompt_calls[0]
        assert called_agent == agent_id
        assert isinstance(called_prompt, list)
        assert getattr(called_prompt[0], "text", None) == "hello"

        # The interrupt should be delivered to the same attached agent.
        async def _wait_for_interrupt() -> None:
            while not interrupt_calls:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_interrupt(), timeout=1.0)
        assert interrupt_calls == [agent_id]

        # ------------------------------------------------------------------
        # Detach stops forwarding but leaves the Epic 008 stream intact
        # ------------------------------------------------------------------

        result1 = await client.detach()
        result2 = await client.detach()
        assert result1 == {"detached": True}
        assert result2 == {"detached": True}
        assert mux.attached_agent_id is None

        # Further updates are visible on the Epic 008 stream but no
        # longer forwarded to the external client.
        post_detach = _publish_info(stream, "after-detach")

        async with stream.subscribe() as independent:
            # New subscribers see retained history followed by live
            # updates. Consume until we observe the post-detach update.
            async def _wait_for_title(title: str) -> ReceivedSessionUpdate:
                while True:
                    item = await _anext_with_timeout(independent)
                    if getattr(item.update, "title", None) == title:
                        return item

            received = await _wait_for_title("after-detach")
            assert received.update.title == "after-detach"

        # Give the mux a brief window; no additional notifications should
        # be delivered to the external client for the post-detach update.
        await asyncio.sleep(0.05)
        titles_after = [n.update.title for n in client.notifications]  # type: ignore[attr-defined]
        assert "after-detach" not in titles_after

        # The underlying AcpAgentSession remains managed by NateOhaAcpClient.
        persisted = acp_client._sessions.get(agent_id)  # type: ignore[attr-defined]
        assert isinstance(persisted, AcpAgentSession)
        assert persisted.status in {"starting", "running"}

        await client.close()
    finally:
        server.close()
        await server.wait_closed()

    # After connection shutdown, the mux must be closed and no
    # forwarding subscription left active on the Epic 008 stream.
    assert mux._closed is True  # type: ignore[attr-defined]
    assert mux._attachment is None  # type: ignore[attr-defined]
    assert len(stream._subscribers) == 0  # type: ignore[attr-defined]




@pytest.mark.asyncio
async def test_swarm_acp_server_transport_switching_reroutes_prompt_and_updates(tmp_path: Path) -> None:
    """Attachment switching reroutes both updates and prompt/interrupt.

    This scenario sets up two agents (A and B) backed by separate
    :class:`AcpAgentSession` instances and validates that switching the
    external attachment from A to B causes:

    * retained updates from A to be replayed when A is attached;
    * retained updates from B to be replayed when B is attached;
    * no further A updates to be forwarded after switching to B; and
    * subsequent prompt and interrupt operations to target only B.
    """

    config = _make_config(tmp_path)
    acp_client = NateOhaAcpClient(config=config)

    agent_a = "agent-a"
    agent_b = "agent-b"

    daemon = _FakeDaemon(agent_ids=[agent_a, agent_b])

    # Seed AcpAgentSession records for both agents. The primary agent's
    # stream is returned directly; the secondary agent's stream is looked
    # up via the adapter's session registry.
    server, stream_a, mux_future = await _start_swarm_acp_server(
        agent_id=agent_a,
        daemon=daemon,
        acp_client=acp_client,
        extra_agent_ids=[agent_b],
    )

    session_b = acp_client._sessions.get(agent_b)  # type: ignore[attr-defined]
    assert isinstance(session_b, AcpAgentSession)
    stream_b = session_b.update_stream

    host, port = server.sockets[0].getsockname()[:2]

    try:
        client = await _RecordingClient.connect(host, port)
        mux = await asyncio.wait_for(mux_future, timeout=1.0)

        # Patch prompt/interrupt so we can observe routing decisions without
        # performing external I/O.
        prompt_calls: list[tuple[str, object | None]] = []
        interrupt_calls: list[str] = []

        async def fake_prompt(agent: str, prompt: object | None = None) -> str | None:
            prompt_calls.append((agent, prompt))
            text_value: str | None = None
            if isinstance(prompt, list) and prompt:
                first = prompt[0]
                text_value = getattr(first, "text", None)
            return f"reply:{agent}:{text_value}"

        async def fake_interrupt(agent: str) -> None:
            interrupt_calls.append(agent)

        acp_client.prompt = fake_prompt  # type: ignore[assignment]
        acp_client.interrupt = fake_interrupt  # type: ignore[assignment]

        # ------------------------------------------------------------------
        # Publish retained history for both agents before any attachment
        # ------------------------------------------------------------------

        _publish_info(stream_a, "A-pre1")
        _publish_info(stream_a, "A-pre2")
        _publish_info(stream_b, "B-pre1")
        _publish_info(stream_b, "B-pre2")

        # ------------------------------------------------------------------
        # Attach A: only A's retained history is forwarded
        # ------------------------------------------------------------------

        attach_a = await client.attach(agent_a)
        assert attach_a == {"attached_agent_id": agent_a}
        assert mux.attached_agent_id == agent_a

        async def _wait_for_notifications(count: int) -> None:
            while len(client.notifications) < count:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_notifications(2), timeout=1.0)
        titles_a = [n.update.title for n in client.notifications]  # type: ignore[attr-defined]
        assert titles_a[:2] == ["A-pre1", "A-pre2"]
        assert "B-pre1" not in titles_a and "B-pre2" not in titles_a

        # ------------------------------------------------------------------
        # Attach B: subsequent forwarding targets B and replays B's history
        # ------------------------------------------------------------------

        attach_b = await client.attach(agent_b)
        assert attach_b == {"attached_agent_id": agent_b}
        assert mux.attached_agent_id == agent_b

        start_idx = len(client.notifications)

        async def _wait_for_more_notifications(count: int) -> None:
            while len(client.notifications) < start_idx + count:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_more_notifications(2), timeout=1.0)
        titles_b = [n.update.title for n in client.notifications[start_idx:]]  # type: ignore[attr-defined]
        assert titles_b == ["B-pre1", "B-pre2"]

        # Publish live updates on both streams after switching. Only B's
        # live update should reach the external client.
        _publish_info(stream_a, "A-live-after-switch")
        _publish_info(stream_b, "B-live-after-switch")

        live_start = len(client.notifications)

        async def _wait_for_live_notifications() -> None:
            # Expect at least one new notification for B.
            while len(client.notifications) <= live_start:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_live_notifications(), timeout=1.0)
        live_titles = [n.update.title for n in client.notifications[live_start:]]  # type: ignore[attr-defined]
        assert "B-live-after-switch" in live_titles
        assert "A-live-after-switch" not in live_titles

        # ------------------------------------------------------------------
        # Prompt and interrupt after switching reach only agent B
        # ------------------------------------------------------------------

        prompt_result = await client.prompt("hello-b")
        pr = acp_schema.PromptResponse.model_validate(prompt_result)
        assert pr.stop_reason == "end_turn"
        assert pr.field_meta == {"swarm_output": f"reply:{agent_b}:hello-b"}

        # The adapter prompt should have been invoked exactly once for B.
        assert len(prompt_calls) == 1
        called_agent, called_prompt = prompt_calls[0]
        assert called_agent == agent_b
        assert isinstance(called_prompt, list)
        assert getattr(called_prompt[0], "text", None) == "hello-b"

        await client.interrupt()

        async def _wait_for_interrupt() -> None:
            while not interrupt_calls:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait_for_interrupt(), timeout=1.0)
        assert interrupt_calls == [agent_b]

        await client.close()
    finally:
        server.close()
        await server.wait_closed()

    # After connection shutdown, the mux must be closed and no forwarding
    # subscriptions left active on either Epic 008 stream.
    assert mux._closed is True  # type: ignore[attr-defined]
    assert mux._attachment is None  # type: ignore[attr-defined]
    assert len(stream_a._subscribers) == 0  # type: ignore[attr-defined]
    assert len(stream_b._subscribers) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_swarm_acp_server_transport_error_mapping_and_shutdown(tmp_path: Path) -> None:
    """Mux/domain failures surface as ACP errors with logical mux codes.

    This scenario verifies that an invalid `_attach` request for an
    unknown agent results in an ACP :class:`RequestError` whose
    ``error.data.mux_code`` matches the contract-defined logical code.
    It also asserts that connection shutdown leaves no forwarding
    subscription active on the Epic 008 stream.
    """

    config = _make_config(tmp_path)
    acp_client = NateOhaAcpClient(config=config)

    known_agent = "agent-known"
    daemon = _FakeDaemon(agent_ids=[known_agent])

    server, stream, mux_future = await _start_swarm_acp_server(
        agent_id=known_agent,
        daemon=daemon,
        acp_client=acp_client,
    )

    host, port = server.sockets[0].getsockname()[:2]

    try:
        client = await _RecordingClient.connect(host, port)
        mux = await asyncio.wait_for(mux_future, timeout=1.0)

        # Attempt to attach to an unknown agent; this should map the
        # underlying UnknownAgentError to MUX_UNKNOWN_AGENT and surface an
        # ACP RequestError with that logical code in error.data.
        with pytest.raises(acp.RequestError) as exc_info:
            await client.attach("missing-agent")

        err = exc_info.value
        assert isinstance(err.data, dict)
        assert err.data.get("mux_code") == "MUX_UNKNOWN_AGENT"

        await client.close()
    finally:
        server.close()
        await server.wait_closed()

    # After the failed connection, the mux must be closed and the Epic
    # 008 stream left without a forwarding subscriber.
    assert mux._closed is True  # type: ignore[attr-defined]
    assert mux._attachment is None  # type: ignore[attr-defined]
    assert len(stream._subscribers) == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Epic 009 real-path integration: Swarm ACP server over REAL runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swarm_acp_server_real_runtime_two_agents_switch_and_shutdown(tmp_path: Path) -> None:
    """End-to-end Swarm ACP server over REAL nate-oha echo agents.

    This test lifts the T027.2 transport assertions into the full Epic 009
    real-path scenario:

    * A REAL :class:`RuntimeDaemon` is constructed in ``adapter_mode=REAL``
      with two nate-oha echo agents in durable swarm state.
    * The REAL :class:`NateOhaAcpClient` starts ACP sessions for both agents
      via :meth:`start_agent_async`, wiring typed
      :class:`AcpSessionUpdateStream` telemetry from nate-oha into the
      runtime.
    * A single-connection Swarm ACP server is started using the production
      :class:`SwarmACPServerSession`, :class:`ConnectionExternalACPConnection`,
      and :class:`SwarmACPConnection` helpers.
    * An external ACP client attaches first to agent A, then switches to
      agent B, sending real ``session/prompt`` and ``session/cancel``
      operations over JSON-RPC.
    * Agent-produced typed updates flow through the canonical Epic 008
      pipeline into :class:`SwarmACPMux` and are forwarded as
      ``session/update`` notifications to the external client.
    * Prompt and interrupt routing is observed via thin logging wrappers
      around the REAL :class:`NateOhaAcpClient` methods (which still call the
      underlying ACP SDK), and connection/runtime cleanup is asserted at the
      end of the test.
    """

    # ------------------------------
    # REAL runtime + swarm metadata
    # ------------------------------

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[3]
    base_config = repo_root / "nate-oha-profiles" / "profile1.json"

    env = dict(os.environ)
    env.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
            "NATE_NTM_NATE_OHA_CONFIG": str(base_config),
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
        }
    )

    config = load_runtime_config(project_path=project, env=env)

    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)

    agent_a = "swarm-real-a"
    agent_b = "swarm-real-b"

    nate_oha_cfg = build_effective_nate_oha_config(config=config)

    meta_a = AgentState(
        agent_id=agent_a,
        display_name="Swarm Real Agent A",
        conversation_id="",  # Force a new ACP session on first run.
        nate_oha_config=nate_oha_cfg,
    )
    meta_b = AgentState(
        agent_id=agent_b,
        display_name="Swarm Real Agent B",
        conversation_id="",
        nate_oha_config=nate_oha_cfg,
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id=str(config.project_path),
        created_at=now,
        last_updated_at=now,
        agents={meta_a.agent_id: meta_a, meta_b.agent_id: meta_b},
    )
    store.save_swarm_state(swarm)

    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.acp, NateOhaAcpClient)
    adapters.acp.executable = "nate-oha"  # type: ignore[attr-defined]

    daemon = RuntimeDaemon.resume(config, adapters=adapters)
    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    # ------------------------------
    # Start REAL ACP sessions for both agents
    # ------------------------------

    meta_a_loaded = store.load_agent_state(agent_a)
    meta_b_loaded = store.load_agent_state(agent_b)

    await acp_client.start_agent_async(agent_a, metadata=meta_a_loaded)
    await acp_client.start_agent_async(agent_b, metadata=meta_b_loaded)

    # ------------------------------
    # Start Swarm ACP server bound to the REAL daemon
    # ------------------------------

    server, mux_future = await _start_swarm_acp_server_for_daemon(daemon=daemon)
    host, port = server.sockets[0].getsockname()[:2]

    try:
        client = await _RecordingClient.connect(host, port)
        mux = await asyncio.wait_for(mux_future, timeout=5.0)

        # Wrap REAL prompt/interrupt to log routing decisions while still
        # exercising the nate-oha / ACP SDK path.
        prompt_calls: list[tuple[str, str]] = []
        interrupt_calls: list[str] = []

        orig_prompt = acp_client.prompt
        orig_interrupt = acp_client.interrupt

        async def logging_prompt(agent_id: str, prompt: str | None = None) -> str | None:
            # Accept both raw text and ACP SDK-style content blocks. When the
            # server adapter passes through the PromptRequest ``prompt`` field
            # directly, it arrives here as a list of TextContentBlock objects;
            # for logging and delegation we normalise this to the first text
            # block's ``text`` value.
            if isinstance(prompt, list) and prompt:
                first = prompt[0]
                text = getattr(first, "text", "")
            else:
                text = "" if prompt is None else prompt
            prompt_calls.append((agent_id, text))
            # Delegate to the REAL NateOhaAcpClient implementation using the
            # normalised text value.
            return await orig_prompt(agent_id, text)  # type: ignore[arg-type]

        async def logging_interrupt(agent_id: str) -> None:
            interrupt_calls.append(agent_id)
            await orig_interrupt(agent_id)  # type: ignore[arg-type]

        acp_client.prompt = logging_prompt  # type: ignore[assignment]
        acp_client.interrupt = logging_interrupt  # type: ignore[assignment]

        def _extract_text_from_notifications(start: int = 0) -> list[str]:
            texts: list[str] = []
            for notif in client.notifications[start:]:
                update = notif.update
                try:
                    payload = update.model_dump(mode="json", by_alias=True)  # type: ignore[call-arg]
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                content = payload.get("content")
                if isinstance(content, dict) and content.get("type") == "text":
                    text_val = content.get("text")
                    if isinstance(text_val, str):
                        texts.append(text_val)
            return texts

        async def _wait_for_text(expected: str, *, start: int, timeout: float = 10.0) -> None:
            """Wait until ``expected`` appears in forwarded session/update text."""

            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                texts = _extract_text_from_notifications(start)
                if any(expected in t for t in texts):
                    return
                now_time = loop.time()
                if now_time >= deadline:
                    raise AssertionError(
                        f"Timed out waiting for {expected!r} in session/update notifications; "
                        f"saw {texts!r}"
                    )
                await asyncio.sleep(0.05)

        # ------------------------------
        # Attach to agent A and send a prompt
        # ------------------------------

        attach_a = await client.attach(agent_a)
        assert attach_a == {"attached_agent_id": agent_a}
        assert mux.attached_agent_id == agent_a

        prompt_text_a = "hello from agent A via swarm"
        start_idx_a = len(client.notifications)
        await client.prompt(prompt_text_a)
        await _wait_for_text(prompt_text_a, start=start_idx_a, timeout=15.0)

        # The REAL adapter's prompt should have been invoked for agent A.
        assert (agent_a, prompt_text_a) in prompt_calls

        # At the JSON-RPC layer, the `_attach` success response must still be
        # observed before any forwarded `session/update` notifications, even
        # when using REAL nate-oha processes behind the mux.
        attach_response_index: int | None = None
        first_update_index: int | None = None
        for i, event in enumerate(client.stream_events):
            kind = event[0]
            if kind == "response" and attach_response_index is None:
                result = event[1]
                if isinstance(result, dict) and result.get("attached_agent_id") == agent_a:
                    attach_response_index = i
            elif kind == "notification" and first_update_index is None:
                method = event[1]
                if method == acp.CLIENT_METHODS["session_update"]:
                    first_update_index = i
            if attach_response_index is not None and first_update_index is not None:
                break

        assert attach_response_index is not None
        assert first_update_index is not None
        assert first_update_index > attach_response_index

        # ------------------------------
        # Switch attachment to agent B and send another prompt
        # ------------------------------

        attach_b = await client.attach(agent_b)
        assert attach_b == {"attached_agent_id": agent_b}
        assert mux.attached_agent_id == agent_b

        prompt_text_b = "hello from agent B via swarm"
        start_idx_b = len(client.notifications)
        await client.prompt(prompt_text_b)
        await _wait_for_text(prompt_text_b, start=start_idx_b, timeout=15.0)

        # Prompts should have been routed to A then B in order.
        assert (agent_a, prompt_text_a) in prompt_calls
        assert (agent_b, prompt_text_b) in prompt_calls

        # ------------------------------
        # Interrupt while attached to B
        # ------------------------------

        await client.interrupt()

        async def _wait_for_interrupt() -> None:
            while not interrupt_calls:
                await asyncio.sleep(0.05)

        await asyncio.wait_for(_wait_for_interrupt(), timeout=10.0)
        # The last interrupt must target the currently attached agent (B).
        assert interrupt_calls[-1] == agent_b

        await client.close()
    finally:
        server.close()
        await server.wait_closed()

    # After connection shutdown the mux must be closed with no active
    # forwarding attachment.
    assert mux._closed is True  # type: ignore[attr-defined]
    assert mux._attachment is None  # type: ignore[attr-defined]

    # ------------------------------
    # Clean shutdown of REAL ACP sessions
    # ------------------------------

    try:
        await acp_client.stop_agent_async(agent_a, timeout=10.0)
        await acp_client.stop_agent_async(agent_b, timeout=10.0)
    finally:
        # Ensure session records reflect termination and no active
        # subscription context remains for either agent.
        session_a = acp_client._sessions.get(agent_a)  # type: ignore[attr-defined]
        session_b = acp_client._sessions.get(agent_b)  # type: ignore[attr-defined]
        if session_a is not None:
            assert session_a.status == "terminated"
        if session_b is not None:
            assert session_b.status == "terminated"

        assert agent_a not in acp_client._session_contexts  # type: ignore[attr-defined]
        assert agent_b not in acp_client._session_contexts  # type: ignore[attr-defined]

