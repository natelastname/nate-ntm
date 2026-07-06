"""JSON-RPC client helpers for the runtime control API.

This module provides a small JSON-RPC 2.0 client implemented on top of
the standard library's :mod:`http.client`. It is intended for use by the
Typer-based CLI (``nate-ntm api call``) and other local tools that need
to talk to the runtime control API exposed by the unified FastAPI app
(``POST /jsonrpc``) in :mod:`nate_ntm.api.runtime_api`.

The client intentionally focuses on a very small surface area:

* Send a single JSON-RPC request object over HTTP.
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

from .jsonrpc import JSONRPC_VERSION
from .models import AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult


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

    async def get_runtime_status(self) -> RuntimeStatusResult:
        """Typed helper for ``runtime.get_status``.

        This method performs a JSON-RPC call and validates the ``result``
        payload against :class:`RuntimeStatusResult`, raising
        :class:`JsonRpcClientError` on JSON-RPC errors and
        :class:`pydantic.ValidationError` if the server returns an
        unexpected shape.
        """

        payload = await self.call_for_result("runtime.get_status", {})
        return RuntimeStatusResult.model_validate(payload)

    async def get_swarm_overview(self) -> SwarmOverviewResult:
        """Typed helper for ``swarm.get_overview``."""

        payload = await self.call_for_result("swarm.get_overview", {})
        return SwarmOverviewResult.model_validate(payload)

    async def get_agent_detail(
        self,
        agent_id: str,
        max_events: int = 100,
    ) -> AgentDetailResult:
        """Typed helper for ``agent.get_detail``.

        Parameters are forwarded as JSON-RPC params; the resulting
        payload is validated against :class:`AgentDetailResult`.
        """

        params: Mapping[str, Any] = {"agent_id": agent_id, "max_events": max_events}
        payload = await self.call_for_result("agent.get_detail", params)
        return AgentDetailResult.model_validate(payload)

def call(method: str, params: Mapping[str, Any] | None = None, *, host: str = "127.0.0.1", port: int = 8765) -> Any:
    """Synchronous helper for one-off CLI-style JSON-RPC calls.

    This is a thin wrapper around :class:`JsonRpcHttpClient` that drives
    the underlying coroutine via :func:`asyncio.run`. It is intended
    primarily for use in simple scripts; higher-level callers are
    encouraged to use :class:`JsonRpcHttpClient` directly.
    """

    client = JsonRpcHttpClient(host=host, port=port)
    return asyncio.run(client.call_for_result(method, params or {}))
