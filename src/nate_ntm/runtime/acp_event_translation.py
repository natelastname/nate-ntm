"""ACP → runtime event translation helpers.

This module isolates translation of ACP SDK session updates into the
runtime's :class:`~nate_ntm.runtime.events.AgentEvent` representation.

The rest of the runtime should treat ACP as an opaque event source and
work exclusively with :class:`AgentEvent` values. Keeping the
translation logic here avoids leaking ACP SDK models throughout the
codebase and makes it easier to test representative mappings in
isolation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping

from .events import AgentEvent, AgentEventSource


def _model_to_payload(update: Any) -> Mapping[str, Any]:
    """Return a JSON-serializable representation of an ACP model instance.

    The ACP SDK uses Pydantic models for protocol types. For those
    models we prefer ``model_dump(by_alias=True)`` so that field names
    match the wire protocol (for example ``sessionUpdate`` and
    ``messageId``).

    For non-Pydantic objects this falls back to ``dict`` when possible
    and finally to a simple ``repr`` wrapper so that callers always
    receive a mapping that can be serialized to JSON.
    """

    if hasattr(update, "model_dump"):
        # Pydantic v2 models provide model_dump; by_alias=True yields
        # wire-compatible field names.
        return update.model_dump(by_alias=True)  # type: ignore[no-any-return]

    if isinstance(update, dict):
        return update

    # Best-effort fallback for unexpected objects.
    return {"value": repr(update)}


def _update_kind(update: Any) -> str:
    """Infer the ACP update kind string for an ``update`` instance.

    ACP ``SessionNotification.update`` models expose a ``session_update``
    attribute (with JSON alias ``sessionUpdate``) whose value is a
    lower-case string such as ``"user_message_chunk"`` or
    ``"tool_call_update"``. When that attribute is not present we fall
    back to the Python class name.
    """

    kind: str | None = None

    # Pydantic exposes both the Pythonic ``session_update`` and the JSON
    # alias ``sessionUpdate`` on model instances; prefer the snake_case
    # form but accept either.
    if hasattr(update, "session_update"):
        kind = getattr(update, "session_update")  # type: ignore[assignment]
    elif hasattr(update, "sessionUpdate"):
        kind = getattr(update, "sessionUpdate")  # type: ignore[assignment]

    if isinstance(kind, str) and kind:
        return kind

    # Fallback: derive a best-effort kind string from the class name.
    return type(update).__name__


def translate_acp_update(
    *,
    agent_id: str,
    session_id: str,
    update: Any,
    sequence: int,
    timestamp: datetime | None = None,
) -> AgentEvent:
    """Translate a single ACP session ``update`` into an :class:`AgentEvent`.

    Parameters
    ----------
    agent_id:
        Identifier of the agent this event belongs to.

    session_id:
        Canonical ACP session identifier associated with the update.

    update:
        The ACP SDK model instance carried in ``SessionNotification.update``.
        Callers should treat this as opaque; this helper converts it into
        a JSON-serializable mapping so that ACP types do not escape into
        the rest of the runtime.

    sequence:
        Monotonically increasing sequence number for this agent/session
        pair. Callers are free to choose their own sequencing scheme;
        this value is used to construct a stable, deterministic
        ``event_id``.

    timestamp:
        Timestamp to use for the event. When omitted, the current UTC
        time is used.

    Returns
    -------
    AgentEvent
        Runtime event suitable for appending to an ``AgentEventStream``
        and serializing through the runtime APIs.
    """

    if sequence <= 0:
        raise ValueError("sequence must be positive")

    if timestamp is None:
        timestamp = datetime.utcnow()

    kind = _update_kind(update)
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "update": _model_to_payload(update),
    }

    event_type = f"acp.{kind}"

    event_id = f"{agent_id}:{session_id}:{sequence}"

    return AgentEvent(
        event_id=event_id,
        timestamp=timestamp,
        agent_id=agent_id,
        source=AgentEventSource.ACP,
        type=event_type,
        payload=payload,
    )
