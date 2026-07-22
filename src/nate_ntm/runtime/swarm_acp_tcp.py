"""TCP transport for external swarm ACP clients."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .daemon import RuntimeDaemon
from .swarm_acp_mux import SwarmAgentClient
from .swarm_acp_server import (
    ConnectionExternalACPConnection,
    SwarmACPConnection,
    SwarmACPServerSession,
)

__all__ = ["SwarmACPTCPServer"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SwarmACPTCPServer:
    """Accept external ACP clients over TCP and bind one mux per connection."""

    daemon: RuntimeDaemon
    agent_client: SwarmAgentClient
    host: str = "127.0.0.1"
    port: int = 8766

    bound_port: int = field(default=0, init=False)
    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    _connections: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        socket = self._server.sockets[0]
        self.bound_port = int(socket.getsockname()[1])

    async def close(self) -> None:
        server = self._server
        self._server = None
        self.bound_port = 0
        if server is not None:
            server.close()
            await server.wait_closed()

        tasks = list(self._connections)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def serve_forever(self) -> None:
        await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)

        peer = writer.get_extra_info("peername")
        external_session_id = f"tcp:{peer!r}"
        bridge = ConnectionExternalACPConnection()
        session = SwarmACPServerSession(
            daemon=self.daemon,
            agent_client=self.agent_client,
            external_connection=bridge,
            external_session_id=external_session_id,
        )
        connection = SwarmACPConnection(session=session, writer=writer, reader=reader)
        bridge.bind(connection)

        async def serve_inbound(_: SwarmACPServerSession) -> None:
            await connection.run()

        async def close_transport() -> None:
            try:
                await connection.close()
            finally:
                writer.close()
                await writer.wait_closed()

        try:
            await session.run_connection(serve_inbound, close_transport=close_transport)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("swarm_acp_connection_failed", extra={"peer": peer})
        finally:
            if task is not None:
                self._connections.discard(task)
