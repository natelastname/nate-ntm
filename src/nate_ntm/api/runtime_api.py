"""Unified FastAPI JSON-RPC runtime control API."""

from __future__ import annotations

from typing import Any

from fastapi_jsonrpc import API, BaseError, Entrypoint

from .models import (
    AgentDetailResult,
    RuntimeStatusResult,
    SwarmOverviewResult,
)
from .server import RuntimeApiServer

__all__ = ["create_runtime_api_app", "AgentNotFoundError", "RuntimeStateConflictError"]


class AgentNotFoundError(BaseError):
    CODE = 1001
    MESSAGE = "Agent not found"


class RuntimeStateConflictError(BaseError):
    CODE = 1100
    MESSAGE = "Runtime state conflict"


def _create_entrypoint(
    api_server: RuntimeApiServer,
    path: str = "/jsonrpc",
) -> Entrypoint:
    entrypoint = Entrypoint(path)

    @entrypoint.method(name="runtime.get_status")
    def runtime_get_status() -> RuntimeStatusResult:
        return RuntimeStatusResult.model_validate(api_server.get_runtime_status())

    @entrypoint.method(name="swarm.get_overview")
    def swarm_get_overview() -> SwarmOverviewResult:
        return SwarmOverviewResult.model_validate(api_server.get_swarm_overview())

    @entrypoint.method(name="runtime.shutdown", errors=[RuntimeStateConflictError])
    def runtime_shutdown(timeout_seconds: int = 30) -> dict[str, Any]:
        try:
            return api_server.shutdown_runtime(timeout_seconds=timeout_seconds)
        except RuntimeError as exc:
            raise RuntimeStateConflictError({"detail": str(exc)})

    @entrypoint.method(name="agent.get_detail", errors=[AgentNotFoundError])
    def agent_get_detail(agent_id: str) -> AgentDetailResult:
        try:
            payload = api_server.get_agent_detail(agent_id=agent_id)
        except KeyError:
            raise AgentNotFoundError({"agent_id": agent_id})
        return AgentDetailResult.model_validate(payload)

    return entrypoint


def create_runtime_api_app(api_server: RuntimeApiServer) -> API:
    """Create the command-only runtime API.

    Live agent output is exposed exclusively through ACP. The control API has
    no event subscriptions, event notifications, or WebSocket event endpoint.
    """

    app = API(title="nate_ntm runtime control API")
    app.bind_entrypoint(_create_entrypoint(api_server))
    return app
