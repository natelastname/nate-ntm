"""WebSocket JSON-RPC server for the runtime control API.

This module provides a small asyncio-based WebSocket server that exposes
:class:`RuntimeApiServer` over a localhost-only JSON-RPC 2.0 interface,
matching the contract in
``specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md``.

Key responsibilities:

* Accept incoming WebSocket connections from local clients.
* Receive JSON-RPC request objects and dispatch them via
  :func:`nate_ntm.api.jsonrpc.dispatch_request`.
* Send JSON-RPC responses back to the client.
* Track ``events.subscribe`` / ``events.unsubscribe`` requests so that
  live :class:`~nate_ntm.runtime.events.AgentEvent` instances can be
  fanned out as ``events.notify`` notifications using
  :func:`nate_ntm.api.jsonrpc.build_events_notify_messages`.

Transport and lifetime management are deliberately minimal; the CLI and
runtime daemon are expected to own this server instance and its event
loop in future phases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

import websockets
from websockets.legacy.server import WebSocketServerProtocol

from .jsonrpc import JSONRPC_VERSION, build_events_notify_messages, dispatch_request
from .server import RuntimeApiServer

__all__ = ["JsonRpcWebSocketServer"]


def _make_error_response(
    *, code: int, message: str, response_id: Any | None = None, data: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Build a JSON-RPC error envelope.

    This mirrors the structure used by :mod:`nate_ntm.api.jsonrpc` for
    consistency but is kept local to avoid exposing additional helpers
    from that module.
    """

    error: Dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data

    return {"jsonrpc": JSONRPC_VERSION, "error": error, "id": response_id}


@dataclass(slots=True)
class JsonRpcWebSocketServer:
    """Async WebSocket JSON-RPC server bound to a :class:`RuntimeApiServer`.

    Parameters
    ----------
    api_server:
        The in-process :class:`RuntimeApiServer` instance that implements
        the control API handlers.

    host, port:
        Bind address for the WebSocket server. The MVP assumes a
        localhost-only binding; passing ``port=0`` allows the OS to pick
        an ephemeral port (useful in tests).
    """

    api_server: RuntimeApiServer
    host: str = "127.0.0.1"
    port: int = 0

    _ws_server: websockets.server.WebSocketServer | None = field(default=None, init=False, repr=False)

    # Mapping from subscription_id -> WebSocket connection and the
    # inverse mapping from connection -> set[subscription_id]. These are
    # used to route ``events.notify`` notifications to the correct
    # clients.
    _subscription_clients: Dict[str, WebSocketServerProtocol] = field(
        default_factory=dict, init=False, repr=False
    )
    _client_subscriptions: Dict[WebSocketServerProtocol, set[str]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def start(self) -> None:
        """Start the WebSocket server.

        This coroutine binds the listening socket but does not block the
        event loop indefinitely. Callers are responsible for running the
        event loop (for example via :func:`asyncio.run`).
        """

        self._ws_server = await websockets.serve(self._handle_client, self.host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server and close all active connections."""

        server = self._ws_server
        self._ws_server = None

        if server is not None:
            server.close()
            await server.wait_closed()

        # Clear subscription tracking state.
        self._subscription_clients.clear()
        self._client_subscriptions.clear()

    @property
    def bound_port(self) -> int:
        """Return the effective TCP port the server is bound to.

        When ``port=0`` was passed to the constructor, this inspects the
        underlying listening socket to discover the OS-assigned
        ephemeral port. Otherwise it simply returns the configured port.
        """

        if self._ws_server is None:
            return self.port

        sockets = getattr(self._ws_server, "sockets", None)
        if not sockets:
            return self.port

        sock = sockets[0]
        return int(sock.getsockname()[1])

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Per-connection handler for JSON-RPC messages.

        The current implementation is deliberately simple:

        * Each received text message is parsed as JSON.
        * Valid JSON-RPC request objects are dispatched via
          :func:`dispatch_request`.
        * Responses are sent back on the same WebSocket.
        * ``events.subscribe`` / ``events.unsubscribe`` calls update the
          subscription-to-connection mappings used by
          :meth:`publish_event`.
        """

        try:
            async for raw_message in websocket:
                try:
                    request = json.loads(raw_message)
                except json.JSONDecodeError:
                    error = _make_error_response(
                        code=1000,
                        message="Invalid JSON payload",
                        response_id=None,
                    )
                    await websocket.send(json.dumps(error))
                    continue

                if not isinstance(request, Mapping):
                    error = _make_error_response(
                        code=1000,
                        message="Request must be a JSON object",
                        response_id=request.get("id") if isinstance(request, dict) else None,
                    )
                    await websocket.send(json.dumps(error))
                    continue

                method = request.get("method")
                response = dispatch_request(self.api_server, request)

                # Track subscriptions based on the JSON-RPC method.
                if method == "events.subscribe" and "result" in response:
                    sub_id = response["result"].get("subscription_id")
                    if isinstance(sub_id, str):
                        self._subscription_clients[sub_id] = websocket
                        self._client_subscriptions.setdefault(websocket, set()).add(sub_id)
                elif method == "events.unsubscribe" and "result" in response:
                    params = request.get("params") or {}
                    sub_id_val = params.get("subscription_id")
                    if isinstance(sub_id_val, str):
                        self._subscription_clients.pop(sub_id_val, None)
                        subs = self._client_subscriptions.get(websocket)
                        if subs is not None:
                            subs.discard(sub_id_val)

                await websocket.send(json.dumps(response))
        finally:
            await self._cleanup_client(websocket)

    async def _cleanup_client(self, websocket: WebSocketServerProtocol) -> None:
        """Remove all subscriptions associated with a disconnected client."""

        subs = self._client_subscriptions.pop(websocket, set())
        for sub_id in subs:
            self._subscription_clients.pop(sub_id, None)
            # Keep the in-process subscription registry tidy as well.
            self.api_server.unsubscribe_events(sub_id)

    async def publish_event(self, event: "AgentEvent") -> None:  # pragma: no cover - covered via tests
        """Publish a single :class:`AgentEvent` to matching subscribers.

        This is a thin async wrapper around
        :func:`build_events_notify_messages`. It looks up the owning
        WebSocket connection for each subscription and sends a
        JSON-RPC 2.0 ``events.notify`` notification frame.
        """

        from ..runtime.events import AgentEvent as _AgentEvent

        if not isinstance(event, _AgentEvent):
            raise TypeError("publish_event expects an AgentEvent instance")

        messages = build_events_notify_messages(self.api_server, event)

        # Send each notification to the WebSocket associated with its
        # subscription, if still connected.
        for msg in messages:
            params = msg.get("params") or {}
            sub_id = params.get("subscription_id")
            if not isinstance(sub_id, str):
                continue

            ws = self._subscription_clients.get(sub_id)
            if ws is None:
                continue

            await ws.send(json.dumps(msg))
