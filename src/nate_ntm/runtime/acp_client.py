"""Runtime-owned ACP client for nate-oha agents."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from asyncio.subprocess import Process
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Awaitable, TypeVar

from acp import RequestError
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
from .nate_oha_launch import build_nate_oha_launch_spec
from .swarm_state import AgentState

__all__ = [
    "AcpClientError",
    "AcpAgentStatus",
    "AcpAgentSession",
    "BaseAcpClient",
    "NateOhaAcpClient",
]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


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
    startup_timeout_seconds: float = 30.0

    _sessions: dict[str, AcpAgentSession] = field(default_factory=dict, init=False)
    _session_contexts: dict[
        str, AbstractAsyncContextManager[ACPConnectionResources]
    ] = field(default_factory=dict, init=False)
    _temp_config_dirs: dict[str, str] = field(default_factory=dict, init=False)
    _terminal_statuses: dict[str, AcpAgentStatus] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.executable = self.config.nate_oha_executable

    async def _startup_phase(
        self,
        agent_id: str,
        phase: str,
        operation: Awaitable[_T],
        **details: object,
    ) -> _T:
        logger.info("%s_begin agent_id=%s", phase, agent_id, extra=details)
        try:
            async with asyncio.timeout(self.startup_timeout_seconds):
                result = await operation
        except TimeoutError as exc:
            logger.error(
                "%s_timeout agent_id=%s timeout_seconds=%s",
                phase,
                agent_id,
                self.startup_timeout_seconds,
                extra=details,
            )
            raise RequestError.internal_error(
                {
                    "agent_id": agent_id,
                    "phase": phase,
                    "timeout_seconds": self.startup_timeout_seconds,
                    **details,
                }
            ) from exc
        logger.info("%s_complete agent_id=%s", phase, agent_id, extra=details)
        return result

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

        logger.info("agent_start_begin agent_id=%s", agent_id)
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

            await self._startup_phase(
                agent_id,
                "agent_initialize",
                connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=NATE_NTM_CLIENT_CAPABILITIES,
                ),
            )
            if session.conversation_id:
                await self._startup_phase(
                    agent_id,
                    "agent_session_load",
                    connection.load_session(
                        cwd=str(self.config.project_path),
                        session_id=session.conversation_id,
                    ),
                    operation="load",
                    conversation_id=session.conversation_id,
                )
            else:
                response = await self._startup_phase(
                    agent_id,
                    "agent_session_load",
                    connection.new_session(cwd=str(self.config.project_path)),
                    operation="create",
                )
                session.conversation_id = response.session_id
                store = MetadataStore(self.config.swarm_id)
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
            logger.info(
                "agent_start_complete agent_id=%s conversation_id=%s",
                agent_id,
                session.conversation_id,
            )
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
            if isinstance(exc, RequestError):
                raise
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
        try:
            await session.connection.prompt(
                session.conversation_id,
                [TextContentBlock(type="text", text=prompt or "")],
            )
        except RequestError as exc:
            data = {
                "agent_id": agent_id,
                "conversation_id": session.conversation_id,
                "downstream_code": exc.code,
                "downstream_data": exc.data,
            }
            logger.error(
                "Prompt failed for agent %r: %s (code=%s, data=%r)",
                agent_id,
                exc,
                exc.code,
                exc.data,
            )
            raise RequestError(exc.code, str(exc), data) from None
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
        spec = build_nate_oha_launch_spec(config=self.config, metadata=metadata)
        self._temp_config_dirs[agent_id] = str(spec.base_config.parent)
        return list(spec.to_argv())

    def _build_env(self, agent_id: str, metadata: AgentState) -> dict[str, str]:
        env = dict(os.environ)
        env["COLUMNS"] = "1000000"
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
