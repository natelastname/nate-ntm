"""Runtime-owned ACP client for nate-oha agents."""

from __future__ import annotations

import logging
import os
import shutil
from asyncio.subprocess import Process
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

from acp.client.connection import ClientSideConnection
from acp.meta import PROTOCOL_VERSION
from acp.schema import TextContentBlock

from ..config.runtime_config import RuntimeConfig
from .acp_connection import ACPConnectionResources, open_nate_oha_acp_client
from .acp_protocol_client import NATE_NTM_CLIENT_CAPABILITIES, NateNtmAcpProtocolClient
from .acp_types import SessionUpdate
from .acp_update_stream import (
    AcpSessionUpdateStream,
    AgentSessionNotActive,
    ReceivedSessionUpdate,
    StreamClosedError,
)
from .metadata_store import MetadataStore
from .nate_oha_launch import materialize_nate_oha_config
from .swarm_state import AgentState

__all__ = [
    "AcpClientError",
    "AcpAgentStatus",
    "AcpAgentSession",
    "BaseAcpClient",
    "NateOhaAcpClient",
]

logger = logging.getLogger(__name__)


class AcpClientError(RuntimeError):
    """Base error for ACP lifecycle and transport failures."""


@dataclass(slots=True)
class AcpAgentStatus:
    agent_id: str
    state: str
    last_error: str | None = None


@dataclass(slots=True)
class AcpAgentSession:
    """All runtime-owned resources for one live ACP session."""

    agent_id: str
    conversation_id: str
    process: Process
    connection: ClientSideConnection
    protocol_client: NateNtmAcpProtocolClient
    update_stream: AcpSessionUpdateStream = field(default_factory=AcpSessionUpdateStream)
    status: str = "starting"
    last_error: str | None = None


class BaseAcpClient:
    """Async agent-centric ACP lifecycle contract used by the runtime."""

    async def start_agent(self, agent_id: str, *, metadata: AgentState) -> None:
        raise NotImplementedError

    async def stop_agent(self, agent_id: str) -> None:
        raise NotImplementedError

    async def prompt(self, agent_id: str, prompt: str | None = None) -> str | None:
        raise NotImplementedError

    async def interrupt(self, agent_id: str) -> None:
        raise NotImplementedError

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        raise NotImplementedError

    @asynccontextmanager
    async def subscribe_acp_updates(
        self, agent_id: str
    ) -> AsyncIterator[AsyncIterator[ReceivedSessionUpdate]]:
        raise NotImplementedError
        yield  # pragma: no cover


@dataclass(slots=True)
class NateOhaAcpClient(BaseAcpClient):
    """Launch and manage one nate-oha ACP process per agent."""

    config: RuntimeConfig
    executable: str = "nate-oha"

    _sessions: dict[str, AcpAgentSession] = field(default_factory=dict, init=False)
    _session_contexts: dict[
        str, AbstractAsyncContextManager[ACPConnectionResources]
    ] = field(default_factory=dict, init=False)
    _temp_config_dirs: dict[str, str] = field(default_factory=dict, init=False)
    _terminal_statuses: dict[str, AcpAgentStatus] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.executable = self.config.nate_oha_executable

    def _on_session_update(
        self,
        agent_id: str,
        session_id: str,
        update: SessionUpdate,
        received_at: datetime,
    ) -> None:
        session = self._sessions.get(agent_id)
        if session is None:
            raise AgentSessionNotActive(
                f"Received ACP session update for inactive agent {agent_id!r}"
            )

        bound_session_id = session.conversation_id.strip()
        if bound_session_id and bound_session_id != session_id:
            logger.warning(
                "acp_session_update_for_stale_session",
                extra={
                    "agent_id": agent_id,
                    "expected_session_id": bound_session_id,
                    "actual_session_id": session_id,
                },
            )
            return

        try:
            session.update_stream.publish(update, received_at=received_at)
        except StreamClosedError:
            logger.debug(
                "acp_update_after_stream_closed",
                extra={"agent_id": agent_id, "session_id": session_id},
            )
        except Exception as exc:
            session.update_stream.close(exc)
            raise

    @asynccontextmanager
    async def subscribe_acp_updates(
        self, agent_id: str
    ) -> AsyncIterator[AsyncIterator[ReceivedSessionUpdate]]:
        session = self._require_active_session(agent_id)
        async with session.update_stream.subscribe() as updates:
            yield updates

    async def start_agent(self, agent_id: str, *, metadata: AgentState) -> None:
        current = self._sessions.get(agent_id)
        if current is not None and current.status in {"starting", "running", "waiting"}:
            return

        context = open_nate_oha_acp_client(
            command=self._build_command(agent_id, metadata),
            env=self._build_env(agent_id, metadata),
            cwd=self.config.project_path,
            agent_id=agent_id,
            on_session_update=self._on_session_update,
            capabilities=NATE_NTM_CLIENT_CAPABILITIES,
        )

        try:
            connection, process, protocol_client = await context.__aenter__()
            session = AcpAgentSession(
                agent_id=agent_id,
                conversation_id=(metadata.conversation_id or "").strip(),
                process=process,
                connection=connection,
                protocol_client=protocol_client,
            )
            self._sessions[agent_id] = session
            self._session_contexts[agent_id] = context

            await connection.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=NATE_NTM_CLIENT_CAPABILITIES,
            )
            if session.conversation_id:
                await connection.load_session(
                    cwd=str(self.config.project_path),
                    session_id=session.conversation_id,
                )
            else:
                response = await connection.new_session(cwd=str(self.config.project_path))
                session.conversation_id = response.session_id
                store = MetadataStore(config=self.config)
                try:
                    persisted = store.load_agent_state(agent_id)
                except FileNotFoundError:
                    persisted = metadata
                store.save_agent_state(
                    persisted.model_copy(
                        update={"conversation_id": session.conversation_id}
                    )
                )

            session.status = "running"
            self._terminal_statuses.pop(agent_id, None)
        except Exception as exc:
            self._sessions.pop(agent_id, None)
            self._session_contexts.pop(agent_id, None)
            try:
                await context.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
            self._cleanup_temp_config(agent_id)
            self._terminal_statuses[agent_id] = AcpAgentStatus(
                agent_id=agent_id,
                state="failed",
                last_error=str(exc),
            )
            raise AcpClientError(
                f"Failed to establish ACP connection for agent {agent_id!r}: {exc}"
            ) from exc

    async def stop_agent(self, agent_id: str) -> None:
        context = self._session_contexts.pop(agent_id, None)
        session = self._sessions.pop(agent_id, None)
        if context is None or session is None:
            self._terminal_statuses.setdefault(
                agent_id, AcpAgentStatus(agent_id=agent_id, state="idle")
            )
            self._cleanup_temp_config(agent_id)
            return

        error: Exception | None = None
        try:
            session.status = "stopping"
            await context.__aexit__(None, None, None)
        except Exception as exc:
            error = exc
            raise AcpClientError(
                f"Failed to stop ACP session for agent {agent_id!r}: {exc}"
            ) from exc
        finally:
            session.update_stream.close(error)
            self._cleanup_temp_config(agent_id)
            self._terminal_statuses[agent_id] = AcpAgentStatus(
                agent_id=agent_id,
                state="failed" if error else "terminated",
                last_error=str(error) if error else None,
            )

    async def prompt(self, agent_id: str, prompt: str | None = None) -> str | None:
        session = self._require_active_session(agent_id)
        await session.connection.prompt(
            session.conversation_id,
            [TextContentBlock(type="text", text=prompt or "")],
        )
        return None

    async def interrupt(self, agent_id: str) -> None:
        session = self._require_active_session(agent_id)
        await session.connection.cancel(session.conversation_id)

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        session = self._sessions.get(agent_id)
        if session is not None:
            return AcpAgentStatus(
                agent_id=agent_id,
                state=session.status,
                last_error=session.last_error,
            )
        return self._terminal_statuses.get(
            agent_id, AcpAgentStatus(agent_id=agent_id, state="idle")
        )

    def _require_active_session(self, agent_id: str) -> AcpAgentSession:
        session = self._sessions.get(agent_id)
        if session is None or session.status not in {"starting", "running", "waiting"}:
            raise AcpClientError(
                f"No active ACP session for agent {agent_id!r}; call start_agent(...) first"
            )
        return session

    def _build_command(self, agent_id: str, metadata: AgentState) -> list[str]:
        config_path = materialize_nate_oha_config(config=metadata.nate_oha_config)
        self._temp_config_dirs[agent_id] = str(config_path.parent)
        command = [self.executable, "acp", "--config", str(config_path)]
        if metadata.conversation_id:
            command.extend(["--resume", metadata.conversation_id])
        return command

    def _build_env(self, agent_id: str, metadata: AgentState) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("NATE_NTM_PROJECT_PATH", str(self.config.project_path))
        env.setdefault("NATE_NTM_SWARM_ID", self.config.swarm_id)
        env.setdefault("NATE_NTM_AGENT_ID", agent_id)
        env.setdefault("LLM_MODEL", "openai/gpt-4o")
        if metadata.conversation_id:
            env.setdefault(
                "NATE_NTM_AGENT_CONVERSATION_ID", metadata.conversation_id
            )
        return env

    def _cleanup_temp_config(self, agent_id: str) -> None:
        path = self._temp_config_dirs.pop(agent_id, None)
        if path:
            shutil.rmtree(path, ignore_errors=True)
