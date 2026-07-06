"""Public API surface for the nate_ntm runtime control layer.

This package hosts the localhost-only control API server and any
client helpers used by CLIs, TUIs, or web frontends.

The primary entrypoint is a unified FastAPI application created by
``create_runtime_api_app``, which exposes:

* ``POST /jsonrpc``
    HTTP JSON-RPC 2.0 endpoint for ``runtime.*``, ``swarm.*``,
    ``agent.*``, and ``events.*`` commands.
* ``WS   /events``
    WebSocket endpoint that streams JSON-RPC-style ``events.notify``
    notifications for subscribed clients.

See ``specs/001-swarm-runtime-orchestrator/contracts/`` for the runtime
API contracts.
"""

from __future__ import annotations

from .runtime_api import AgentNotFoundError, RuntimeStateConflictError, create_runtime_api_app
from .server import RuntimeApiServer

__all__ = [
    "RuntimeApiServer",
    "create_runtime_api_app",
    "AgentNotFoundError",
    "RuntimeStateConflictError",
]
