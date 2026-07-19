from __future__ import annotations

"""Typed, per-session ACP update stream primitives.

This module defines:

- :class:`ReceivedSessionUpdate`: a small receipt record that wraps a typed
  ACP ``SessionUpdate`` object with session-local sequence information;
- :class:`AcpSessionUpdateStream`: an in-memory, replay-capable stream that
  stores a bounded history of :class:`ReceivedSessionUpdate` values for a
  single concrete ACP session and exposes an async subscription API.

The stream is intended to be owned by :class:`AcpAgentSession` instances in
:mod:`nate_ntm.runtime.acp_client`. It replaces the older generic
``AgentEvent`` telemetry pipeline and is used for ACP transport and mux
forwarding only.
"""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Deque, List, Set

from .acp_types import SessionUpdate


@dataclass(frozen=True, slots=True)
class ReceivedSessionUpdate:
    """Receipt record for a single ACP ``SessionUpdate``.

    Attributes
    ----------
    sequence:
        1-based, monotonically increasing sequence number local to a single
        concrete ACP session.

    received_at:
        Timestamp indicating when the runtime observed this update.

    update:
        The exact typed ACP ``SessionUpdate`` model instance delivered by the
        SDK.
    """

    sequence: int
    received_at: datetime
    update: SessionUpdate


class AcpUpdateStreamError(RuntimeError):
    """Base error type for session update stream failures."""


class StreamClosedError(AcpUpdateStreamError):
    """Raised when publishing to or subscribing from a closed stream."""


class SubscriberOverflowError(AcpUpdateStreamError):
    """Raised when a subscriber's live queue exceeds its capacity."""


class AgentSessionNotActive(AcpUpdateStreamError):
    """Raised when attempting to attach to a non-existent ACP session."""


@dataclass(slots=True)
class AcpSessionUpdateStream:
    """Replay-capable, per-session stream of :class:`ReceivedSessionUpdate`.

    This stream is intended to be owned by exactly one concrete ACP session.

    Properties:
    - Maintains a bounded retained history of updates (oldest entries are
      dropped when the limit is exceeded).
    - Assigns monotonically increasing sequence numbers starting at 1.
    - Exposes an async subscription API that first replays retained history
      and then yields live updates until the stream is closed.

    The current implementation uses unbounded per-subscriber queues for live
    delivery to avoid silent data loss. Bounded-queue and explicit overflow
    semantics can be introduced later without changing the public interface.
    """

    max_events: int = 200

    _events: Deque[ReceivedSessionUpdate] = field(default_factory=deque, init=False, repr=False)
    _next_sequence: int = field(default=1, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _close_error: BaseException | None = field(default=None, init=False, repr=False)

    # Per-subscriber live queues. Each queue receives new updates published
    # after the subscriber attaches. Subscribers always see a full replay of
    # the retained history first.
    _subscribers: Set[asyncio.Queue[ReceivedSessionUpdate]] = field(default_factory=set, init=False, repr=False)

    def publish(self, update: SessionUpdate, *, received_at: datetime) -> ReceivedSessionUpdate:
        """Publish ``update`` into this session's stream.

        Returns the corresponding :class:`ReceivedSessionUpdate` instance.
        """

        if self._closed:
            raise StreamClosedError("cannot publish to closed AcpSessionUpdateStream")

        event = ReceivedSessionUpdate(
            sequence=self._next_sequence,
            received_at=received_at,
            update=update,
        )
        self._next_sequence += 1

        # Append to bounded retained history (drop oldest when full).
        self._events.append(event)
        if self.max_events > 0 and len(self._events) > self.max_events:
            # Drop oldest entries until within bound.
            while len(self._events) > self.max_events:
                self._events.popleft()

        # Fan out to subscribers. Subscriber queues are currently unbounded to
        # avoid silent loss of ACP updates.
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - defensive
                # With unbounded queues this should not occur. If it does,
                # treat it as a hard error so it can be surfaced during tests.
                raise

        return event

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[ReceivedSessionUpdate]]:
        """Subscribe to this stream.

        The returned async iterator will:
        - yield a snapshot of retained history as of subscription time;
        - then yield live updates until the stream is closed.
        """

        # Snapshot retained history at subscription time.
        snapshot: List[ReceivedSessionUpdate] = list(self._events)

        # If already closed, we still replay the retained history, but there
        # will be no live updates.
        if self._closed:
            live_queue: asyncio.Queue[ReceivedSessionUpdate] | None = None
        else:
            live_queue = asyncio.Queue[ReceivedSessionUpdate]()
            self._subscribers.add(live_queue)

        async def _iterator() -> AsyncIterator[ReceivedSessionUpdate]:
            # First, drain the immutable snapshot.
            for ev in snapshot:
                yield ev

            # Then, if still live, consume the live queue.
            if live_queue is None:
                return

            try:
                while True:
                    # When the stream has been closed and there are no
                    # remaining items in the subscriber queue, terminate
                    # the iterator so callers observe a natural end-of-
                    # stream signal.
                    if self._closed and live_queue.empty():
                        break

                    ev = await live_queue.get()
                    yield ev
            finally:
                self._subscribers.discard(live_queue)

        try:
            yield _iterator()
        finally:
            # No additional cleanup beyond removing the subscriber in the
            # iterator's finally block.
            pass

    def close(self, error: BaseException | None = None) -> None:
        """Mark the stream as closed.

        After calling this method, further publishes will raise
        :class:`StreamClosedError`. Existing subscribers will naturally
        terminate once they exhaust any items already present in their live
        queues. New subscribers will receive only the retained snapshot and
        then terminate.

        When ``error`` is provided, it is recorded for diagnostics and may
        be surfaced by higher-level components if needed.
        """

        self._closed = True
        if error is not None and self._close_error is None:
            self._close_error = error


__all__ = [
    "ReceivedSessionUpdate",
    "AcpUpdateStreamError",
    "StreamClosedError",
    "SubscriberOverflowError",
    "AgentSessionNotActive",
    "AcpSessionUpdateStream",
]
