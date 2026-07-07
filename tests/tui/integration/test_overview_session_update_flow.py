from __future__ import annotations

"""Integration test for overview updates driven by RuntimeSession caches.

This test drives the real Textual :class:`ConsoleApp` in headless mode using
``App.run_test`` and a small dummy :class:`RuntimeClient`. Rather than talking
to a real runtime, it directly populates :class:`RuntimeSession`'s cached
runtime status and swarm overview and signals an update via
:meth:`RuntimeSession._notify_updated`.

The goal is to verify that:

* ``ConsoleApp`` starts on :class:`OverviewScreen`.
* The overview initially reflects the "connecting" state when no snapshots
  are available.
* When the session caches are updated and an update is signalled, the
  overview's :class:`SwarmSummary` and :class:`AgentTable` widgets render the
  new runtime status and agent list.
"""

import pytest

from nate_ntm.api.models import AgentCounts, AgentOverview, RuntimeStatusResult, SwarmOverviewResult
from nate_ntm.tui.app import ConsoleApp
from nate_ntm.tui.runtime_session import RuntimeSession
from nate_ntm.tui.screens import OverviewScreen
from nate_ntm.tui.widgets import AgentTable, SwarmSummary


class _DummyRuntimeClient:
    """Minimal stand-in for :class:`RuntimeClient` used in this test.

    The test never calls any of the runtime client's methods; it only mutates
    :class:`RuntimeSession`'s cached state directly. The dummy exists solely so
    that we can construct a ``RuntimeSession`` without pulling in transport
    details.
    """

    # No behavior required for this slice.
    pass


@pytest.mark.asyncio
async def test_overview_widgets_update_when_session_caches_change() -> None:
    """Overview widgets reflect runtime status and agents after a session update.

    The test runs ``ConsoleApp`` in headless mode, inspects the initial
    "connecting" state of the overview, then simulates the background polling
    loop by populating cached status and overview on the shared
    :class:`RuntimeSession` and signalling an update. The :class:`SwarmSummary`
    and :class:`AgentTable` widgets should render the new information.
    """

    session = RuntimeSession(client=_DummyRuntimeClient(), poll_interval=0.01, event_buffer_size=10)  # type: ignore[arg-type]

    # Pretend the session is connected so that SwarmSummary reports a connected
    # console while the runtime snapshots are still being fetched.
    session._connected = True  # type: ignore[assignment]

    app = ConsoleApp(session)

    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        # Allow the app to mount the initial OverviewScreen.
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, OverviewScreen)

        summary = screen.query_one("#swarm-summary", SwarmSummary)
        table = screen.query_one("#agent-table", AgentTable)

        # With no cached snapshots yet, the overview should reflect a connecting
        # runtime and a missing overview.
        initial_summary = summary.render()
        initial_table = table.render()

        assert "Runtime: connecting" in initial_summary
        assert "Agents: (overview not yet available)" in initial_table

        # Populate cached status and overview as if the background poll loop had
        # fetched them from the runtime, then signal an update to any waiters.
        counts = AgentCounts(
            total=1,
            starting=0,
            idle=1,
            running=0,
            waiting=0,
            failed=0,
        )

        status = RuntimeStatusResult(
            status="running",
            project_path="/tmp/project",
            swarm_id="default",
            agent_counts=counts,
        )

        overview = SwarmOverviewResult(
            swarm_id="default",
            project_path="/tmp/project",
            runtime_status="running",
            agent_counts=counts,
            agents=[
                AgentOverview(
                    agent_id="agent-1",
                    display_name="Agent One",
                    status="idle",
                    has_unread_mail=False,
                )
            ],
        )

        session.runtime_status = status
        session.swarm_overview = overview
        # Notify the overview screen's watcher that new state is available.
        session._notify_updated()

        # Allow the watcher task to observe the update and refresh the widgets.
        await pilot.pause()

        updated_summary = summary.render()
        updated_table = table.render()

        assert "Runtime status: running" in updated_summary
        assert "Swarm: default" in updated_summary
        assert "Agents: total=1" in updated_summary

        assert "agent-1" in updated_table
        assert "Agent One" in updated_table
        assert "status=idle" in updated_table
