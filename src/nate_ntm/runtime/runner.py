"""Run an existing RuntimeDaemon with its control API and ACP TCP server."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field

import uvicorn
from fastapi_jsonrpc import API

from ..api.runtime_api import create_runtime_api_app
from ..api.server import RuntimeApiServer
from ..config.runtime_config import RuntimeConfig
from .adapters import RuntimeAdapters
from .daemon import RuntimeDaemon
from .state import AgentStatus
from .swarm_acp_tcp import SwarmACPTCPServer
from .swarm_state import AgentState, SwarmState

__all__ = [
    "RuntimeControlContext",
    "create_runtime_control_context",
    "serve_runtime_control_api",
    "run_runtime_with_control_api_async",
    "run_runtime_with_control_api",
]

logger = logging.getLogger(__name__)

_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(levelname)-8s %(name)s: %(message)s",
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "format": (
                "%(levelname)-8s %(name)s: "
                '%(client_addr)s - "%(request_line)s" %(status_code)s'
            ),
            "use_colors": False,
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "level": "INFO",
        },
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["default"],
        "level": "INFO",
    },
}


@dataclass(slots=True)
class RuntimeControlContext:
    config: RuntimeConfig
    daemon: RuntimeDaemon
    api_server: RuntimeApiServer
    app: API
    host: str
    port: int
    acp_host: str
    acp_port: int
    acp_server: SwarmACPTCPServer
    bound_port: int = 0
    _uvicorn_server: uvicorn.Server | None = field(default=None, repr=False)
    _server_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _sockets: list[socket.socket] | None = field(default=None, repr=False)


def create_runtime_control_context(
    config: RuntimeConfig,
    swarm_state: SwarmState | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    acp_host: str = "127.0.0.1",
    acp_port: int = 8766,
    adapters: RuntimeAdapters | None = None,
) -> RuntimeControlContext:
    daemon = RuntimeDaemon.resume(config, swarm_state, adapters=adapters)
    if daemon.acp_client is None:
        raise RuntimeError("runtime ACP client was not configured")
    api_server = RuntimeApiServer(daemon=daemon)
    acp_server = SwarmACPTCPServer(
        daemon=daemon,
        agent_client=daemon.acp_client,
        host=acp_host,
        port=acp_port,
    )
    return RuntimeControlContext(
        config=config,
        daemon=daemon,
        api_server=api_server,
        app=create_runtime_api_app(api_server),
        host=host or config.control_api_host,
        port=port if port is not None else config.control_api_port,
        acp_host=acp_host,
        acp_port=acp_port,
        acp_server=acp_server,
    )


async def _start_api_server(ctx: RuntimeControlContext) -> None:
    if ctx._uvicorn_server is not None:
        return
    config = uvicorn.Config(
        ctx.app,
        host=ctx.host,
        port=ctx.port,
        log_config=_LOG_CONFIG,
        log_level="info",
    )
    if not config.loaded:
        config.load()
    sock = config.bind_socket()
    ctx.bound_port = int(sock.getsockname()[1])
    ctx._sockets = [sock]
    server = uvicorn.Server(config)
    ctx._uvicorn_server = server
    server.lifespan = config.lifespan_class(config)
    await server.startup(sockets=ctx._sockets)
    ctx._server_task = asyncio.create_task(server.main_loop())


async def _stop_api_server(ctx: RuntimeControlContext) -> None:
    server = ctx._uvicorn_server
    task = ctx._server_task
    ctx._uvicorn_server = None
    ctx._server_task = None
    if server is not None and task is not None:
        server.should_exit = True
        await task
        await server.shutdown(sockets=ctx._sockets or [])
    ctx._sockets = None
    ctx.bound_port = 0


async def _start_agent(
    ctx: RuntimeControlContext,
    agent_id: str,
    metadata: AgentState,
) -> None:
    client = ctx.daemon.acp_client
    assert client is not None
    try:
        await client.start_agent(agent_id, metadata=metadata)
    except Exception as exc:
        ctx.daemon.mark_agent_failed(agent_id, str(exc))
        logger.warning("agent_start_failed agent_id=%s error=%s", agent_id, exc)
    else:
        ctx.daemon.state.agents[agent_id].status = AgentStatus.RUNNING


async def _start_all_agents(ctx: RuntimeControlContext) -> None:
    await asyncio.gather(
        *(
            _start_agent(ctx, agent_id, metadata)
            for agent_id, metadata in ctx.daemon.swarm_state.agents.items()
        )
    )


async def serve_runtime_control_api(
    ctx: RuntimeControlContext,
    *,
    poll_interval: float = 0.1,
    non_lazy: bool = False,
) -> None:
    await _start_api_server(ctx)
    await ctx.acp_server.start()
    try:
        ctx.daemon.start()
        if non_lazy:
            await _start_all_agents(ctx)
        while not ctx.daemon.state.shutdown_requested:
            await asyncio.sleep(poll_interval)
    finally:
        try:
            await ctx.acp_server.close()
        finally:
            try:
                await _stop_api_server(ctx)
            finally:
                ctx.daemon.mark_stopped()


async def run_runtime_with_control_api_async(
    config: RuntimeConfig,
    swarm_state: SwarmState | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    acp_host: str = "127.0.0.1",
    acp_port: int = 8766,
    poll_interval: float = 0.1,
    adapters: RuntimeAdapters | None = None,
    non_lazy: bool = False,
) -> None:
    ctx = create_runtime_control_context(
        config,
        swarm_state,
        host=host,
        port=port,
        acp_host=acp_host,
        acp_port=acp_port,
        adapters=adapters,
    )
    await serve_runtime_control_api(
        ctx,
        poll_interval=poll_interval,
        non_lazy=non_lazy,
    )


def run_runtime_with_control_api(
    config: RuntimeConfig,
    swarm_state: SwarmState | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    acp_host: str = "127.0.0.1",
    acp_port: int = 8766,
    poll_interval: float = 0.1,
    adapters: RuntimeAdapters | None = None,
    non_lazy: bool = False,
) -> None:
    asyncio.run(
        run_runtime_with_control_api_async(
            config,
            swarm_state,
            host=host,
            port=port,
            acp_host=acp_host,
            acp_port=acp_port,
            poll_interval=poll_interval,
            adapters=adapters,
            non_lazy=non_lazy,
        )
    )
