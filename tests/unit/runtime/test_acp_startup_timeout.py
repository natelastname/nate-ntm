from types import SimpleNamespace

import pytest
from acp import RequestError

from nate_ntm.runtime.acp_client import NateOhaAcpClient


@pytest.mark.asyncio
async def test_startup_phase_timeout_reports_agent_and_phase(caplog) -> None:
    client = NateOhaAcpClient(
        config=SimpleNamespace(nate_oha_executable="nate-oha"),  # type: ignore[arg-type]
        startup_timeout_seconds=0.001,
    )

    async def never_finishes() -> None:
        await __import__("asyncio").sleep(10)

    with pytest.raises(RequestError) as raised:
        await client._startup_phase(
            "agent-a",
            "agent_session_load",
            never_finishes(),
            operation="load",
            conversation_id="conversation-a",
        )

    assert raised.value.data == {
        "agent_id": "agent-a",
        "phase": "agent_session_load",
        "timeout_seconds": 0.001,
        "operation": "load",
        "conversation_id": "conversation-a",
    }
    assert "agent_session_load_begin agent_id=agent-a" in caplog.text
    assert "agent_session_load_timeout agent_id=agent-a" in caplog.text
