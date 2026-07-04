"""Runtime integration adapter selection and construction (T100).

This module centralizes the logic for selecting and constructing the
runtime-owned integration adapters used by :class:`RuntimeDaemon` and
related helpers. It provides a small dependency-injection boundary so
that the daemon and scheduler can depend on the abstract adapter
interfaces without needing to know which concrete implementations are in
use for a given run.

For T100 and the US1–US3 baseline we primarily support the in-memory
"fake" adapters used in dev-mode and tests. As Phase 6 tasks land, the
``"real"`` adapter kind is being wired up to production-ready
implementations. At this stage (T101/T102) both the Agent Mail and ACP
adapters have real implementations available in addition to their fake
counterparts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.runtime_config import AdapterKind, RuntimeConfig
from .acp_client import BaseAcpClient, FakeAcpClient, OpenHandsAcpClient
from .agent_mail_client import BaseAgentMailClient, FakeAgentMailClient, McpAgentMailClient

__all__ = ["RuntimeAdapters", "create_runtime_adapters"]


@dataclass(slots=True)
class RuntimeAdapters:
    """Bundle of concrete adapter instances owned by a runtime.

    A :class:`RuntimeDaemon` treats this as a simple container of the
    adapter implementations it should use for a given run. Callers are
    expected to construct one :class:`RuntimeAdapters` per process (or
    per logical runtime instance) and reuse it for the lifetime of that
    runtime.
    """

    agent_mail: BaseAgentMailClient
    """Adapter used for Agent Mail coordination."""

    acp: BaseAcpClient
    """Adapter used for OpenHands ACP interactions."""


def _select_adapter_kind(global_mode: AdapterKind, specific: AdapterKind | None) -> AdapterKind:
    """Return the effective adapter kind for an integration.

    ``specific`` (for example, :attr:`RuntimeConfig.agent_mail_adapter`)
    takes precedence when not ``None``; otherwise ``global_mode`` (for
    example, :attr:`RuntimeConfig.adapter_mode`) is used.
    """

    return specific or global_mode


def create_runtime_adapters(config: RuntimeConfig) -> RuntimeAdapters:
    """Construct :class:`RuntimeAdapters` for ``config``.

    This helper inspects the adapter selection fields on ``config`` and
    constructs the appropriate concrete adapter implementations. For the
    T100/T101/T102 baseline the ``AdapterKind.FAKE`` branch is implemented
    for both Agent Mail and ACP, and ``AdapterKind.REAL`` is implemented
    for both integrations as well.
    """

    mail_kind = _select_adapter_kind(config.adapter_mode, config.agent_mail_adapter)
    acp_kind = _select_adapter_kind(config.adapter_mode, config.acp_adapter)

    # Agent Mail adapter -------------------------------------------------
    if mail_kind is AdapterKind.FAKE:
        agent_mail: BaseAgentMailClient = FakeAgentMailClient(config=config)
    elif mail_kind is AdapterKind.REAL:
        agent_mail = McpAgentMailClient(config=config)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported Agent Mail adapter kind: {mail_kind!r}")

    # ACP adapter --------------------------------------------------------
    if acp_kind is AdapterKind.FAKE:
        acp: BaseAcpClient = FakeAcpClient(config=config)
    elif acp_kind is AdapterKind.REAL:
        acp = OpenHandsAcpClient(config=config)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported ACP adapter kind: {acp_kind!r}")

    return RuntimeAdapters(agent_mail=agent_mail, acp=acp)
