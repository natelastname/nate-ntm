"""OpenHands ACP client adapters for the swarm runtime (T015/T102).

The nate_ntm runtime owns all ACP (Agent Control Protocol) connections
for agents in a swarm. This module defines a small adapter interface
that the runtime and scheduler use to interact with an OpenHands server.

Two concrete implementations are provided:

* :class:`FakeAcpClient` – an in-memory, dev-mode implementation used in
  unit/integration tests that simulates conversations and turn
  identifiers without performing any network I/O.
* :class:`OpenHandsAcpClient` – a production-oriented adapter that
  speaks the HTTP surface of an OpenHands-compatible ACP server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config.runtime_config import RuntimeConfig

__all__ = ["AcpClientError", "BaseAcpClient", "FakeAcpClient", "OpenHandsAcpClient"]


class AcpClientError(RuntimeError):
    """Base error type for ACP adapter failures."""


class BaseAcpClient:
    """Abstract interface for the OpenHands ACP client.

    The interface is intentionally lean for the MVP:

    * Ensure a control-protocol conversation exists per agent.
    * Optionally, start new turns within that conversation and surface
      identifiers back to the runtime.

    Concrete implementations are expected to be **runtime-owned** and
    reused for the lifetime of the process.
    """

    # The following methods define the public contract. Concrete
    # implementations *must* override them.

    def ensure_conversation(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Ensure a control-protocol conversation exists for ``agent_id``.

        The returned string is an opaque conversation identifier. The
        method must be **idempotent**: repeated calls for the same
        ``agent_id`` MUST return the same conversation ID.
        """

        raise NotImplementedError

    def start_turn(self, agent_id: str) -> str:  # pragma: no cover - abstract
        """Start a new ACP turn for ``agent_id`` and return its ID.

        The exact semantics of a "turn" are defined by the ACP spec and
        the concrete implementation. The fake client simply allocates a
        monotonically increasing identifier per agent.
        """

        raise NotImplementedError


@dataclass(slots=True)
class FakeAcpClient(BaseAcpClient):
    """In-memory ACP client for tests and dev-mode.

    This implementation does **not** perform any network I/O. It keeps
    a minimal in-memory model of:

    * A per-agent conversation identifier.
    * A monotonically increasing counter of turn IDs per agent.

    It is sufficient for unit tests and early integration tests that
    need stable, realistic-looking conversation and turn identifiers
    without talking to a real OpenHands server.
    """

    config: RuntimeConfig

    _conversations: Dict[str, str] = field(default_factory=dict)
    _turn_counters: Dict[str, int] = field(default_factory=dict)

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

    def start_turn(self, agent_id: str) -> str:
        # Ensure a conversation exists; many callers will already have
        # done this explicitly but the helper is cheap and idempotent.
        self.ensure_conversation(agent_id)

        counter = self._turn_counters.get(agent_id, 0) + 1
        self._turn_counters[agent_id] = counter
        turn_id = f"fake-turn:{agent_id}:{counter}"
        return turn_id


@dataclass(slots=True)
class OpenHandsAcpClient(BaseAcpClient):
    """Production OpenHands-compatible ACP adapter over HTTP (T102).

    This implementation speaks the ACP HTTP/OpenAPI surface defined in
    ``reference/acp-spec/openapi.json`` (v0.2.3). It focuses on the minimal
    operations required by the runtime today:

    * Ensure a per-agent conversation (ACP thread) exists.
    * Start new runs on that thread and return their identifiers.

    The adapter is **runtime-owned** and is constructed by
    :func:`nate_ntm.runtime.adapters.create_runtime_adapters` when
    ``AdapterKind.REAL`` is selected for ACP.
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

    def start_turn(self, agent_id: str) -> str:
        """Start a new stateful ACP run for ``agent_id``.

        This creates a background run on the agent's thread using
        ``POST /threads/{thread_id}/runs`` and returns the ``run_id`` from the
        ACP ``RunStateful`` response.
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
