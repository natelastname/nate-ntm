from __future__ import annotations

"""Textual application shell for the nate_ntm runtime console.

This module defines :class:`ConsoleApp`, a thin Textual :class:`~textual.app.App`
subclass that owns exactly one :class:`~nate_ntm.tui.runtime_session.RuntimeSession`
instance for the lifetime of the process.

Layering
========

The app is responsible for:

* Constructing a :class:`~nate_ntm.api.runtime_client.RuntimeClient` based on
  CLI-provided host/port parameters.
* Constructing a :class:`RuntimeSession` around that client.
* Calling :meth:`RuntimeSession.connect` during startup and
  :meth:`RuntimeSession.disconnect` during shutdown.
* Pushing the default :class:`OverviewScreen` as the initial screen.

Textual screens and widgets **do not** talk to the runtime or transports
directly; they observe a shared :class:`RuntimeSession` owned by this app.
"""

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.events import Shutdown

from nate_ntm.api.runtime_client import RuntimeClient
from nate_ntm.tui.runtime_session import RuntimeSession
from nate_ntm.tui.screens.overview import OverviewScreen


class ConsoleApp(App[None]):
    """Textual runtime console application.

    The app owns a single :class:`RuntimeSession` instance, which in turn owns
    the underlying :class:`RuntimeClient`. All screens obtain runtime state via
    that shared session and must not create additional protocol clients.
    """

    TITLE = "nate_ntm Runtime Console"

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, **kwargs: Any) -> None:
        """Construct a new console app.

        Parameters
        ----------
        host:
            Runtime control API host. This is typically the same host where the
            runtime daemon is running.

        port:
            Runtime control API TCP port. By default this matches the control
            API defaults used elsewhere in the project.
        """

        super().__init__(**kwargs)
        self._client = RuntimeClient(host=host, port=port)
        self.session = RuntimeSession(client=self._client)
        self._connected: bool = False

    async def on_mount(self) -> None:  # pragma: no cover - exercised via Textual runtime
        """Connect the runtime session and push the overview screen.

        For the initial implementation we keep error handling simple: if the
        session fails to connect, the app logs the error and exits.
        """

        try:
            await self.session.connect()
        except Exception as exc:  # pragma: no cover - defensive
            # In a later polish phase we will surface this in a dedicated
            # connection error screen. For now, log and exit non-interactively.
            self.log(f"Failed to connect to runtime: {exc}")
            self.exit(message=f"Failed to connect to runtime: {exc}")
            return

        self._connected = True
        await self.push_screen(OverviewScreen(self.session))

    async def on_shutdown(self, event: Shutdown) -> None:  # pragma: no cover - Textual runtime hook
        """Ensure the runtime session is disconnected on application shutdown."""

        if self._connected:
            # Best-effort disconnect; swallow cancellation so shutdown can
            # proceed even if the runtime is already gone.
            try:
                await self.session.disconnect()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                self.log(f"Error while disconnecting session: {exc}")
            finally:
                self._connected = False

    def compose(self) -> ComposeResult:  # pragma: no cover - UI composition
        """Compose the root view.

        The app itself does not render substantial UI; it immediately pushes
        :class:`OverviewScreen` from :meth:`on_mount`. This method is provided
        for completeness and potential future extensions.
        """

        # Textual requires a compose method, but since we push the overview
        # screen explicitly in :meth:`on_mount`, there is nothing to compose at
        # the root level for now.
        yield from ()
