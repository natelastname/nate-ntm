"""OpenHands ACP client adapter for the swarm runtime (T015).

The nate_ntm runtime owns all ACP (Agent Control Protocol) connections
for agents in a swarm. This module defines a small adapter interface
that the runtime and scheduler use to interact with an OpenHands server.

For the MVP and tests we rely on :class:`FakeAcpClient`, an in-memory
implementation that simulates conversations and turn identifiers without
performing any network I/O. A real ACP client that speaks HTTP/WebSocket
or another transport to an OpenHands server can be implemented later on
this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from ..config.runtime_config import RuntimeConfig

__all__ = ["AcpClientError", "BaseAcpClient", "FakeAcpClient"]


class AcpClientError(RuntimeError):
    """Base error type for ACP adapter failures."""


class BaseAcpClient:
    """Abstract interface for the OpenHands ACP client.

    The interface is intentionally lean for the MVP:

    * Ensure a control-protocol conversation exists per agent.
    * Optionally, start new turns within that conversation and surface
      identifiers back to the runtime.

    Concrete implementations are expected to be **runtime-owned** and
    reused for the lifetime of the process.
    """

    # The following methods define the public contract. Concrete
    # implementations *must* override them.

    def ensure_conversation(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Ensure a control-protocol conversation exists for ``agent_id``.

        The returned string is an opaque conversation identifier. The
        method must be **idempotent**: repeated calls for the same
        ``agent_id`` MUST return the same conversation ID.
        """

        raise NotImplementedError

    def start_turn(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Start a new ACP turn for ``agent_id`` and return its ID.

        The exact semantics of a "turn" are defined by the ACP spec and
        the concrete implementation. The fake client simply allocates a
        monotonically increasing identifier per agent.
        """

        raise NotImplementedError


@dataclass(slots=True)
class FakeAcpClient(BaseAcpClient):
    """In-memory ACP client for tests and dev-mode.

    This implementation does **not** perform any network I/O. It keeps
    a minimal in-memory model of:

    * A per-agent conversation identifier.
    * A monotonically increasing counter of turn IDs per agent.

    It is sufficient for unit tests and early integration tests that
    need stable, realistic-looking conversation and turn identifiers
    without talking to a real OpenHands server.
    """

    config: RuntimeConfig

    _conversations: Dict[str, str] = field(default_factory=dict)
    _turn_counters: Dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # BaseAcpClient API
    # ------------------------------------------------------------------

    def ensure_conversation(self, agent_id: str) -> str:
        if agent_id in self._conversations:
            return self._conversations[agent_id]

        # Derive a deterministic, human-readable conversation identifier.
        conv_id = f"fake-conversation:{agent_id}"
        self._conversations[agent_id] = conv_id
        return conv_id

    def start_turn(self, agent_id: str) -> str:
        # Ensure a conversation exists; many callers will already have
        # done this explicitly but the helper is cheap and idempotent.
        self.ensure_conversation(agent_id)

        counter = self._turn_counters.get(agent_id, 0) + 1
        self._turn_counters[agent_id] = counter
        turn_id = f"fake-turn:{agent_id}:{counter}"
        return turn_id
