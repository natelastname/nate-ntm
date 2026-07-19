"""ACP SDK client implementation used by the runtime.

`NateNtmAcpProtocolClient` implements the ACP :class:`~acp.interfaces.Client`
interface and is responsible for receiving typed ACP session updates from the
SDK and forwarding them into the runtime's per-session update stream
machinery.

All ACP-specific models are kept behind this boundary so the rest of the
runtime can work with the internal :class:`SessionUpdate` alias without
depending directly on the ACP SDK import paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from acp import RequestError
from acp.interfaces import Client, ClientCapabilities

from .acp_types import SessionUpdate

__all__ = [
    "NATE_NTM_CLIENT_CAPABILITIES",
    "NateNtmAcpProtocolClient",
]

# Public capabilities object advertised during ACP initialization.
#
# The default constructed `ClientCapabilities` instance explicitly
# disables optional features (file system operations, terminal control,
# plan updates, elicitation, NES, etc.). This accurately reflects the
# current runtime behavior: nate_ntm does not yet implement these
# capabilities at the client layer.
NATE_NTM_CLIENT_CAPABILITIES: ClientCapabilities = ClientCapabilities()


# Type of the callback used to forward typed session updates from the ACP SDK
# into the runtime's per-session update stream machinery. Using a synchronous
# callable keeps the implementation simple and avoids introducing additional
# async hops in the ACP callback path.
SessionUpdateSink = Callable[[str, str, SessionUpdate, datetime], None]


class NateNtmAcpProtocolClient(Client):
    """ACP client implementation used by :mod:`nate_ntm`.

    Parameters
    ----------
    agent_id:
        Identifier of the agent this client instance is associated with.

    on_session_update:
        Callback invoked with each typed :class:`SessionUpdate` delivered
        by the ACP SDK. The callback receives ``agent_id``, ``session_id``,
        the concrete ``SessionUpdate`` instance, and a receipt timestamp.

    clock:
        Optional callable returning the current time. This is primarily
        useful for tests that need deterministic timestamps.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        on_session_update: SessionUpdateSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._on_session_update = on_session_update
        self._clock = clock or datetime.utcnow

        # The last ACP session identifier observed via `session_update`.
        # This is advisory only; the canonical conversation identity is
        # owned by nate-oha / ACP and surfaced through the higher-level
        # NateOhaAcpClient adapter.
        self._session_id: str | None = None

    # ------------------------------------------------------------------
    # Core ACP callbacks
    # ------------------------------------------------------------------

    async def session_update(self, session_id: str, update: SessionUpdate, **kwargs: Any) -> None:  # type: ignore[override]
        """Handle a single ACP ``session/update`` notification.

        The ACP SDK decodes the wire payload into a concrete Pydantic
        model instance before calling this method. We treat the model as
        opaque here and forward it, together with identity metadata and a
        receipt timestamp, into the runtime's per-session update stream.
        """

        # Remember the most recent session identifier for introspection.
        self._session_id = session_id

        self._on_session_update(
            self._agent_id,
            session_id,
            update,
            self._clock(),
        )

    # ------------------------------------------------------------------
    # Permission, filesystem, terminal, and elicitation callbacks
    # ------------------------------------------------------------------

    async def request_permission(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Respond to permission prompts from the agent.

        The current nate_ntm runtime does not implement interactive
        permission flows at the ACP layer. We advertise no such
        capabilities and respond with a structured ACP error if an agent
        still attempts to use them.
        """

        raise RequestError.invalid_request({"reason": "request_permission is not supported by this client"})

    async def read_text_file(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``fs/read_text_file`` requests.

        File system operations are not currently exposed through the
        nate_ntm runtime. Agents should not invoke these methods because
        the advertised :data:`NATE_NTM_CLIENT_CAPABILITIES` disable the
        corresponding capabilities.
        """

        raise RequestError.invalid_request({"reason": "fs/read_text_file is not supported by this client"})

    async def write_text_file(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``fs/write_text_file`` requests.

        See :meth:`read_text_file` for rationale.
        """

        raise RequestError.invalid_request({"reason": "fs/write_text_file is not supported by this client"})

    async def create_terminal(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``terminal/create`` requests.

        Terminal management is not wired into the nate_ntm runtime.
        """

        raise RequestError.invalid_request({"reason": "terminal/create is not supported by this client"})

    async def terminal_output(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``terminal/output`` notifications from the agent.

        Because terminal sessions are not supported, this method should
        never be invoked.
        """

        raise RequestError.invalid_request({"reason": "terminal/output is not supported by this client"})

    async def release_terminal(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``terminal/release`` requests."""

        raise RequestError.invalid_request({"reason": "terminal/release is not supported by this client"})

    async def wait_for_terminal_exit(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``terminal/wait_for_exit`` requests."""

        raise RequestError.invalid_request({"reason": "terminal/wait_for_exit is not supported by this client"})

    async def kill_terminal(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``terminal/kill`` requests."""

        raise RequestError.invalid_request({"reason": "terminal/kill is not supported by this client"})

    async def create_elicitation(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``elicitation/create`` requests.

        Elicitation flows (for example form-based prompts) are not
        currently supported by the runtime.
        """

        raise RequestError.invalid_request({"reason": "elicitation/create is not supported by this client"})

    async def complete_elicitation(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle ``elicitation/complete`` requests."""

        raise RequestError.invalid_request({"reason": "elicitation/complete is not supported by this client"})

    # ------------------------------------------------------------------
    # Extension method hooks
    # ------------------------------------------------------------------

    async def ext_method(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:  # type: ignore[override]
        """Handle calls to ``client/ext_*`` methods.

        The current runtime does not expose any extension methods; report
        them as missing so the agent receives a clear JSON-RPC error.
        """

        raise RequestError.method_not_found(method)

    async def ext_notification(self, method: str, params: Mapping[str, Any]) -> None:  # type: ignore[override]
        """Handle ``client/ext_*`` notifications.

        Because extension methods are not supported we simply ignore
        these notifications.
        """

        return None

    # ------------------------------------------------------------------
    # Connection lifecycle hooks
    # ------------------------------------------------------------------

    def on_connect(self, conn: Any) -> None:  # type: ignore[override]
        """Connection-established hook.

        The ACP SDK calls this method once the JSON-RPC connection is
        ready. The runtime does not currently need to perform any action
        here, but the hook is retained for future diagnostics or
        instrumentation needs.
        """

        # No-op by design.
        return None
