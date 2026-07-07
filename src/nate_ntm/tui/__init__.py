"""Textual-based runtime console package.

This package contains the Textual application entrypoint, screens, widgets,
and the shared :class:`RuntimeSession` abstraction used by the console.

The :mod:`nate_ntm.tui.runtime_session` module intentionally has **no
Textual dependencies** so it can be reused by non-UI code and tested in
isolation. Textual components should depend on :class:`RuntimeSession`
rather than on :class:`RuntimeClient` or lower-level transport primitives.
"""
