from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from acp import RequestError

from nate_ntm.runtime.acp_client import AcpAgentSession, NateOhaAcpClient


class _Connection:
    async def prompt(self, session_id: str, prompt: object) -> None:
        raise RequestError(-32603, "Internal error", {"reason": "provider failed"})


@pytest.mark.asyncio
async def test_prompt_preserves_downstream_acp_error_details(caplog) -> None:
    client = NateOhaAcpClient(config=SimpleNamespace(nate_oha_executable="nate-oha"))  # type: ignore[arg-type]
    client._sessions["agent-a"] = AcpAgentSession(
        agent_id="agent-a",
        conversation_id="conversation-a",
        process=cast(object, SimpleNamespace()),  # type: ignore[arg-type]
        connection=cast(object, _Connection()),  # type: ignore[arg-type]
        protocol_client=cast(object, SimpleNamespace()),  # type: ignore[arg-type]
        status="running",
    )

    with caplog.at_level("ERROR"), pytest.raises(RequestError) as raised:
        await client.prompt("agent-a", "hello")

    assert raised.value.code == -32603
    assert raised.value.data == {
        "agent_id": "agent-a",
        "conversation_id": "conversation-a",
        "downstream_code": -32603,
        "downstream_data": {"reason": "provider failed"},
    }
    assert "Prompt failed for agent 'agent-a'" in caplog.text
    assert "provider failed" in caplog.text
