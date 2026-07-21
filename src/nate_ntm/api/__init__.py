"""Command-only runtime control API.

The package exposes a single FastAPI JSON-RPC endpoint for runtime status,
swarm inspection, agent detail, and shutdown. Live agent output is carried by
ACP rather than a parallel control-API event system.
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
