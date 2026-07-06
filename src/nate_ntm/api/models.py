from __future__ import annotations

"""Shared Pydantic models for the runtime control API surface.

These models represent the **JSON-RPC wire-level result shapes** for the
primary runtime control methods:

* ``runtime.get_status``
* ``swarm.get_overview``
* ``agent.get_detail``

They are treated as the single source of truth for the control API
contract and are reused across:

* the FastAPI/JSON-RPC server (``nate_ntm.api.runtime_api``),
* the HTTP JSON-RPC client helpers (``nate_ntm.api.client.JsonRpcHttpClient``),
* the ``nate-ntm api call`` CLI output normalisation, and
* unit tests that assert response shapes.

If you add or evolve JSON-RPC methods that return structured payloads,
prefer to extend this module so that server, client, and CLI code all
share the same schema.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

__all__ = [
    "AgentCounts",
    "RuntimeStatusResult",
    "AgentOverview",
    "SwarmOverviewResult",
    "AgentDetailAgent",
    "AgentDetailEvent",
    "AgentDetailResult",
]


class AgentCounts(BaseModel):
    """Aggregated agent count metrics used in multiple API results."""

    total: int
    starting: int
    idle: int
    running: int
    waiting: int
    failed: int


class RuntimeStatusResult(BaseModel):
    """Result payload for ``runtime.get_status``.

    This mirrors the dictionary-based shape returned by
    :meth:`RuntimeDaemon.get_runtime_status` and exposed both via the
    legacy JSON-RPC dispatcher and the unified FastAPI/JSON-RPC app.
    """

    status: str
    project_path: str
    swarm_id: str
    agent_counts: AgentCounts


class AgentOverview(BaseModel):
    """Per-agent summary entry for ``swarm.get_overview`` results."""

    agent_id: str
    display_name: str
    status: str
    has_unread_mail: bool
    last_error: Optional[str] = None


class SwarmOverviewResult(BaseModel):
    """Result payload for ``swarm.get_overview``.

    The field names and nested structure are aligned with the
    dictionaries produced by :meth:`RuntimeDaemon.get_swarm_overview`
    so that the JSON wire format remains stable while the FastAPI
    layer uses typed models internally.
    """

    swarm_id: str
    project_path: str
    runtime_status: str
    agent_counts: AgentCounts
    agents: List[AgentOverview]


class AgentDetailAgent(BaseModel):
    """Nested ``agent`` object in ``agent.get_detail`` results."""

    agent_id: str
    display_name: str
    status: str
    agent_mail_identity: str
    conversation_id: str
    last_error: Optional[str] = None


class AgentDetailEvent(BaseModel):
    """Event entries in ``agent.get_detail`` results.

    These mirror the dictionaries returned by
    :meth:`nate_ntm.runtime.events.AgentEvent.to_dict`. The ``timestamp``
    is represented as a plain string here to avoid any implicit
    timezone or formatting changes when models are (de-)serialized.
    """

    event_id: str
    timestamp: str
    agent_id: str
    source: str
    type: str
    payload: Dict[str, Any]


class AgentDetailResult(BaseModel):
    """Result payload for ``agent.get_detail``.

    The top-level structure is ``{"agent": {...}, "events": [...]}``
    to match the existing JSON-RPC contract.
    """

    agent: AgentDetailAgent
    events: List[AgentDetailEvent]
