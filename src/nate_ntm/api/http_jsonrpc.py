"""FastAPI/fastapi-jsonrpc application for the runtime control API.

This module provides a ready-to-use ASGI application that exposes the
same JSON-RPC methods as :func:`dispatch_request`, but over HTTP using
``fastapi-jsonrpc`` and ``FastAPI`` under the hood.

Typical usage::

    from nate_ntm.api.http_jsonrpc import create_app
    from nate_ntm.api.server import RuntimeApiServer

    api_server = RuntimeApiServer(daemon=...)  # your RuntimeDaemon
    app = create_app(api_server)

You can then run the app under uvicorn::

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

The individual JSON-RPC methods mirror those implemented by
:func:`nate_ntm.api.jsonrpc.dispatch_request` so that HTTP and WebSocket
transports share a consistent contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi_jsonrpc import API, Entrypoint, BaseError

from .server import RuntimeApiServer

__all__ = ["create_app", "create_entrypoint", "AgentNotFoundError"]


class AgentNotFoundError(BaseError):
    """JSON-RPC error raised when an ``agent_id`` is unknown.

    This mirrors the ``code=1001`` error used by the existing
    :func:`dispatch_request` implementation for ``agent.get_detail``.
    """

    CODE = 1001
    MESSAGE = "Agent not found"


def create_entrypoint(api_server: RuntimeApiServer, path: str = "/rpc") -> Entrypoint:
    """Create a :class:`fastapi_jsonrpc.Entrypoint` bound to ``api_server``.

    The entrypoint exposes the same logical methods as
    :func:`nate_ntm.api.jsonrpc.dispatch_request`:

    * ``runtime.get_status``
    * ``runtime.shutdown``
    * ``swarm.get_overview``
    * ``agent.get_detail``
    * ``events.subscribe``
    * ``events.unsubscribe``
    """

    ep = Entrypoint(path)

    @ep.method(name="runtime.get_status")
    def runtime_get_status() -> Dict[str, Any]:
        """Return high-level runtime status information."""

        return api_server.get_runtime_status()

    @ep.method(name="swarm.get_overview")
    def swarm_get_overview() -> Dict[str, Any]:
        """Return an overview of the swarm and its agents."""

        return api_server.get_swarm_overview()

    @ep.method(name="runtime.shutdown")
    def runtime_shutdown(timeout_seconds: int = 30) -> Dict[str, Any]:
        """Request a graceful runtime shutdown.

        Parameters mirror the ``runtime.shutdown`` JSON-RPC method
        handled by :func:`dispatch_request`.
        """

        return api_server.shutdown_runtime(timeout_seconds=timeout_seconds)

    @ep.method(name="agent.get_detail", errors=[AgentNotFoundError])
    def agent_get_detail(
        agent_id: str,
        max_events: int = 100,
    ) -> Dict[str, Any]:
        """Return detailed state for a single agent.

        Unknown agents are mapped to :class:`AgentNotFoundError` with
        ``code=1001`` to match the existing WebSocket/JSON-RPC
        behaviour.
        """

        try:
            return api_server.get_agent_detail(agent_id=agent_id, max_events=max_events)
        except KeyError:
            raise AgentNotFoundError({"agent_id": agent_id})

    @ep.method(name="events.subscribe")
    def events_subscribe(
        agent_ids: Optional[List[str]] = None,
        include_runtime: bool = True,
    ) -> Dict[str, Any]:
        """Subscribe to :class:`AgentEvent` streams.

        ``agent_ids`` and ``include_runtime`` mirror the parameters of
        the existing ``events.subscribe`` JSON-RPC method.
        """

        return api_server.subscribe_events(
            agent_ids=agent_ids,
            include_runtime=include_runtime,
        )

    @ep.method(name="events.unsubscribe")
    def events_unsubscribe(subscription_id: str) -> Dict[str, Any]:
        """Cancel a previously established event subscription."""

        return api_server.unsubscribe_events(subscription_id)

    return ep


def create_app(api_server: RuntimeApiServer, *, path: str = "/rpc") -> API:
    """Create a :class:`fastapi_jsonrpc.API` exposing the control API.

    The returned object is a fully configured ASGI application that can
    be served by uvicorn or any other ASGI-compatible server.
    """

    api = API(title="nate_ntm runtime HTTP JSON-RPC API")
    entrypoint = create_entrypoint(api_server, path=path)
    api.bind_entrypoint(entrypoint)
    return api
