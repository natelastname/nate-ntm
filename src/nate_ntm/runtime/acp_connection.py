"""Spawn a nate-oha ACP subprocess and bind it to the ACP SDK."""

from __future__ import annotations

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
