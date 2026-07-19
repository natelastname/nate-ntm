from __future__ import annotations

from datetime import datetime
from pathlib import Path
import asyncio

import pytest

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.acp_client import AcpAgentSession, AcpClientError, NateOhaAcpClient, _EVENT_STREAM_CLOSED
from nate_ntm.runtime.acp_types import SessionUpdate
from nate_ntm.runtime.acp_update_stream import AgentSessionNotActive, StreamClosedError
from nate_ntm.runtime.events import AgentEvent, AgentEventSource


def _make_config(tmp_path: Path) -> RuntimeConfig:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    return load_runtime_config(project_path=project_root)


@pytest.mark.asyncio
async def test_subscribe_events_broadcasts_to_multiple_subscribers(tmp_path: Path) -> None:
    """Multiple subscribers receive the same emitted event independently.

    This exercise ensures that :meth:`NateOhaAcpClient.subscribe_events` uses
    per-subscriber queues with broadcast semantics rather than a single
    work-queue. A single call to :meth:`_emit_event` must deliver the event to
    every active subscriber for the agent.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-broadcast-1"
    event = AgentEvent(
        event_id="e1",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        agent_id=agent_id,
        source=AgentEventSource.ACP,
        type="acp.test_event",
        payload={"value": 42},
    )

    async with client.subscribe_events(agent_id) as events1:
        async with client.subscribe_events(agent_id) as events2:
            # Emit a single event; both subscriptions should observe it
            # independently without consuming it for one another.
            client._emit_event(event)

            ev1 = await asyncio.wait_for(events1.__anext__(), timeout=1.0)
            ev2 = await asyncio.wait_for(events2.__anext__(), timeout=1.0)

    # Both subscribers must have seen the exact same event object.
    assert ev1 is event
    assert ev2 is event

    # After leaving the subscription contexts, all per-agent subscribers should
    # have been unregistered.
    assert agent_id not in client._event_subscribers


@pytest.mark.asyncio
async def test_subscribe_events_cleans_up_on_timeout(tmp_path: Path) -> None:
    """Timeouts in consumers do not leak subscriptions.

    The subscription context manager is responsible for unregistering
    subscribers even when consumers experience timeouts while awaiting events.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-timeout-1"

    async with client.subscribe_events(agent_id) as events:
        # No events are emitted; waiting for the next item with a short timeout
        # should raise asyncio.TimeoutError.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(events.__anext__(), timeout=0.01)

    # The agent's subscriber set should be empty once the context exits.
    assert agent_id not in client._event_subscribers


@pytest.mark.asyncio
async def test_subscribe_events_cleans_up_on_cancelled_consumer(tmp_path: Path) -> None:
    """Cancellation of a waiting consumer removes its subscription.

    When a task awaiting events from a subscription is cancelled, the
    subscription's iterator ``finally`` block and the context manager's
    teardown must still unregister the subscriber so that no stale queues
    remain.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-cancel-1"

    async with client.subscribe_events(agent_id) as events:
        task = asyncio.create_task(events.__anext__())

        # Allow the task to start and block on the internal queue before
        # cancelling it. ``sleep(0)`` is used here purely as a scheduling
        # yield, not as an event-synchronization mechanism.
        await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # After the subscription context exits, there should be no lingering
    # subscriber queues for the agent.
    assert agent_id not in client._event_subscribers


@pytest.mark.asyncio
async def test_close_event_subscribers_terminates_stream(tmp_path: Path) -> None:
    """Closing event subscribers terminates active iterators promptly.

    This simulates the lifecycle behavior used when an agent stops or fails.
    Calling the private ``_close_event_subscribers`` helper should cause any
    active subscription iterator to complete rather than wait indefinitely.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-close-1"

    async with client.subscribe_events(agent_id) as events:
        # Simulate agent shutdown by closing all subscribers for this agent.
        client._close_event_subscribers(agent_id)

        # The iterator should terminate with StopAsyncIteration on the next
        # attempted ``__anext__`` call instead of blocking.
        with pytest.raises(StopAsyncIteration):
            await events.__anext__()

    # No subscribers should remain registered for the agent once both the
    # iterator and the subscription context have unwound.
    assert agent_id not in client._event_subscribers


@pytest.mark.asyncio
async def test_close_event_subscribers_inserts_sentinel_when_queue_full(tmp_path: Path) -> None:
    """Closing subscribers inserts a sentinel even when the queue is full.

    This guards against regressions where a full per-agent queue would
    prevent the end-of-stream marker from being enqueued, leaving
    consumers blocked on ``queue.get()``.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-close-full-1"

    # Register a subscriber queue and fill it to capacity using the
    # normal event-emission path so that ``queue.full()`` is true when
    # ``_close_event_subscribers`` runs.
    queue = client._register_event_subscriber(agent_id)

    event = AgentEvent(
        event_id="e-base",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        agent_id=agent_id,
        source=AgentEventSource.ACP,
        type="acp.test_event",
        payload={"value": 1},
    )

    for _ in range(queue.maxsize):
        client._emit_event(event)

    assert queue.qsize() == queue.maxsize

    client._close_event_subscribers(agent_id)

    # After closure, the sentinel should be present exactly once in the
    # queue despite it having been full.
    items: list[object] = []
    while not queue.empty():
        items.append(queue.get_nowait())

    assert _EVENT_STREAM_CLOSED in items
    assert items.count(_EVENT_STREAM_CLOSED) == 1
    assert len(items) == queue.maxsize


@pytest.mark.asyncio
async def test_subscribe_events_close_inserts_sentinel_when_queue_full(tmp_path: Path) -> None:
    """Exiting ``subscribe_events`` inserts a sentinel when the queue is full.

    This mirrors the behavior of ``_close_event_subscribers`` and
    ensures that per-subscriber teardown cannot leave blocked
    consumers when their queues are at capacity.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-sub-close-full-1"

    # Manually enter the async context manager so we can inspect the
    # underlying queue before and after ``__aexit__`` runs.
    cm = client.subscribe_events(agent_id)
    _events_iter = await cm.__aenter__()

    subscribers = client._event_subscribers.get(agent_id)
    assert subscribers is not None and len(subscribers) == 1
    (queue,) = tuple(subscribers)

    event = AgentEvent(
        event_id="e-base",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        agent_id=agent_id,
        source=AgentEventSource.ACP,
        type="acp.test_event",
        payload={"value": 1},
    )

    for _ in range(queue.maxsize):
        client._emit_event(event)

    assert queue.qsize() == queue.maxsize

    # Exiting the context should enqueue the close sentinel even though
    # the queue is full.
    await cm.__aexit__(None, None, None)

    items: list[object] = []
    while not queue.empty():
        items.append(queue.get_nowait())

    assert _EVENT_STREAM_CLOSED in items
    assert items.count(_EVENT_STREAM_CLOSED) == 1
    assert len(items) == queue.maxsize



class _DummyUpdate(SessionUpdate):  # type: ignore[misc]
    """Minimal concrete SessionUpdate type for testing.

    The real ACP SDK exposes concrete subclasses of the ``SessionUpdate``
    protocol type; for tests we provide a lightweight stand-in so that
    ``AcpSessionUpdateStream`` can assign sequence numbers and retain
    history without depending on specific ACP schemas.
    """

    pass


@pytest.mark.asyncio
async def test_stop_agent_async_closes_typed_update_stream(tmp_path: Path) -> None:
    """Stopping an async ACP session closes its typed update stream.

    This ensures that callers publishing into the per-session
    :class:`AcpSessionUpdateStream` after shutdown observe
    :class:`StreamClosedError` and can treat the stream as terminal.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-async-stop-1"

    class DummyContext:
        def __init__(self) -> None:
            self.exited = False

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            self.exited = True

    ctx = DummyContext()

    # Create a synthetic AcpAgentSession with a live typed update stream.
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

    # Publish a single update to confirm the stream accepts events prior to
    # shutdown.
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    session.update_stream.publish(_DummyUpdate(), received_at=t0)

    client._session_contexts[agent_id] = ctx  # type: ignore[assignment]
    client._sessions[agent_id] = session

    await client.stop_agent_async(agent_id, timeout=5.0)

    # The underlying context manager should have been exited and the
    # in-memory session marked as terminated.
    assert ctx.exited is True
    assert client._sessions[agent_id].status == "terminated"

    # Further publishes into the per-session stream must fail with
    # StreamClosedError.
    with pytest.raises(StreamClosedError):
        session.update_stream.publish(_DummyUpdate(), received_at=t0)


@pytest.mark.asyncio
async def test_stop_agent_async_closes_typed_update_stream_on_failure(tmp_path: Path) -> None:
    """Even when shutdown fails, the typed stream is closed.

    When the underlying async context manager raises during exit,
    :meth:`stop_agent_async` re-raises an :class:`AcpClientError` but still
    closes the per-session typed update stream so callers observe a
    consistent terminal state.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-async-stop-fail-1"

    class FailingContext:
        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            raise RuntimeError("synthetic shutdown failure")

    ctx = FailingContext()

    session = AcpAgentSession(
        agent_id=agent_id,
        conversation_id="conv-2",
        process=object(),
        connection=object(),
        protocol_client=object(),
        status="running",
        stderr_task=None,
        exit_monitor_task=None,
    )

    t0 = datetime(2024, 1, 1, 12, 0, 0)
    session.update_stream.publish(_DummyUpdate(), received_at=t0)

    client._session_contexts[agent_id] = ctx  # type: ignore[assignment]
    client._sessions[agent_id] = session

    # Shutdown failures propagate as AcpClientError.
    with pytest.raises(AcpClientError):
        await client.stop_agent_async(agent_id, timeout=5.0)

    # The synthetic session object remains available in this test and its
    # typed update stream must still be closed.
    with pytest.raises(StreamClosedError):
        session.update_stream.publish(_DummyUpdate(), received_at=t0)



@pytest.mark.asyncio
async def test_on_session_update_preserves_typed_update_and_timestamp(tmp_path: Path) -> None:
    """_on_session_update forwards typed updates intact into the stream.

    This verifies that a concrete ``SessionUpdate`` instance and its
    associated ``received_at`` timestamp are preserved end-to-end from the
    ACP callback into :class:`AcpSessionUpdateStream` and
    :meth:`subscribe_acp_updates`.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-update-pass-1"

    # Create a synthetic live session with an attached typed update stream.
    session = AcpAgentSession(
        agent_id=agent_id,
        conversation_id="conv-typed-1",
        process=object(),
        connection=object(),
        protocol_client=object(),
        status="running",
        stderr_task=None,
        exit_monitor_task=None,
    )

    client._sessions[agent_id] = session

    update = _DummyUpdate()
    received_at = datetime(2024, 1, 1, 12, 0, 0)

    # Simulate the ACP SDK invoking the protocol client's callback, which in
    # turn calls ``NateOhaAcpClient._on_session_update``.
    client._on_session_update(
        agent_id=agent_id,
        session_id="conv-typed-1",
        update=update,
        received_at=received_at,
    )

    # The first item observed via ``subscribe_acp_updates`` should reflect
    # the exact update object and timestamp that were passed into
    # ``_on_session_update``.
    async with client.subscribe_acp_updates(agent_id) as updates:
        received = await asyncio.wait_for(updates.__anext__(), timeout=1.0)

    assert received.sequence == 1
    assert received.update is update
    assert received.received_at == received_at



@pytest.mark.asyncio
async def test_subscribe_acp_updates_requires_active_session(tmp_path: Path) -> None:
    """subscribe_acp_updates rejects missing or inactive sessions.

    When no live AcpAgentSession exists for an agent, or when the
    recorded session is not in a "starting" / "running" state, the
    helper must raise AgentSessionNotActive instead of exposing a
    dangling subscription.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-acp-no-session-1"

    # No session has been recorded for this agent.
    with pytest.raises(AgentSessionNotActive):
        async with client.subscribe_acp_updates(agent_id):
            assert False, "unreachable"

    # A recorded but inactive session (for example, terminated) must
    # also be rejected.
    session = AcpAgentSession(
        agent_id=agent_id,
        conversation_id="conv-inactive-1",
        process=object(),
        connection=object(),
        protocol_client=object(),
        status="terminated",
        stderr_task=None,
        exit_monitor_task=None,
    )
    client._sessions[agent_id] = session

    with pytest.raises(AgentSessionNotActive):
        async with client.subscribe_acp_updates(agent_id):
            assert False, "unreachable"


@pytest.mark.asyncio
async def test_subscribe_acp_updates_binds_to_single_session_stream(tmp_path: Path) -> None:
    """Subscriptions attach to one concrete session-owned update stream.

    Once established, a subscription created via subscribe_acp_updates
    observes updates from the session's AcpSessionUpdateStream that was
    active at attachment time.
    """

    config = _make_config(tmp_path)
    client = NateOhaAcpClient(config=config)

    agent_id = "agent-acp-attach-1"

    session = AcpAgentSession(
        agent_id=agent_id,
        conversation_id="conv-attach-1",
        process=object(),
        connection=object(),
        protocol_client=object(),
        status="running",
        stderr_task=None,
        exit_monitor_task=None,
    )
    client._sessions[agent_id] = session

    t0 = datetime(2024, 1, 1, 12, 0, 0)

    async with client.subscribe_acp_updates(agent_id) as updates:
        ev = session.update_stream.publish(_DummyUpdate(), received_at=t0)
        received = await asyncio.wait_for(updates.__anext__(), timeout=1.0)

    # The subscription must observe exactly the event published into the
    # owning session's typed stream.
    assert received is ev

