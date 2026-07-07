from __future__ import annotations

"""Screens for the Textual runtime console.

At this stage we provide only the default :class:`OverviewScreen`, which
presents a high-level summary of runtime and swarm state backed by the shared
:class:`~nate_ntm.tui.runtime_session.RuntimeSession`.
"""

from .overview import OverviewScreen

__all__ = ["OverviewScreen"]
