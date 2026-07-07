from __future__ import annotations

"""High-level async client for the nate_ntm runtime control API.

This module provides a reusable, transport-owning client abstraction that
wraps the low-level :class:`JsonRpcHttpClient` and the ``/events`` WebSocket
endpoint exposed by :mod:`nate_ntm.api.runtime_api`.

The intent is to give higher-level consumers (for example, the Textual
runtime console, future ACP tooling, or automated tests) a single place to
interact with a running runtime using **typed models** for the control API
and a clean async interface for live events, without needing to know about
JSON-RPC envelopes, HTTP details, or WebSocket framing.

Layering:

- ``RuntimeClient`` owns:
  - JSON-RPC control calls via :class:`JsonRpcHttpClient`.
  - ``/events`` WebSocket connections, including basic reconnect logic.
  - Parsing of ``events.notify`` notifications into typed models.
- ``RuntimeSession`` (implemented in ``nate_ntm.tui.runtime_session``) will
  depend on this client to maintain a cached view of runtime state for UI
  consumers.

This module is intentionally **independent of Textual** and any TUI
concerns so that it can be reused by non-interactive tools.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, Mapping, Optional

import websockets
from pydantic import ValidationError
from websockets.exceptions import WebSocketException

from .client import JsonRpcClientError, JsonRpcHttpClient
from .jsonrpc import JSONRPC_VERSION
from .models import AgentDetailEvent, AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult

__all__ = ["EventsNotify", "RuntimeClient"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EventsNotify:
    """Typed representation of an ``events.notify`` notification.

    Parameters
    ----------
    subscription_id:
        Identifier returned by ``events.subscribe`` and echoed in the
        ``events.notify`` payload.

    event:
        Parsed :class:`AgentDetailEvent` model for the underlying
        :class:`~nate_ntm.runtime.events.AgentEvent` dictionary payload.
    """

    subscription_id: str
    event: AgentDetailEvent


@dataclass(slots=True)
class RuntimeClient:
    """Async client for the runtime control API and event stream.

    This client is responsible for all transport- and protocol-level
    concerns when talking to a running nate_ntm runtime daemon:

    * HTTP JSON-RPC control methods via :class:`JsonRpcHttpClient`.
    * ``/events`` WebSocket connections for ``events.notify`` notifications.

    It exposes **typed helpers** for the core control API and an async
    iterator for live events. Callers such as ``RuntimeSession`` and the
    Textual console should use this client instead of dealing with HTTP
    requests, JSON-RPC envelopes, or WebSocket frames directly.

    The client is intentionally independent of any UI framework.
    """

    host: str = "127.0.0.1"
    """Runtime control API host (defaults to localhost)."""

    port: int = 8765
    """Runtime control API port (defaults to the MVP port)."""

    timeout: Optional[float] = 10.0
    """Timeout in seconds for HTTP JSON-RPC calls (``None`` = no timeout)."""

    rpc_client: Optional[JsonRpcHttpClient] = field(default=None, repr=False)
    """Optional pre-configured JSON-RPC client.

    When provided, ``host``, ``port``, and ``timeout`` are not used to
    construct a new :class:`JsonRpcHttpClient`. This hook primarily exists
    for tests and advanced callers; most consumers should rely on the
    defaults.
    """

    def __post_init__(self) -> None:  # pragma: no cover - trivial wiring
        if self.rpc_client is None:
            self.rpc_client = JsonRpcHttpClient(host=self.host, port=self.port, timeout=self.timeout)

    # ------------------------------------------------------------------
    # Control API helpers (typed where models exist)
    # ------------------------------------------------------------------

    @property
    def _rpc(self) -> JsonRpcHttpClient:
        assert self.rpc_client is not None  # for type checkers
        return self.rpc_client

    async def get_runtime_status(self) -> RuntimeStatusResult:
        """Typed helper for ``runtime.get_status``.

        Returns a :class:`RuntimeStatusResult` model and surfaces
        :class:`JsonRpcClientError` if the server returns an error envelope.
        """

        return await self._rpc.get_runtime_status()

    async def get_swarm_overview(self) -> SwarmOverviewResult:
        """Typed helper for ``swarm.get_overview``."""

        return await self._rpc.get_swarm_overview()

    async def get_agent_detail(self, agent_id: str, max_events: int = 100) -> AgentDetailResult:
        """Typed helper for ``agent.get_detail``.

        Parameters
        ----------
        agent_id:
            Identifier of the agent to inspect.

        max_events:
            Maximum number of recent events to include in the result.
        """

        return await self._rpc.get_agent_detail(agent_id=agent_id, max_events=max_events)

    async def shutdown_runtime(self, timeout_seconds: int = 30) -> Mapping[str, Any]:
        """Helper for ``runtime.shutdown``.

        The result payload currently has a small dict shape and does not
        have a dedicated Pydantic model. This method returns the decoded
        mapping directly while still surfacing :class:`JsonRpcClientError`
        on JSON-RPC errors.
        """

        params: Dict[str, Any] = {"timeout_seconds": int(timeout_seconds)}
        result = await self._rpc.call_for_result("runtime.shutdown", params)
        assert isinstance(result, Mapping)
        return result

    async def subscribe_events(
        self,
        *,
        agent_ids: Optional[Iterable[str]] = None,
        include_runtime: bool = True,
    ) -> str:
        """Call ``events.subscribe`` and return the subscription identifier.

        Parameters
        ----------
        agent_ids:
            Optional iterable of agent identifiers to filter events. When
            ``None`` (the default), the server MAY interpret this as "all
            agents" for the current swarm, consistent with the runtime API
            contract.

        include_runtime:
            Whether to include runtime-level events in addition to agent-
            scoped events.
        """

        params: Dict[str, Any] = {"include_runtime": bool(include_runtime)}
        if agent_ids is not None:
            params["agent_ids"] = list(agent_ids)

        result = await self._rpc.call_for_result("events.subscribe", params)
        sub_id = result.get("subscription_id") if isinstance(result, Mapping) else None
        if not isinstance(sub_id, str):  # pragma: no cover - defensive
            raise ValueError("events.subscribe did not return a string subscription_id")
        return sub_id

    async def unsubscribe_events(self, subscription_id: str) -> Mapping[str, Any]:
        """Call ``events.unsubscribe`` for ``subscription_id``.

        Returns the decoded result mapping.
        """

        params = {"subscription_id": subscription_id}
        result = await self._rpc.call_for_result("events.unsubscribe", params)
        assert isinstance(result, Mapping)
        return result

    # ------------------------------------------------------------------
    # Live event streaming
    # ------------------------------------------------------------------

    def _events_ws_uri(self) -> str:
        """Return the ``ws://`` URI for the runtime's ``/events`` endpoint."""

        return f"ws://{self.host}:{self.port}/events"

    async def iter_events(
        self,
        *,
        subscription_id: Optional[str] = None,
        agent_ids: Optional[Iterable[str]] = None,
        include_runtime: bool = True,
        reconnect: bool = True,
        reconnect_initial_backoff: float = 0.5,
        reconnect_max_backoff: float = 5.0,
    ) -> AsyncIterator[EventsNotify]:
        """Yield :class:`EventsNotify` values for a runtime event subscription.

        This helper is designed to be consumed via ``async for``::

            async for notification in client.iter_events(agent_ids=None):
                ... # handle notification.event

        It hides the details of:

        * Calling ``events.subscribe`` (when ``subscription_id`` is not
          provided).
        * Establishing and maintaining a WebSocket connection to ``/events``.
        * Parsing ``events.notify`` JSON-RPC envelopes into typed models.
        * Optionally attempting reconnects if the WebSocket drops.

        Parameters
        ----------
        subscription_id:
            Existing subscription identifier returned by ``events.subscribe``.
            When provided, this method will *not* create a new subscription
            and will **not** automatically unsubscribe on exit.

        agent_ids:
            Optional iterable of agent identifiers to subscribe to. Mutually
            exclusive with ``subscription_id``; if you pass ``agent_ids``,
            this helper will first call :meth:`subscribe_events`.

        include_runtime:
            Whether to include runtime-level events when creating a
            subscription via :meth:`subscribe_events`.

        reconnect:
            When ``True`` (the default), the client will attempt to
            transparently reconnect the WebSocket using the same
            ``subscription_id`` if the connection drops unexpectedly.

        reconnect_initial_backoff / reconnect_max_backoff:
            Backoff parameters (in seconds) for reconnection attempts when
            ``reconnect`` is enabled.
        """

        if subscription_id is not None and agent_ids is not None:
            raise ValueError("Provide either subscription_id or agent_ids, not both")

        auto_unsubscribe = subscription_id is None

        if subscription_id is None:
            sub_id = await self.subscribe_events(agent_ids=agent_ids, include_runtime=include_runtime)
        else:
            sub_id = subscription_id

        backoff = float(reconnect_initial_backoff)

        async def _event_loop() -> AsyncIterator[EventsNotify]:
            nonlocal backoff

            while True:
                uri = self._events_ws_uri()
                try:
                    async with websockets.connect(uri) as websocket:
                        # Initial handshake indicates which subscription to attach.
                        handshake = {"subscription_id": sub_id}
                        await websocket.send(json.dumps(handshake))

                        # Reset backoff after a successful connection.
                        backoff = float(reconnect_initial_backoff)

                        while True:
                            raw = await websocket.recv()
                            # ``websocket.recv()`` returns either ``str`` or
                            # ``bytes`` depending on how the frame was sent.
                            if isinstance(raw, bytes):
                                text = raw.decode("utf-8", errors="ignore")
                            else:
                                text = raw

                            try:
                                msg = json.loads(text)
                            except json.JSONDecodeError:  # pragma: no cover - defensive
                                logger.debug("runtime_client_ignored_non_json_frame")
                                continue

                            if msg.get("jsonrpc") != JSONRPC_VERSION:
                                continue
                            if msg.get("method") != "events.notify":
                                continue

                            params = msg.get("params") or {}
                            if str(params.get("subscription_id")) != str(sub_id):
                                # Not for this subscription; ignore.
                                continue

                            event_payload = params.get("event")
                            if not isinstance(event_payload, Mapping):
                                continue

                            try:
                                event_model = AgentDetailEvent.model_validate(event_payload)
                            except ValidationError:  # pragma: no cover - defensive
                                logger.debug("runtime_client_ignored_malformed_event", extra={"payload": event_payload})
                                continue

                            yield EventsNotify(subscription_id=str(sub_id), event=event_model)

                except (WebSocketException, OSError) as exc:
                    logger.warning(
                        "runtime_client_events_ws_disconnected",
                        extra={"error": str(exc)},
                    )
                    if not reconnect:
                        # Surface the disconnection to the caller.
                        raise

                    # Apply simple exponential backoff for reconnect attempts.
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, reconnect_max_backoff)
                    continue

        try:
            async for notification in _event_loop():
                yield notification
        finally:
            if auto_unsubscribe:
                try:
                    await self.unsubscribe_events(sub_id)
                except (JsonRpcClientError, OSError):  # pragma: no cover - best-effort cleanup
                    logger.warning(
                        "runtime_client_unsubscribe_failed",
                        extra={"subscription_id": sub_id},
                    )
