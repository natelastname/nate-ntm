from __future__ import annotations

"""Simple agent table widget.

The initial implementation renders a textual list of agents using cached swarm
overview data from :class:`~nate_ntm.tui.runtime_session.RuntimeSession`.

Interactivity (selection, keyboard navigation) will be added in later
iterations; for now this widget is read-only and provides a basic overview of
agents and their latest-known states.
"""

from typing import Any

from textual.widgets import Static

from nate_ntm.tui.runtime_session import RuntimeSession


class AgentTable(Static):
    """Render a simple table of agents based on cached overview data."""

    def __init__(self, session: RuntimeSession, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session = session

    @property
    def session(self) -> RuntimeSession:
        """Return the associated :class:`RuntimeSession`."""

        return self._session

    def render(self) -> str:  # pragma: no cover - exercised through Textual rendering
        overview = self._session.get_cached_swarm_overview()

        if overview is None:
            return "Agents: (overview not yet available)"

        if not overview.agents:
            return "Agents: (none)"

        lines: list[str] = ["Agents:"]

        for agent in overview.agents:
            # Agent overview entries include id, display_name, and status
            display_name = agent.display_name or agent.agent_id
            lines.append(
                f"  - {agent.agent_id}  {display_name}  status={agent.status}"
            )

        return "\n".join(lines)
