from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

import pytest

from acp import RequestError
from acp.interfaces import ClientCapabilities
from acp.schema import UserMessageChunk

from nate_ntm.runtime.acp_protocol_client import (
    NATE_NTM_CLIENT_CAPABILITIES,
    NateNtmAcpProtocolClient,
)
from nate_ntm.runtime.acp_types import SessionUpdate


class _UpdateCollector:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, SessionUpdate, datetime]] = []

    def __call__(
        self,
        agent_id: str,
        session_id: str,
        update: SessionUpdate,
        received_at: datetime,
    ) -> None:
        self.calls.append((agent_id, session_id, update, received_at))


def _fixed_clock() -> datetime:
    return datetime(2024, 1, 1, 12, 0, 0)


@pytest.mark.asyncio
async def test_session_update_forwards_typed_update() -> None:
    collector = _UpdateCollector()
    client = NateNtmAcpProtocolClient(
        agent_id="agent-1",
        on_session_update=collector,
        clock=_fixed_clock,
    )

    update = UserMessageChunk(
        sessionUpdate="user_message_chunk",
        content={"type": "text", "text": "hi"},
    )

    await client.session_update(session_id="session-123", update=update)

    assert len(collector.calls) == 1
    agent_id, session_id, received_update, ts = collector.calls[0]

    assert agent_id == "agent-1"
    assert session_id == "session-123"
    assert received_update is update
    assert ts == _fixed_clock()


@pytest.mark.asyncio
async def test_request_permission_reports_unsupported_capability() -> None:
    client = NateNtmAcpProtocolClient(agent_id="agent-x", on_session_update=lambda *args, **kwargs: None)

    with pytest.raises(RequestError) as exc_info:
        await client.request_permission("session-x", object(), [], reason="test")

    err = exc_info.value
    assert err.code == -32600  # invalid_request
    # The RequestError carries a structured reason in its data payload.
    assert isinstance(err.data, dict)
    assert err.data.get("reason") == "request_permission is not supported by this client"


@pytest.mark.asyncio
async def test_ext_method_reports_method_not_found() -> None:
    client = NateNtmAcpProtocolClient(agent_id="agent-x", on_session_update=lambda *args, **kwargs: None)

    with pytest.raises(RequestError) as exc_info:
        await client.ext_method("custom/unknown", {"foo": "bar"})

    err = exc_info.value
    assert err.code == -32601  # method_not_found
    assert isinstance(err.data, dict)
    assert err.data.get("method") == "custom/unknown"


def test_nate_ntm_client_capabilities_is_explicit_model_instance() -> None:
    # The exported capabilities object should be a concrete
    # `ClientCapabilities` model instance that can be serialized and
    # round-tripped.
    assert isinstance(NATE_NTM_CLIENT_CAPABILITIES, ClientCapabilities)

    # Suppress pydantic warnings so the test output stays clean.
    data = NATE_NTM_CLIENT_CAPABILITIES.model_dump(warnings=False)
    # The defaults currently disable filesystem and terminal features,
    # which matches the behavior of NateNtmAcpProtocolClient.
    assert data["fs"]["read_text_file"] is False
    assert data["fs"]["write_text_file"] is False
    assert data["terminal"] is False
