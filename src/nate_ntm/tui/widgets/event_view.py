from __future__ import annotations

"""Live event view widget.

This widget renders a simple, scroll-free view of the most recent events from
a :class:`~nate_ntm.tui.runtime_session.RuntimeSession` instance.

For this initial slice the widget simply lists recent events in reverse
chronological order (newest last in the buffer) with minimal formatting.
"""

from typing import Any

from textual.widgets import Static

from nate_ntm.tui.runtime_session import RuntimeSession


class EventView(Static):
    """Render a small, bounded list of recent runtime/agent events."""

    def __init__(self, session: RuntimeSession, limit: int = 50, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._limit = int(limit)

    @property
    def session(self) -> RuntimeSession:
        """Return the associated :class:`RuntimeSession`."""

        return self._session

    def render(self) -> str:  # pragma: no cover - exercised through Textual rendering
        events = self._session.get_recent_events(limit=self._limit)

        if not events:
            return "Events: (none yet)"

        lines: list[str] = ["Events (most recent first):"]

        for event in events:
            # The AgentDetailEvent model exposes agent_id, event_type, and
            # created_at (timestamp) fields among others.
            created = getattr(event, "created_at", None)
            created_str = created.isoformat() if created is not None else "?"
            agent_id = getattr(event, "agent_id", "-")
            event_type = getattr(event, "event_type", "-")
            lines.append(
                f"  - {created_str}  agent={agent_id}  type={event_type}"
            )

        return "\n".join(lines)
