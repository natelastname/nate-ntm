from __future__ import annotations

"""Shared widgets for the Textual runtime console.

These widgets are presentation-only and consume state from a
:class:`~nate_ntm.tui.runtime_session.RuntimeSession` instance provided by the
application. They must not import or depend on :class:`RuntimeClient`,
:class:`JsonRpcHttpClient`, WebSocket primitives, or runtime internals.
"""

from .swarm_summary import SwarmSummary
from .agent_table import AgentTable
from .event_view import EventView

__all__ = ["SwarmSummary", "AgentTable", "EventView"]
