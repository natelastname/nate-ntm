"""Runtime control API server skeleton.

For Phase 2 (T011), this module provides a very small abstraction over
an eventual WebSocket JSON-RPC server. The goal is to pin down the
in-process surface that the runtime daemon and CLI will rely on without
binding to a specific async server implementation yet.

A minimal `RuntimeApiServer` class is provided with stubbed methods that
can be expanded in later tasks (for example T018 and T019).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from ..runtime.daemon import RuntimeDaemon

__all__ = ["RuntimeApiServer", "SupportsRuntimeDaemon"]


class SupportsRuntimeDaemon(Protocol):
    """Protocol capturing the subset of RuntimeDaemon used by the API.

    This keeps the server layer decoupled from the concrete daemon
    implementation while still enabling type checking.
    """

    @property
    def daemon(self) -> RuntimeDaemon:  # pragma: no cover - structural only
        ...


@dataclass(slots=True)
class RuntimeApiServer:
    """Skeleton for the runtime control API server (T011).

    The eventual implementation will:

    * Own an async WebSocket server bound to localhost.
    * Accept JSON-RPC requests and dispatch them to the
      :class:`RuntimeDaemon`.
    * Expose high-level `start`/`stop` methods and
      request/notification handlers.

    For now, we only capture the association with a `RuntimeDaemon`.
    """

    daemon: RuntimeDaemon

    def start(self) -> None:
        """Start accepting API connections (stub).

        The actual implementation will be async and will integrate with
        the runtime event loop.
        """

        # Stub: nothing to do yet.
        return

    def stop(self) -> None:
        """Stop the API server and release any resources (stub)."""

        # Stub: nothing to do yet.
        return
