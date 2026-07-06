"""Helpers for running a RuntimeDaemon with its FastAPI control API.

This module provides small orchestration helpers that wire together

* :class:`~nate_ntm.runtime.daemon.RuntimeDaemon`
* :class:`~nate_ntm.api.server.RuntimeApiServer`
* A unified FastAPI/uvicorn control API app created by
  :func:`nate_ntm.api.runtime_api.create_runtime_api_app`.

into a single in-process runtime suitable for the MVP quickstart
scenarios (US1).

The helpers are intentionally minimal and synchronous at the top level so
that they can be used from the Typer-based CLI while still exposing
async-capable building blocks for tests and future event-loop plumbing.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from typing import Optional

import uvicorn
from fastapi_jsonrpc import API

from ..api.runtime_api import create_runtime_api_app
from ..api.server import RuntimeApiServer
from ..config.runtime_config import RuntimeConfig
from .adapters import RuntimeAdapters, create_runtime_adapters
from .daemon import RuntimeDaemon, StartupMode
from .events import AgentEvent

__all__ = [
    "RuntimeControlContext",
    "create_runtime_control_context",
    "serve_runtime_control_api",
    "run_runtime_with_control_api_async",
    "run_runtime_with_control_api",
]


@dataclass(slots=True)
class RuntimeControlContext:
    """Bundle owning a :class:`RuntimeDaemon` and its control API server.

    Parameters
    ----------
    config:
        The resolved :class:`RuntimeConfig` for this runtime instance.

    mode:
        Startup mode used to construct the daemon (``create`` or
        ``resume``).

    daemon:
        The in-process :class:`RuntimeDaemon` instance.

    api_server:
        The :class:`RuntimeApiServer` bound to ``daemon``.

    app:
        The unified FastAPI/JSON-RPC :class:`~fastapi_jsonrpc.API`
        instance exposing the runtime control API.

    host / port:
        Desired bind host and port for the control API. ``port`` may be
        ``0`` to request an ephemeral port; ``bound_port`` will be
        populated with the actual value once the underlying uvicorn
        server has started.
    """

    config: RuntimeConfig
    mode: StartupMode
    daemon: RuntimeDaemon
    api_server: RuntimeApiServer
    app: API
    host: str
    port: int
    bound_port: int = 0

    _uvicorn_server: uvicorn.Server | None = field(default=None, repr=False)
    _server_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _sockets: list[socket.socket] | None = field(default=None, repr=False)


def create_runtime_control_context(
    config: RuntimeConfig,
    mode: StartupMode,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    agent_count: int | None = None,
    adapters: RuntimeAdapters | None = None,
) -> RuntimeControlContext:
    """Construct a :class:`RuntimeControlContext` for ``config`` and ``mode``.

    This helper performs the synchronous wiring needed to:

    * Create or resume a :class:`RuntimeDaemon`.
    * Attach a :class:`RuntimeApiServer` to the daemon.
    * Build a unified FastAPI/JSON-RPC application for the runtime
      control API, bound to the configured host/port.

    The returned context does **not** start the uvicorn server or mark
    the daemon as running; call :func:`serve_runtime_control_api` to do
    so under an event loop.
    """

    if adapters is None:
        adapters = create_runtime_adapters(config)

    if mode is StartupMode.CREATE:
        daemon = RuntimeDaemon.create(
            config,
            agent_count=agent_count,
            adapters=adapters,
        )
    elif mode is StartupMode.RESUME:
        daemon = RuntimeDaemon.resume(config, adapters=adapters)
    else:  # pragma: no cover - defensive against future enum variants
        raise ValueError(f"Unsupported startup mode: {mode!r}")

    api_server = RuntimeApiServer(daemon=daemon)

    host_value = host or config.control_api_host
    port_value = port if port is not None else config.control_api_port

    app = create_runtime_api_app(api_server)

    # Wire the runtime's AgentEvent pipeline into the WebSocket event
    # streaming endpoint exposed by the FastAPI app. The scheduler's
    # AgentSupervisor invokes ``on_agent_event`` whenever a new
    # :class:`AgentEvent` is appended to an agent's in-memory event
    # stream; here we forward those events to the app's
    # ``state.publish_event`` coroutine if it is present.
    scheduler = daemon.scheduler
    if scheduler is not None:
        supervisor = getattr(scheduler, "agent_supervisor", None)
        publish_event = getattr(app.state, "publish_event", None)

        if supervisor is not None and publish_event is not None:

            def _on_agent_event(event: AgentEvent) -> None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # If no event loop is running (for example, in pure
                    # in-process unit tests), we still record events in the
                    # per-agent streams but skip streaming notifications.
                    return

                # Schedule asynchronous publication of the event without
                # blocking the caller.
                loop.create_task(publish_event(event))

            supervisor.on_agent_event = _on_agent_event

    return RuntimeControlContext(
        config=config,
        mode=mode,
        daemon=daemon,
        api_server=api_server,
        app=app,
        host=host_value,
        port=port_value,
    )


async def _start_api_server(ctx: RuntimeControlContext) -> None:
    """Start the uvicorn server for the runtime control API.

    This binds the configured host/port (supporting ``port=0`` for an
    ephemeral port), runs uvicorn's startup sequence, and then launches
    the main loop as a background task on the current event loop.
    """

    if ctx._uvicorn_server is not None:
        # Already started.
        return

    config = uvicorn.Config(
        ctx.app,
        host=ctx.host,
        port=ctx.port,
        log_level="info",
    )
    if not config.loaded:
        config.load()

    # Bind a socket so we can discover the effective port when
    # ``port=0`` was requested, then run uvicorn's startup sequence
    # against that socket.
    sock = config.bind_socket()
    ctx.bound_port = int(sock.getsockname()[1])
    ctx._sockets = [sock]

    server = uvicorn.Server(config)
    ctx._uvicorn_server = server
    # Mirror the setup performed in ``Server._serve`` so that
    # ``startup`` can run correctly when called directly.
    server.lifespan = config.lifespan_class(config)
    await server.startup(sockets=ctx._sockets)

    # Run the uvicorn main loop in the background; the caller owns
    # the event loop.
    loop = asyncio.get_running_loop()
    ctx._server_task = loop.create_task(server.main_loop())


async def _stop_api_server(ctx: RuntimeControlContext) -> None:
    """Stop the uvicorn server and close all active connections."""

    server = ctx._uvicorn_server
    ctx._uvicorn_server = None

    # Ask the uvicorn main loop to exit and wait for it to finish.
    task = ctx._server_task
    ctx._server_task = None

    if server is not None and task is not None:
        server.should_exit = True
        await task

        sockets = ctx._sockets or []
        await server.shutdown(sockets=sockets)

    ctx._sockets = None
    ctx.bound_port = 0



async def serve_runtime_control_api(
    ctx: RuntimeControlContext,
    *,
    poll_interval: float = 0.1,
) -> None:
    """Start the FastAPI control API and run until shutdown is requested.

    This coroutine is responsible for the *lifetime* of the control API
    server for a single runtime instance. It:

    * Starts the underlying FastAPI/uvicorn application.
    * Marks the :class:`RuntimeDaemon` as running via :meth:`start`.
    * Polls :attr:`RuntimeState.shutdown_requested` until a graceful
      shutdown has been requested (for example, via the
      ``runtime.shutdown`` control API method).
    * On exit, stops the API server and marks the daemon as stopped.

    The caller owns the asyncio event loop and is expected to manage
    cancellation or process-level signals as appropriate.
    """

    await _start_api_server(ctx)

    try:
        # Transition the daemon into the Running state. This will, in
        # turn, allow the scheduler to register and "launch" configured
        # agents in dev-mode.
        ctx.daemon.start()

        # Simple polling loop driven by the RuntimeState flag. More
        # sophisticated event-loop and signal handling can be introduced
        # later without changing this basic contract.
        while not ctx.daemon.state.shutdown_requested:
            await asyncio.sleep(poll_interval)
    finally:
        # Always attempt to stop the API server and mark the daemon as
        # fully stopped, even if an error or cancellation occurs while
        # serving requests.
        try:
            await _stop_api_server(ctx)
        finally:
            ctx.daemon.mark_stopped()


async def run_runtime_with_control_api_async(
    config: RuntimeConfig,
    mode: StartupMode,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    poll_interval: float = 0.1,
    agent_count: int | None = None,
    adapters: RuntimeAdapters | None = None,
) -> None:
    """Async helper to run a runtime and its control API to completion.

    This is a convenience wrapper that constructs a
    :class:`RuntimeControlContext` and delegates to
    :func:`serve_runtime_control_api`. It is suitable for use in tests or
    higher-level orchestration code that already manages an asyncio
    event loop.
    """

    ctx = create_runtime_control_context(
        config,
        mode,
        host=host,
        port=port,
        agent_count=agent_count,
        adapters=adapters,
    )
    await serve_runtime_control_api(ctx, poll_interval=poll_interval)


def run_runtime_with_control_api(
    config: RuntimeConfig,
    mode: StartupMode,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    poll_interval: float = 0.1,
    agent_count: int | None = None,
    adapters: RuntimeAdapters | None = None,
) -> None:
    """Run a runtime daemon and its FastAPI control API to completion.

    This synchronous helper is intended for use from the Typer-based CLI
    and other non-async entrypoints. It drives the underlying coroutine
    via :func:`asyncio.run` and returns once a graceful shutdown has been
    requested and processed.
    """

    asyncio.run(
        run_runtime_with_control_api_async(
            config,
            mode,
            host=host,
            port=port,
            poll_interval=poll_interval,
            agent_count=agent_count,
            adapters=adapters,
        )
    )
