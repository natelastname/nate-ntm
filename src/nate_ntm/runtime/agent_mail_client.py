"""Agent Mail coordination adapter for the swarm runtime (T014).

This module defines a small, runtime-owned abstraction for interacting
with an Agent Mail coordination service. The *real* implementation that
speaks to a running Agent Mail server (for example via the
``mcp_agent_mail`` package) will be layered on later.

For the MVP and unit/integration tests we provide
:class:`FakeAgentMailClient`, an in-memory implementation that simulates
Agent Mail projects, per-agent identities, and unread-mail flags without
performing any network I/O. This keeps the runtime core testable and
allows higher layers (daemon, scheduler, API) to depend on a narrow
interface regardless of the underlying transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable

from ..config.runtime_config import RuntimeConfig

__all__ = ["AgentMailClientError", "BaseAgentMailClient", "FakeAgentMailClient"]


class AgentMailClientError(RuntimeError):
    """Base error type for Agent Mail adapter failures.

    In the real adapter this will be used to wrap lower-level
    network/HTTP/MCP exceptions so that callers can handle all
    integration failures in a uniform way. The fake client used in
    tests generally does not raise this error.
    """


class BaseAgentMailClient:
    """Abstract interface for Agent Mail coordination.

    Implementations are expected to be **runtime-owned**: a
    :class:`~nate_ntm.runtime.daemon.RuntimeDaemon` (or tests) should
    construct an adapter instance and reuse it for the lifetime of the
    process.

    The interface is intentionally small and focused on the needs of the
    runtime:

    * Create or reuse a *project-level* Agent Mail identifier for the
      swarm.
    * Create or reuse *per-agent* identities within that project.
    * Report whether agents currently have unread mail so that
      ``swarm.get_overview`` and related APIs can expose a
      ``has_unread_mail`` flag.
    """

    # The following methods define the public contract. Concrete
    # implementations *must* override them.

    def ensure_project(self) -> str:  # pragma: no cover - abstract
        """Ensure an Agent Mail project exists for this swarm.

        The returned string is an opaque identifier understood by the
        backing Agent Mail service. Implementations must be **idempotent**:
        repeated calls for the same runtime configuration MUST return the
        same project identifier.
        """

        raise NotImplementedError

    def ensure_agent_identity(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Ensure an Agent Mail identity exists for ``agent_id``.

        The returned string is an opaque identifier representing the
        agent within the Agent Mail project. Implementations must be
        **idempotent** per agent: calling this multiple times for the
        same ``agent_id`` MUST return the same identity string.
        """

        raise NotImplementedError

    def get_unread_mail_flags(self, agent_ids: Iterable[str]) -> Dict[str, bool]:  # pragma: no cover - abstract
        """Return a mapping of ``agent_id`` to ``has_unread_mail``.

        Implementations should treat unknown agents conservatively as not
        having unread mail (``False``) unless they have a strong reason
        to do otherwise.
        """

        raise NotImplementedError


@dataclass(slots=True)
class FakeAgentMailClient(BaseAgentMailClient):
    """In-memory Agent Mail adapter for tests and dev-mode.

    This implementation performs **no external I/O**. Instead it keeps a
    small in-memory model of a single project and a set of per-agent
    identities/unread-mail flags:

    * The project identifier is derived deterministically from the
      runtime configuration (``swarm_id`` and project path) so that
      tests can make assertions about its value.
    * Agent identities are simple, stable strings derived from the
      ``agent_id``.
    * Unread-mail information is represented as integer counts per agent
      and exposed to callers as boolean flags.

    The goal is to provide realistic-enough behavior for unit and
    integration tests without constraining the eventual real adapter.
    """

    config: RuntimeConfig

    # Internal state: a single project identifier plus per-agent
    # identities and unread counts. These are kept simple and fully
    # in-memory; they are not persisted across runs.
    _project_id: str | None = None
    _agent_identities: Dict[str, str] = field(default_factory=dict)
    _unread_counts: Dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # BaseAgentMailClient API
    # ------------------------------------------------------------------

    def ensure_project(self) -> str:
        if self._project_id is None:
            # Derive a deterministic, human-readable identifier that is
            # unique per project path + swarm ID in typical usage. This
            # is *not* meant to be globally unique; it is purely for
            # dev/test scenarios.
            project_path = str(self.config.project_path)
            self._project_id = f"fake-mail-project:{self.config.swarm_id}:{project_path}"
        return self._project_id

    def ensure_agent_identity(self, agent_id: str) -> str:
        if agent_id in self._agent_identities:
            return self._agent_identities[agent_id]

        # In a real implementation this would call into Agent Mail to
        # create or look up an identity. For tests we synthesize a stable
        # string that is unique per agent within the project.
        identity = f"fake-mail-identity:{agent_id}"
        self._agent_identities[agent_id] = identity
        return identity

    def get_unread_mail_flags(self, agent_ids: Iterable[str]) -> Dict[str, bool]:
        # Unknown agents default to having no unread mail.
        return {agent_id: self._unread_counts.get(agent_id, 0) > 0 for agent_id in agent_ids}

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def set_unread_count_for_test(self, agent_id: str, count: int) -> None:
        """Override the unread-mail count for ``agent_id``.

        This helper exists specifically for tests that want to simulate
        unread mail for particular agents without involving a real Agent
        Mail service. A non-positive ``count`` clears the unread
        indicator.
        """

        if count > 0:
            self._unread_counts[agent_id] = count
        else:
            self._unread_counts.pop(agent_id, None)
