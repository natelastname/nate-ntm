"""JSON-RPC/WebSocket client helper for the runtime control API.

This module provides a small JSON-RPC 2.0 client implemented on top of
:mod:`websockets`. It is intended for use by the Typer-based CLI
(``nate-ntm api call``) and other local tools that need to talk to the
runtime control API described in
``specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md``.

The client intentionally focuses on a very small surface area:

* Connect to a localhost-only WebSocket endpoint.
* Send a single JSON-RPC request object.
* Await and return the corresponding response.

More advanced concerns (connection pooling, streaming helpers for
``events.notify``) can be layered on later without changing this basic
interface.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping

import websockets

from .jsonrpc import JSONRPC_VERSION


class JsonRpcClientError(RuntimeError):
    """Raised when a JSON-RPC error response is returned by the server."""

    def __init__(self, code: int, message: str, data: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.data = dict(data) if data is not None else None
        detail = f"JSON-RPC error {code}: {message}"
        if self.data:
            detail = f"{detail} ({self.data})"
        super().__init__(detail)


@dataclass(slots=True)
class JsonRpcWebSocketClient:
    """Minimal JSON-RPC 2.0 client over WebSockets.

    Parameters
    ----------
    host, port:
        Target host and TCP port for the runtime control API
        WebSocket endpoint. The MVP assumes a localhost-only binding
        (for example, ``127.0.0.1:8765``).

    timeout:
        Optional timeout (in seconds) applied to the initial WebSocket
        connection. A value of ``None`` disables the client-side timeout.
    """

    host: str = "127.0.0.1"
    port: int = 8765
    timeout: float | None = 10.0

    async def call_async(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> Mapping[str, Any]:
        """Perform a single JSON-RPC call and return the full response.

        The returned mapping is the raw JSON-RPC envelope with either a
        ``result`` or an ``error`` key. Callers that prefer exception-based
        error handling can use :meth:`call_for_result` instead.
        """

        uri = f"ws://{self.host}:{self.port}"

        async with websockets.connect(uri, open_timeout=self.timeout) as websocket:
            request = {
                "jsonrpc": JSONRPC_VERSION,
                "method": method,
                "params": params or {},
                "id": request_id,
            }

            await websocket.send(json.dumps(request))
            raw_response = await websocket.recv()
            response = json.loads(raw_response)
            return response

    async def call_for_result(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> Any:
        """Perform a JSON-RPC call and return ``result`` or raise.

        If the server returns an error envelope, this method raises
        :class:`JsonRpcClientError` with the embedded error information.
        """

        response = await self.call_async(method, params, request_id=request_id)

        if "error" in response:
            error = response["error"] or {}
            code = int(error.get("code", -1))
            message = str(error.get("message", "Unknown error"))
            data = error.get("data")
            raise JsonRpcClientError(code=code, message=message, data=data)

        return response.get("result")




@dataclass(slots=True)
class JsonRpcHttpClient:
    """Minimal JSON-RPC 2.0 client over HTTP.

    This client uses the standard library's :mod:`http.client` module
    executed in a background thread via :func:`asyncio.to_thread` so it
    can be safely invoked from within an asyncio event loop without
    blocking it. It targets the unified ``POST /jsonrpc`` endpoint
    exposed by :func:`nate_ntm.api.runtime_api.create_runtime_api_app`.
    """

    host: str = "127.0.0.1"
    port: int = 8765
    timeout: float | None = 10.0

    async def call_async(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> Mapping[str, Any]:
        """Perform a single JSON-RPC call and return the full response.

        The returned mapping is the raw JSON-RPC envelope with either a
        ``result`` or an ``error`` key. Callers that prefer exception-
        based error handling can use :meth:`call_for_result` instead.
        """

        import http.client

        def _do_request() -> Mapping[str, Any]:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            try:
                payload = {
                    "jsonrpc": JSONRPC_VERSION,
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                body = json.dumps(payload).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                conn.request("POST", "/jsonrpc", body, headers)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8")
            finally:
                conn.close()

            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} {resp.reason}: {raw}")

            return json.loads(raw)

        return await asyncio.to_thread(_do_request)

    async def call_for_result(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> Any:
        """Perform a JSON-RPC call and return ``result`` or raise.

        If the server returns an error envelope, this method raises
        :class:`JsonRpcClientError` with the embedded error information.
        """

        response = await self.call_async(method, params, request_id=request_id)

        if "error" in response:
            error = response["error"] or {}
            code = int(error.get("code", -1))
            message = str(error.get("message", "Unknown error"))
            data = error.get("data")
            raise JsonRpcClientError(code=code, message=message, data=data)

        return response.get("result")

def call(method: str, params: Mapping[str, Any] | None = None, *, host: str = "127.0.0.1", port: int = 8765) -> Any:
    """Synchronous helper for one-off CLI-style JSON-RPC calls.

    This is a thin wrapper around :class:`JsonRpcHttpClient` that drives
    the underlying coroutine via :func:`asyncio.run`. It is intended
    primarily for use in simple scripts; higher-level callers are
    encouraged to use :class:`JsonRpcHttpClient` directly.
    """

    client = JsonRpcHttpClient(host=host, port=port)
    return asyncio.run(client.call_for_result(method, params or {}))
