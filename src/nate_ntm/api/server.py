"""Runtime control API server skeleton.

For Phase 2 (T011), this module provides a very small abstraction over
an eventual WebSocket JSON-RPC server. The goal is to pin down the
in-process surface that the runtime daemon and CLI will rely on without
binding to a specific async server implementation yet.

A minimal `RuntimeApiServer` class is provided with stubbed methods that
can be expanded in later tasks (for example T018 and T019).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol

from ..runtime.daemon import RuntimeDaemon
from ..runtime.events import AgentEvent
from ..runtime.state import RuntimeStatus

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

    For now, we only capture the association with a `RuntimeDaemon` and a
    minimal in-memory subscription registry for event streaming.
    """

    daemon: RuntimeDaemon

    # Internal subscription registry for ``events.subscribe``/``events.unsubscribe``.
    _subscriptions: Dict[str, Dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _next_subscription_id: int = field(default=1, init=False, repr=False)

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

    # Handlers -----------------------------------------------------------

    def get_runtime_status(self) -> Dict[str, Any]:
        """Return high-level runtime status for ``runtime.get_status``.

        For the MVP this is a thin wrapper over the
        :class:`RuntimeDaemon` introspection APIs. JSON-RPC wiring and
        WebSocket transport are added in later tasks.
        """

        return self.daemon.get_runtime_status()

    def get_swarm_overview(self) -> Dict[str, Any]:
        """Return swarm overview data for ``swarm.get_overview``.

        This mirrors the result shape defined in
        ``contracts/runtime-api.md`` by delegating to the
        :class:`RuntimeDaemon`.
        """

        return self.daemon.get_swarm_overview()

    def shutdown_runtime(self, timeout_seconds: int = 30) -> Dict[str, Any]:
        """Request a graceful runtime shutdown for ``runtime.shutdown``.

        This mirrors the high-level contract in
        ``specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md`` by
        delegating to :meth:`RuntimeDaemon.request_shutdown` and returning a
        small acknowledgement payload.

        In the eventual JSON-RPC/WebSocket layer this result will be mapped
        to a structured response object or error.
        """

        if self.daemon.state.status is not RuntimeStatus.RUNNING:
            raise RuntimeError(
                f"Cannot shutdown runtime from status "
                f"{self.daemon.state.status.value!r}"
            )

        self.daemon.request_shutdown()

        return {
            "accepted": True,
            "status": self.daemon.state.status.value,
        }

    def subscribe_events(
        self,
        *,
        agent_ids: list[str] | None = None,
        include_runtime: bool = True,
    ) -> Dict[str, Any]:
        """Register an event subscription for ``events.subscribe``.

        This is a minimal, in-memory subscription registry suitable for the
        MVP. The eventual WebSocket/JSON-RPC layer will call this method
        when handling ``events.subscribe`` requests and map the returned
        ``subscription_id`` onto a specific client connection.
        """

        if agent_ids is None:
            agent_ids = []

        subscription_id = f"sub-{self._next_subscription_id:03d}"
        self._next_subscription_id += 1

        # Store a small descriptor for future routing; concrete notification
        # delivery is added alongside the WebSocket server.
        self._subscriptions[subscription_id] = {
            "agent_ids": tuple(agent_ids),
            "include_runtime": bool(include_runtime),
        }

        return {"subscription_id": subscription_id}

    def unsubscribe_events(self, subscription_id: str) -> Dict[str, Any]:
        """Terminate a subscription for ``events.unsubscribe``.

        This is intentionally idempotent: attempting to unsubscribe an
        unknown ``subscription_id`` still returns ``{\"unsubscribed\": true}``.
        """

        self._subscriptions.pop(subscription_id, None)
        return {"unsubscribed": True}

    # ------------------------------------------------------------------
    # Event routing helpers
    # ------------------------------------------------------------------

    def build_agent_event_notifications(self, event: AgentEvent) -> Dict[str, Any]:
        """Build notification payloads for an :class:`AgentEvent`.

        This is a small, in-process helper that applies the current
        subscription filters to a single agent-scoped event and returns a
        JSON-serializable structure mirroring the ``events.notify``
        contract:

        .. code-block:: json

            {
              "notifications": [
                {
                  "subscription_id": "sub-001",
                  "event": { ... AgentEvent.to_dict() ... }
                },
                ...
              ]
            }

        The actual WebSocket/JSON-RPC layer will take this payload and
        fan it out to connected clients.
        """

        event_payload = event.to_dict()
        notifications: list[Dict[str, Any]] = []

        for subscription_id, desc in self._subscriptions.items():
            agent_ids = desc.get("agent_ids") or ()

            # Empty ``agent_ids`` means "all agents".
            if agent_ids and event.agent_id not in agent_ids:
                continue

            notifications.append(
                {
                    "subscription_id": subscription_id,
                    "event": event_payload,
                }
            )

        return {"notifications": notifications}



    def get_agent_detail(self, agent_id: str, max_events: int = 100) -> Dict[str, Any]:
        """Return detailed information for a single agent.

        This corresponds to the ``agent.get_detail`` method in
        ``contracts/runtime-api.md`` and delegates to the
        :class:`RuntimeDaemon` for its implementation.
        """

        return self.daemon.get_agent_detail(agent_id=agent_id, max_events=max_events)
