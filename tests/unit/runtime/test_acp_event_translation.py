from __future__ import annotations

from datetime import datetime

import pytest

from acp.schema import UsageUpdate, UserMessageChunk, ToolCallStart

from nate_ntm.runtime.acp_event_translation import translate_acp_update
from nate_ntm.runtime.events import AgentEventSource


def _make_timestamp() -> datetime:
    # Fixed timestamp for deterministic assertions.
    return datetime(2024, 1, 1, 12, 0, 0)


def test_translate_user_message_chunk_produces_agent_event() -> None:
    agent_id = "agent-1"
    session_id = "session-xyz"
    ts = _make_timestamp()

    update = UserMessageChunk(
        sessionUpdate="user_message_chunk",
        content={"type": "text", "text": "hello"},
    )

    event = translate_acp_update(
        agent_id=agent_id,
        session_id=session_id,
        update=update,
        sequence=1,
        timestamp=ts,
    )

    assert event.agent_id == agent_id
    assert event.source is AgentEventSource.ACP
    assert event.type == "acp.user_message_chunk"
    assert event.event_id == f"{agent_id}:{session_id}:1"
    assert event.timestamp is ts

    payload = event.payload
    assert payload["session_id"] == session_id

    update_payload = payload["update"]
    assert update_payload["sessionUpdate"] == "user_message_chunk"
    assert update_payload["content"]["type"] == "text"
    assert update_payload["content"]["text"] == "hello"


def test_translate_tool_call_start_uses_acp_kind_for_event_type() -> None:
    agent_id = "agent-2"
    session_id = "session-abc"
    ts = _make_timestamp()

    update = ToolCallStart(
        toolCallId="call-1",
        title="run command",
        sessionUpdate="tool_call",
    )

    event = translate_acp_update(
        agent_id=agent_id,
        session_id=session_id,
        update=update,
        sequence=7,
        timestamp=ts,
    )

    assert event.type == "acp.tool_call"
    assert event.event_id == f"{agent_id}:{session_id}:7"

    payload = event.payload
    assert payload["session_id"] == session_id

    update_payload = payload["update"]
    assert update_payload["sessionUpdate"] == "tool_call"
    assert update_payload["toolCallId"] == "call-1"
    assert update_payload["title"] == "run command"


def test_translate_usage_update_round_trips_basic_fields() -> None:
    agent_id = "agent-3"
    session_id = "session-usage"
    ts = _make_timestamp()

    update = UsageUpdate(
        used=128,
        size=4096,
        sessionUpdate="usage_update",
    )

    event = translate_acp_update(
        agent_id=agent_id,
        session_id=session_id,
        update=update,
        sequence=3,
        timestamp=ts,
    )

    assert event.type == "acp.usage_update"

    payload = event.payload
    update_payload = payload["update"]
    assert update_payload["sessionUpdate"] == "usage_update"
    assert update_payload["used"] == 128
    assert update_payload["size"] == 4096


def test_translate_acp_update_rejects_non_positive_sequence() -> None:
    update = UsageUpdate(used=0, size=0, sessionUpdate="usage_update")

    with pytest.raises(ValueError):
        translate_acp_update(
            agent_id="agent-x",
            session_id="session-x",
            update=update,
            sequence=0,
        )
