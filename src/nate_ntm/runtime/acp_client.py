"""ACP client adapters for the swarm runtime.

The nate_ntm runtime owns all ACP (Agent Control Protocol) integrations
for agents in a swarm. This module defines the
:class:`BaseAcpClient` abstraction that the runtime and scheduler use to
interact with ACP-backed agent runtimes.

Concrete implementations in this branch are:

* :class:`FakeAcpClient` – an in-memory, dev-mode implementation used in
  unit/integration tests that simulates conversations and turn
  identifiers without performing any network I/O.
* :class:`OpenHandsAcpClient` – a legacy HTTP adapter that speaks the
  OpenHands-compatible ACP server surface and is retained for
  compatibility and potential OpenHands-focused integrations.
* :class:`NateOhaAcpClient` – the nate_OHA-backed ACP adapter used as the
  canonical ``AdapterKind.REAL`` implementation for the nate_ntm
  runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Literal

import json
import os
import re
import subprocess
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config.runtime_config import RuntimeConfig
from .events import AgentEvent, AgentEventSource
from .metadata_store import AgentMetadata

__all__ = [
    "AcpClientError",
    "AcpAgentStatus",
    "BaseAcpClient",
    "FakeAcpClient",
    "OpenHandsAcpClient",
    "NateOhaAcpClient",
]


class AcpClientError(RuntimeError):
    """Base error type for ACP adapter failures."""



@dataclass(slots=True)
class AcpAgentStatus:
    """Lightweight adapter-level status for a single agent.

    Instances of this type are returned by :meth:`BaseAcpClient.get_status`
    and are intended to be easy to map onto :class:`AgentRuntimeState` and
    runtime API payloads.
    """

    agent_id: str
    """Identifier of the agent this status belongs to."""

    state: str
    """Adapter-level lifecycle state (for example ``"idle"`` or ``"running"``)."""

    last_exit_code: int | None = None
    """Exit code from the most recent process run, if applicable."""

    last_error: str | None = None
    """Summary of the last error observed for this agent, if any."""

    restart_count: int = 0
    """Number of restarts attempted for this agent, when tracked."""


@dataclass(slots=True)
class NateOhaProcessRecord:
    """In-memory supervision record for a nate_OHA subprocess.

    This mirrors the conceptual model described in
    ``specs/002-nate-oha-acp-adapter/data-model.md`` section 2.1.
    ``NateOhaAcpClient`` maintains one record per nate_OHA–backed agent.
    """

    agent_id: str
    pid: int | None = None
    status: Literal["starting", "running", "stopping", "terminated", "failed"] = "starting"
    last_start_time: datetime | None = None
    last_exit_code: int | None = None
    last_error: str | None = None
    restart_count: int = 0


class BaseAcpClient:
    """Runtime-facing contract for ACP-backed agent execution.

    Implementations are responsible for:

    * Owning ACP/runtime lifecycle for managed agents (process launch,
      readiness checks, shutdown, and status reporting).
    * Ensuring a per-agent control-protocol conversation exists and
      returning an opaque identifier for it.
    * Starting new "turns" of work for agents and surfacing their
      identifiers back to the runtime.
    * Optionally emitting :class:`AgentEvent` instances via the
      :attr:`on_event` callback.

    Concrete implementations are expected to be **runtime-owned** and
    reused for the lifetime of the process.
    """

    #: Optional callback invoked when adapter-level events occur for an
    #: agent. Implementations SHOULD invoke this for significant ACP or
    #: process lifecycle events when configured.
    on_event: Callable[[AgentEvent], None] | None = None

    # The following methods define the public contract. Concrete
    # implementations *must* override them.

    def ensure_conversation(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Ensure a control-protocol conversation exists for ``agent_id``.

        The returned string is an opaque conversation identifier. The
        method must be **idempotent**: repeated calls for the same
        ``agent_id`` MUST return the same conversation ID.
        """

        raise NotImplementedError

    def start_agent(self, agent_id: str, *, metadata: AgentMetadata) -> None:  # pragma: no cover - abstract
        """Launch or attach to the ACP runtime backing ``agent_id``.

        Implementations are free to decide how much work is performed
        synchronously here (for example, spawning a subprocess and
        performing an initial health check) as long as they satisfy the
        process launch contract described in the feature spec.
        """

        raise NotImplementedError

    def start_turn(self, agent_id: str, prompt: str | None = None) -> str:  # pragma: no cover - abstract
        """Start a new ACP turn for ``agent_id`` and return its ID.

        The exact semantics of a "turn" are defined by the ACP spec and
        the concrete implementation. The fake client simply allocates a
        monotonically increasing identifier per agent. The optional
        ``prompt`` parameter is accepted for compatibility with adapters
        that initiate work based on an explicit prompt.
        """

        raise NotImplementedError

    def stop_agent(self, agent_id: str, *, timeout: float) -> None:  # pragma: no cover - abstract
        """Request a graceful stop for the ACP runtime backing ``agent_id``.

        Implementations should enforce a bounded timeout and apply any
        configured restart or escalation policy on timeout.
        """

        raise NotImplementedError

    def get_status(self, agent_id: str) -> AcpAgentStatus:  # pragma: no cover - abstract
        """Return a lightweight status snapshot for ``agent_id``.

        The returned :class:`AcpAgentStatus` is intended to be easy to map
        onto :class:`AgentRuntimeState` and the runtime API payloads.
        """

        raise NotImplementedError


@dataclass(slots=True)
class FakeAcpClient(BaseAcpClient):
    """In-memory ACP client for tests and dev-mode.

    This implementation does **not** perform any network I/O. It keeps
    a minimal in-memory model of:

    * A per-agent conversation identifier.
    * A monotonically increasing counter of turn IDs per agent.
    * A lightweight adapter-level lifecycle state for each agent.

    It is sufficient for unit tests and early integration tests that
    need stable, realistic-looking conversation and turn identifiers
    without talking to a real ACP server.
    """

    config: RuntimeConfig

    _conversations: Dict[str, str] = field(default_factory=dict)
    _turn_counters: Dict[str, int] = field(default_factory=dict)
    _agent_states: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # BaseAcpClient API
    # ------------------------------------------------------------------

    def ensure_conversation(self, agent_id: str) -> str:
        if agent_id in self._conversations:
            return self._conversations[agent_id]

        # Derive a deterministic, human-readable conversation identifier.
        conv_id = f"fake-conversation:{agent_id}"
        self._conversations[agent_id] = conv_id
        return conv_id

    def start_agent(self, agent_id: str, *, metadata: AgentMetadata) -> None:
        """Dev-mode implementation: record the agent as running.

        This method does not launch any real subprocesses. It simply tracks a
        basic lifecycle state suitable for tests that exercise
        :meth:`BaseAcpClient.get_status`.
        """

        # Ensure a conversation is allocated for the agent so that metadata
        # and runtime state can rely on a stable identifier.
        self.ensure_conversation(agent_id)
        self._agent_states[agent_id] = "running"

    def start_turn(self, agent_id: str, prompt: str | None = None) -> str:
        """Allocate a new fake turn ID and emit an optional event.

        The ``prompt`` parameter is accepted for API compatibility but is not
        interpreted by this dev-mode implementation.
        """

        # Ensure a conversation exists; many callers will already have done
        # this explicitly but the helper is cheap and idempotent.
        conversation_id = self.ensure_conversation(agent_id)

        counter = self._turn_counters.get(agent_id, 0) + 1
        self._turn_counters[agent_id] = counter
        turn_id = f"fake-turn:{agent_id}:{counter}"

        # When configured, emit a simple adapter-level event so that tests can
        # observe ACP activity via the runtime event pipeline.
        if self.on_event is not None:
            event = AgentEvent(
                event_id=f"{agent_id}:{counter}",
                timestamp=datetime.utcnow(),
                agent_id=agent_id,
                source=AgentEventSource.ACP,
                type="TurnCompleted",
                payload={
                    "adapter": "fake",
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    **({"prompt": prompt} if prompt is not None else {}),
                },
            )
            self.on_event(event)

        return turn_id

    def stop_agent(self, agent_id: str, *, timeout: float) -> None:
        """Dev-mode implementation: mark the agent as terminated.

        Unknown agents are treated as a no-op but will subsequently report a
        ``"terminated"`` state via :meth:`get_status`.
        """

        self._agent_states[agent_id] = "terminated"

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        """Return a lightweight adapter-level status for ``agent_id``."""

        state = self._agent_states.get(agent_id, "idle")
        return AcpAgentStatus(
            agent_id=agent_id,
            state=state,
            last_exit_code=None,
            last_error=None,
            restart_count=0,
        )


@dataclass(slots=True)
class OpenHandsAcpClient(BaseAcpClient):
    """Legacy OpenHands-compatible ACP adapter over HTTP (T102).

    This implementation speaks the ACP HTTP/OpenAPI surface defined in
    ``reference/acp-spec/openapi.json`` (v0.2.3). It focuses on the minimal
    operations required by the runtime today:

    * Ensure a per-agent conversation (ACP thread) exists.
    * Start new runs on that thread and return their identifiers.

    The adapter remains available for compatibility and potential
    OpenHands-focused integrations, but the nate_ntm runtime now uses
    :class:`NateOhaAcpClient` as the canonical ``AdapterKind.REAL`` ACP
    implementation.
    """

    config: RuntimeConfig
    base_url: str | None = None
    bearer_token: str | None = None
    timeout: float = 5.0

    # Cache of per-agent conversation identifiers (thread IDs).
    _conversations: Dict[str, str] = field(default_factory=dict, init=False)

    # Namespace used to derive deterministic thread IDs from runtime context.
    _thread_namespace = uuid.UUID("d71950ef-c7fe-44b8-b892-24c0960f46a4")

    def __post_init__(self) -> None:
        """Resolve endpoint and auth settings from arguments or environment.

        The base URL is taken from, in order of precedence:

        * the explicit ``base_url`` argument
        * ``NATE_NTM_ACP_URL``
        * ``ACP_URL``
        * a localhost default (``http://127.0.0.1:8766``)

        Similarly, the bearer token is taken from:

        * the explicit ``bearer_token`` argument
        * ``NATE_NTM_ACP_TOKEN``
        * ``ACP_TOKEN``
        * or left empty if none is provided.
        """

        url = (
            self.base_url
            or os.environ.get("NATE_NTM_ACP_URL")
            or os.environ.get("ACP_URL")
            or "http://127.0.0.1:8766"
        )
        # Normalize by stripping whitespace and trailing slashes.
        self.base_url = url.strip().rstrip("/")

        token = (
            self.bearer_token
            or os.environ.get("NATE_NTM_ACP_TOKEN")
            or os.environ.get("ACP_TOKEN")
            or ""
        )
        self.bearer_token = token.strip() or None

    # ------------------------------------------------------------------
    # BaseAcpClient API
    # ------------------------------------------------------------------

    def ensure_conversation(self, agent_id: str) -> str:
        """Ensure an ACP thread exists for ``agent_id``.

        The conversation identifier is the ACP ``thread_id``. It is derived
        deterministically from the runtime configuration and ``agent_id`` so
        that repeated calls – even across processes – return the same
        identifier, while the ACP ``ThreadCreate.if_exists`` flag is used to
        make thread creation idempotent on the server.
        """

        if agent_id in self._conversations:
            return self._conversations[agent_id]

        # Derive a stable, per-agent thread UUID based on the project path
        # and swarm ID. This avoids a separate lookup step when resuming a
        # runtime: the same inputs yield the same thread ID.
        project_path = str(self.config.project_path)
        basis = f"{self.config.swarm_id}:{project_path}:{agent_id}"
        thread_uuid = uuid.uuid5(self._thread_namespace, basis)
        thread_id = str(thread_uuid)

        body = {
            "thread_id": thread_id,
            "metadata": {
                "nate_ntm_swarm_id": self.config.swarm_id,
                "nate_ntm_project_path": project_path,
                "nate_ntm_agent_id": agent_id,
            },
            "if_exists": "do_nothing",
        }

        response = self._request(
            "POST",
            "/threads",
            body=body,
            request_name=f"ACP create_thread({agent_id})",
        )

        conv_id = thread_id
        if isinstance(response, Mapping):
            returned = str(response.get("thread_id") or "").strip()
            if returned:
                conv_id = returned

        self._conversations[agent_id] = conv_id
        return conv_id

    def start_agent(self, agent_id: str, *, metadata: AgentMetadata) -> None:
        """Legacy HTTP adapter does not manage a local subprocess.

        This method is provided for API compatibility with the expanded
        :class:`BaseAcpClient` contract and currently acts as a no-op beyond
        ensuring that a conversation exists for the agent.
        """

        self.ensure_conversation(agent_id)

    def start_turn(self, agent_id: str, prompt: str | None = None) -> str:
        """Start a new stateful ACP run for ``agent_id``.

        This creates a background run on the agent's thread using
        ``POST /threads/{thread_id}/runs`` and returns the ``run_id`` from the
        ACP ``RunStateful`` response. The optional ``prompt`` parameter is
        accepted for API compatibility but is not currently sent over the
        wire.
        """

        thread_id = self.ensure_conversation(agent_id)

        body = {
            # We rely on the server's default agent configuration. Runtime
            # metadata is attached so operators can correlate runs.
            "metadata": {
                "nate_ntm_swarm_id": self.config.swarm_id,
                "nate_ntm_agent_id": agent_id,
            }
        }

        path = f"/threads/{thread_id}/runs"
        response = self._request(
            "POST",
            path,
            body=body,
            request_name=f"ACP create_thread_run({agent_id})",
        )

        run_id: str | None = None
        if isinstance(response, Mapping):
            raw = response.get("run_id")
            if raw:
                run_id = str(raw).strip()
            else:
                # Some implementations may wrap the run object.
                run = response.get("run")
                if isinstance(run, Mapping):
                    raw = run.get("run_id")
                    if raw:
                        run_id = str(raw).strip()

        if not run_id:
            raise AcpClientError("ACP create_thread_run: missing run_id in response")

        return run_id

    def stop_agent(self, agent_id: str, *, timeout: float) -> None:
        """Legacy HTTP adapter has no local process to stop.

        This method is provided for API compatibility with the expanded
        :class:`BaseAcpClient` contract and currently acts as a no-op.
        """

        return None

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        """Return a minimal adapter-level status for ``agent_id``.

        The OpenHands HTTP adapter does not expose a local subprocess, so it
        reports a simple ``"unknown"`` state; higher layers may derive richer
        status via other mechanisms.
        """

        return AcpAgentStatus(agent_id=agent_id, state="unknown")

    # ------------------------------------------------------------------
    # Low-level HTTP helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        request_name: str,
    ) -> Any:
        """Perform an HTTP JSON request against the ACP server.

        Responses are decoded as JSON. Network errors, HTTP error statuses,
        and invalid JSON payloads are wrapped in :class:`AcpClientError` so
        callers see a consistent error surface.
        """

        url = f"{self.base_url}/{path.lstrip('/')}"

        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        req = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:  # pragma: no cover - network/HTTP error
            raise AcpClientError(
                f"{request_name}: HTTP {exc.code} error from ACP server"
            ) from exc
        except URLError as exc:  # pragma: no cover - network error
            raise AcpClientError(
                f"{request_name}: failed to reach ACP server"
            ) from exc

        text = raw.decode("utf-8") if raw else ""
        if not text:
            return {}

        try:
            decoded: Any = json.loads(text)
        except ValueError as exc:  # pragma: no cover - defensive
            raise AcpClientError(
                f"{request_name}: invalid JSON response from ACP server"
            ) from exc

        return decoded


@dataclass(slots=True)
class NateOhaAcpClient(BaseAcpClient):
    """Production ACP adapter that launches and supervises ``nate_OHA``.

    NateOhaAcpClient is the canonical production implementation of
    :class:`BaseAcpClient` for the nate_ntm runtime. It owns the lifecycle of
    a dedicated ``nate_OHA`` process per managed agent and reports
    adapter-level status via :class:`AcpAgentStatus`.

    The initial implementation focuses on the process-supervision contract
    described in the Feature 002 spec. Conversation semantics and ACP event
    streaming are added in subsequent tasks.
    """

    config: RuntimeConfig

    #: Executable used to launch nate_OHA. This may be overridden in tests or
    #: deployment-specific configuration if needed.
    executable: str = "nate_OHA"

    #: Maximum time to wait for initial nate_OHA readiness checks.
    startup_timeout: float = 15.0

    #: Default timeout for graceful shutdown requests.
    shutdown_timeout: float = 10.0

    # Internal process supervision state, keyed by ``agent_id``.
    _processes: Dict[str, NateOhaProcessRecord] = field(default_factory=dict, init=False)

    # Live subprocess handles keyed by ``agent_id``. These are used for
    # shutdown and basic health checks and are not exposed outside the
    # adapter.
    _process_handles: Dict[str, subprocess.Popen] = field(default_factory=dict, init=False)

    # Cached result of the version/compatibility check (FR-013).
    _version_checked: bool = field(default=False, init=False)
    _detected_version: str | None = field(default=None, init=False)

    # ------------------------------------------------------------------
    # BaseAcpClient API (skeleton; implemented in T212–T214)
    # ------------------------------------------------------------------

    def ensure_conversation(self, agent_id: str) -> str:  # pragma: no cover - placeholder
        """Ensure a control-protocol conversation exists for ``agent_id``.

        The concrete nate_OHA/OpenHands conversation semantics are implemented
        in subsequent tasks; for now this method is left unimplemented so that
        tests can be written against the intended behavior.
        """

        raise NotImplementedError("NateOhaAcpClient.ensure_conversation is not implemented yet")

    def start_agent(self, agent_id: str, *, metadata: AgentMetadata) -> None:
        """Launch the nate_OHA ACP process backing ``agent_id``.

        This implementation follows the nate_OHA process-launch contract at a
        high level:

        * Ensure the nate_OHA binary is compatible via :meth:`_check_version`.
        * Spawn a dedicated nate_OHA process for the agent.
        * Create/update the in-memory :class:`NateOhaProcessRecord`.
        * Perform a lightweight startup check and transition the record to a
          running or failed state.
        """

        self._check_version()

        # Avoid spawning duplicate processes for the same agent when one is
        # already starting or running. Restart semantics are implemented in
        # later tasks.
        existing = self._processes.get(agent_id)
        if existing is not None and existing.status in {"starting", "running"}:
            return

        cmd = self._build_command(metadata)
        env = self._build_env(agent_id, metadata)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.config.project_path),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:  # pragma: no cover - defensive
            message = str(exc)
            record = NateOhaProcessRecord(
                agent_id=agent_id,
                pid=None,
                status="failed",
                last_start_time=datetime.utcnow(),
                last_exit_code=None,
                last_error=message,
                restart_count=existing.restart_count if existing else 0,
            )
            self._processes[agent_id] = record
            raise AcpClientError(
                f"Failed to launch nate_OHA process for agent {agent_id!r}: {message}"
            ) from exc

        record = NateOhaProcessRecord(
            agent_id=agent_id,
            pid=proc.pid,
            status="starting",
            last_start_time=datetime.utcnow(),
            last_exit_code=existing.last_exit_code if existing else None,
            last_error=None,
            restart_count=existing.restart_count if existing else 0,
        )
        self._processes[agent_id] = record
        self._process_handles[agent_id] = proc

        # Emit a simple process-started event when a callback is configured.
        if self.on_event is not None:
            self.on_event(
                self._make_process_event(
                    agent_id=agent_id,
                    event_type="nate_oha_process_started",
                    payload={"pid": proc.pid},
                )
            )

        # Minimal readiness check: if the process has already exited, treat
        # startup as failed; otherwise consider it running.
        retcode = proc.poll()
        if retcode is not None:
            record.status = "failed"
            record.last_exit_code = retcode
            record.last_error = f"nate_OHA exited during startup with code {retcode}"

            if self.on_event is not None:
                self.on_event(
                    self._make_process_event(
                        agent_id=agent_id,
                        event_type="nate_oha_process_start_failed",
                        payload={"exit_code": retcode},
                    )
                )

            raise AcpClientError(
                f"nate_OHA process for agent {agent_id!r} exited during startup with code {retcode}"
            )

        record.status = "running"
        if self.on_event is not None:
            self.on_event(
                self._make_process_event(
                    agent_id=agent_id,
                    event_type="nate_oha_process_ready",
                    payload={"pid": proc.pid},
                )
            )

    def start_turn(self, agent_id: str, prompt: str | None = None) -> str:  # pragma: no cover - placeholder
        """Start a new ACP turn for ``agent_id``.

        Turn semantics for nate_OHA-backed agents are implemented in
        follow-up tasks; this placeholder exists so that tests can be written
        against the intended interface.
        """

        raise NotImplementedError("NateOhaAcpClient.start_turn is not implemented yet")

    def stop_agent(self, agent_id: str, *, timeout: float) -> None:
        """Request a graceful stop for the nate_OHA process backing ``agent_id``.

        The method attempts a graceful termination first (``SIGTERM`` via
        :meth:`subprocess.Popen.terminate`) and escalates to a forced kill if
        the process does not exit within ``timeout`` seconds. Adapter-level
        status and process records are updated accordingly.
        """

        record = self._processes.get(agent_id)
        proc = self._process_handles.get(agent_id)

        # If we have no subprocess handle, treat this as a no-op but ensure the
        # status reflects a non-running agent for subsequent calls.
        if record is None or proc is None or record.pid is None:
            if record is None:
                self._processes[agent_id] = NateOhaProcessRecord(
                    agent_id=agent_id,
                    pid=None,
                    status="terminated",
                    last_start_time=None,
                    last_exit_code=None,
                    last_error=None,
                    restart_count=0,
                )
            else:
                record.status = "terminated"
            return

        # If the process has already exited, just normalize the status.
        retcode = proc.poll()
        if retcode is not None:
            record.last_exit_code = retcode
            record.status = "terminated" if retcode == 0 else "failed"
            if retcode != 0 and not record.last_error:
                record.last_error = f"nate_OHA exited with code {retcode}"

            self._process_handles.pop(agent_id, None)

            if self.on_event is not None:
                event_type = (
                    "nate_oha_process_exited" if retcode == 0 else "nate_oha_process_crashed"
                )
                self.on_event(
                    self._make_process_event(
                        agent_id=agent_id,
                        event_type=event_type,
                        payload={"exit_code": retcode},
                    )
                )
            return

        record.status = "stopping"
        try:
            proc.terminate()
            try:
                retcode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                retcode = proc.wait(timeout=timeout)
        except OSError as exc:  # pragma: no cover - defensive
            record.status = "failed"
            record.last_error = f"Failed to stop nate_OHA process: {exc}"
            if self.on_event is not None:
                self.on_event(
                    self._make_process_event(
                        agent_id=agent_id,
                        event_type="nate_oha_process_stop_failed",
                        payload={"error": str(exc)},
                    )
                )
            raise AcpClientError(
                f"Failed to stop nate_OHA process for agent {agent_id!r}: {exc}"
            ) from exc

        record.last_exit_code = retcode
        record.status = "terminated" if retcode == 0 else "failed"
        if retcode != 0 and not record.last_error:
            record.last_error = f"nate_OHA exited with code {retcode}"

        self._process_handles.pop(agent_id, None)

        if self.on_event is not None:
            event_type = "nate_oha_process_exited" if retcode == 0 else "nate_oha_process_crashed"
            self.on_event(
                self._make_process_event(
                    agent_id=agent_id,
                    event_type=event_type,
                    payload={"exit_code": retcode},
                )
            )

    def get_status(self, agent_id: str) -> AcpAgentStatus:
        """Return a lightweight status snapshot for ``agent_id``.

        When no nate_OHA process has been started for ``agent_id``, the
        adapter reports an ``"idle"`` state. Otherwise the status is derived
        from the corresponding :class:`NateOhaProcessRecord`.
        """

        record = self._processes.get(agent_id)
        if record is None:
            return AcpAgentStatus(
                agent_id=agent_id,
                state="idle",
                last_exit_code=None,
                last_error=None,
                restart_count=0,
            )

        return AcpAgentStatus(
            agent_id=agent_id,
            state=record.status,
            last_exit_code=record.last_exit_code,
            last_error=record.last_error,
            restart_count=record.restart_count,
        )

    def _build_command(self, metadata: AgentMetadata) -> list[str]:
        """Construct the nate_OHA command line for ``metadata``.

        The exact set of flags is intentionally small for now and will be
        expanded as additional Feature 002 requirements are implemented.
        """

        cmd = [self.executable, "acp"]

        # Enable Agent Mail integration when an identity is configured.
        if metadata.agent_mail_identity:
            cmd.append("--enable-agent-mail")

        return cmd

    def _build_env(self, agent_id: str, metadata: AgentMetadata) -> Dict[str, str]:
        """Return the environment used to launch nate_OHA.

        The base environment is inherited from the current process with a
        small set of nate_ntm-specific variables added for correlation.

        When Agent Mail is enabled for an agent (that is, when
        ``metadata.agent_mail_identity`` is non-empty), this helper derives
        the required ``AGENT_MAIL_*`` variables from the runtime's
        configuration and the :class:`AgentMetadata` for the agent rather
        than reading them directly from :mod:`os.environ`. This ensures
        that Agent Mail launch settings are explicit, testable, and tied to
        the runtime/swarm configuration instead of ambient environment
        state.

        Configuration invariants:

        * If no Agent Mail identity is configured for an agent, no
          ``AGENT_MAIL_*`` variables are added and nate_OHA is launched
          without Agent Mail integration.
        * If an Agent Mail identity is configured but the runtime/swarm
          Agent Mail configuration is incomplete or invalid, an
          :class:`AcpClientError` is raised and **no subprocess is
          launched**. This provides the required fail-fast behavior.
        """

        # Start from the current process environment but treat it purely as
        # a base for non-secret settings and unrelated variables. All
        # required Agent Mail configuration is derived from
        # :class:`RuntimeConfig` and :class:`AgentMetadata`.
        env: Dict[str, str] = dict(os.environ)

        # Runtime correlation variables used by nate_ntm and downstream
        # tooling. These are non-secret and safe to set by default.
        env.setdefault("NATE_NTM_PROJECT_PATH", str(self.config.project_path))
        env.setdefault("NATE_NTM_SWARM_ID", self.config.swarm_id)
        env.setdefault("NATE_NTM_AGENT_ID", agent_id)

        if metadata.conversation_id:
            env.setdefault("NATE_NTM_AGENT_CONVERSATION_ID", metadata.conversation_id)

        # If no Agent Mail identity is configured, leave AGENT_MAIL_* alone
        # and rely solely on the correlation variables above. This keeps
        # dev/test agents that do not use Agent Mail simple.
        if not metadata.agent_mail_identity:
            return env

        # Agent Mail integration is enabled from this point on. All
        # required configuration must be supplied via RuntimeConfig and
        # AgentMetadata.
        project = (self.config.agent_mail_project or "").strip()
        if not project:
            raise AcpClientError(
                "Agent Mail project is not configured; set RuntimeConfig.agent_mail_project "
                "(for example via NATE_NTM_AGENT_MAIL_PROJECT or AGENT_MAIL_PROJECT) "
                "before launching nate_OHA."
            )
        env["AGENT_MAIL_PROJECT"] = project

        identity = metadata.agent_mail_identity.strip()
        if not identity:
            raise AcpClientError(
                f"Agent Mail identity is empty for agent {agent_id!r}; "
                "set AgentMetadata.agent_mail_identity before launching nate_OHA."
            )
        env["AGENT_MAIL_AGENT"] = identity

        token = metadata.agent_mail_credentials_ref.strip() if metadata.agent_mail_credentials_ref else ""
        if not token:
            raise AcpClientError(
                f"Agent Mail token/credentials_ref not configured for agent {agent_id!r}; "
                "set AgentMetadata.agent_mail_credentials_ref before launching nate_OHA."
            )
        env["AGENT_MAIL_TOKEN"] = token

        upstream = (self.config.agent_mail_upstream_url or "").strip()
        if not upstream:
            raise AcpClientError(
                "Agent Mail upstream URL is not configured; set RuntimeConfig.agent_mail_upstream_url "
                "(for example via NATE_NTM_AGENT_MAIL_URL or AGENT_MAIL_UPSTREAM_URL) "
                "before launching nate_OHA."
            )
        env["AGENT_MAIL_UPSTREAM_URL"] = upstream

        return env

    def _make_process_event(
        self,
        *,
        agent_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> AgentEvent:
        """Construct a process-lifecycle :class:`AgentEvent` for callbacks."""

        return AgentEvent(
            event_id=f"{agent_id}:{event_type}:{uuid.uuid4()}",
            timestamp=datetime.utcnow(),
            agent_id=agent_id,
            source=AgentEventSource.ACP,
            type=event_type,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # Version and compatibility checks (FR-013, T211)
    # ------------------------------------------------------------------

    def _check_version(self) -> None:
        """Verify that the installed ``nate_OHA`` meets minimum requirements.

        This helper runs a lightweight self-check command (by default
        ``nate_OHA --version``) and parses its output to ensure that a
        supported version of nate_OHA is installed. If the check fails or an
        incompatible version is detected, :class:`AcpClientError` is raised
        with a clear diagnostic.
        """

        if self._version_checked:
            return

        cmd = [self.executable, "--version"]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError as exc:  # pragma: no cover - defensive
            raise AcpClientError(
                f"nate_OHA executable {self.executable!r} not found or not executable"
            ) from exc

        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip()
            if not message:
                message = f"exit code {proc.returncode}"
            raise AcpClientError(
                f"nate_OHA version check failed (command: {' '.join(cmd)}): {message}"
            )

        output = (proc.stdout or proc.stderr or "").strip()
        if not output:
            raise AcpClientError(
                f"nate_OHA version check produced no output (command: {' '.join(cmd)})"
            )

        version_tuple = self._parse_semver(output)
        if version_tuple is None:
            raise AcpClientError(
                "nate_OHA version check did not report a semantic version "
                f"(output was: {output!r})"
            )

        # Enforce a minimum version if configured via environment. This keeps
        # the runtime flexible while still satisfying FR-013.
        min_version_str = os.environ.get("NATE_OHA_MIN_VERSION", "").strip()
        if min_version_str:
            min_tuple = self._parse_semver(min_version_str)
            if min_tuple is None:
                raise AcpClientError(
                    "Invalid NATE_OHA_MIN_VERSION value "
                    f"{min_version_str!r}; expected a semantic version such as '0.5.0'."
                )

            if self._compare_versions(version_tuple, min_tuple) < 0:
                current_str = ".".join(str(p) for p in version_tuple)
                raise AcpClientError(
                    "Installed nate_OHA version "
                    f"{current_str} is below the minimum required version {min_version_str}."
                )

        # Record that we've successfully validated the version.
        self._version_checked = True
        self._detected_version = ".".join(str(p) for p in version_tuple)

    @staticmethod
    def _parse_semver(text: str) -> tuple[int, int, int] | None:
        """Extract the first ``MAJOR.MINOR.PATCH`` version from ``text``.

        Returns a tuple of integers on success or ``None`` if no semantic
        version can be found.
        """

        match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
        if not match:
            return None

        return int(match.group(1)), int(match.group(2)), int(match.group(3))

    @staticmethod
    def _compare_versions(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
        """Return -1, 0, or 1 depending on version ordering."""

        return (a > b) - (a < b)

