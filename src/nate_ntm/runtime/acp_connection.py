"""Spawn a nate-oha ACP subprocess and bind it to the ACP SDK."""

from __future__ import annotations

import asyncio
import logging
from asyncio.subprocess import Process
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Mapping

from acp.client.connection import ClientSideConnection
from acp.interfaces import ClientCapabilities

from .acp_protocol_client import (
    NATE_NTM_CLIENT_CAPABILITIES,
    NateNtmAcpProtocolClient,
    SessionUpdateSink,
)

ACPConnectionResources = tuple[
    ClientSideConnection,
    Process,
    NateNtmAcpProtocolClient,
]

logger = logging.getLogger(__name__)


async def _log_stderr(process: Process, agent_id: str) -> None:
    if process.stderr is None:
        return
    while line := await process.stderr.readline():
        message = line.decode(errors="replace").rstrip()
        if message:
            logger.warning("nate-oha[%s]: %s", agent_id, message)


@asynccontextmanager
async def open_nate_oha_acp_client(
    *,
    command: list[str],
    env: Mapping[str, str] | None,
    cwd: Path,
    agent_id: str,
    on_session_update: SessionUpdateSink,
    capabilities: ClientCapabilities | None = None,
    use_unstable_protocol: bool = False,
) -> AsyncIterator[ACPConnectionResources]:
    """Yield the typed connection, subprocess, and protocol callback client."""

    from acp import spawn_stdio_transport

    async with spawn_stdio_transport(
        command[0],
        *command[1:],
        env=env,
        cwd=cwd,
    ) as (reader, writer, process):
        stderr_task = (
            asyncio.create_task(_log_stderr(process, agent_id))
            if process.stderr is not None
            else None
        )
        protocol_client = NateNtmAcpProtocolClient(
            agent_id=agent_id,
            on_session_update=on_session_update,
        )
        connection = ClientSideConnection(
            protocol_client,
            writer,
            reader,
            use_unstable_protocol=use_unstable_protocol,
        )
        try:
            yield connection, process, protocol_client
        finally:
            await connection.close()
            if stderr_task is not None:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
