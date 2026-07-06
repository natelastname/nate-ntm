from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping

import pytest

from nate_ntm.api.client import JsonRpcClientError, JsonRpcHttpClient
from nate_ntm.api.models import AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult


class _FakeHttpClient(JsonRpcHttpClient):
    """Test double that bypasses the actual HTTP stack.

    The base implementation uses :mod:`http.client` in a background
    thread; for these tests we override :meth:`call_async` so we can
    drive the higher-level helpers without network traffic.
    """

    def __init__(self) -> None:
        super().__init__(host="127.0.0.1", port=8765)
        self.last_method: str | None = None
        self.last_params: Mapping[str, Any] | None = None
        self.response: Mapping[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {}}

    async def call_async(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> Mapping[str, Any]:  # type: ignore[override]
        self.last_method = method
        self.last_params = params or {}
        return self.response


def test_get_runtime_status_typed_success() -> None:
    client = _FakeHttpClient()
    expected: Dict[str, Any] = {
        "status": "running",
        "project_path": "/tmp/project",
        "swarm_id": "swarm-42",
        "agent_counts": {
            "total": 2,
            "starting": 0,
            "idle": 1,
            "running": 1,
            "waiting": 0,
            "failed": 0,
        },
    }
    client.response = {"jsonrpc": "2.0", "id": 1, "result": expected}

    result = asyncio.run(client.get_runtime_status())

    assert isinstance(result, RuntimeStatusResult)
    assert result.model_dump() == expected
    assert client.last_method == "runtime.get_status"
    assert client.last_params == {}


def test_get_swarm_overview_typed_success() -> None:
    client = _FakeHttpClient()
    expected: Dict[str, Any] = {
        "swarm_id": "swarm-42",
        "project_path": "/tmp/project",
        "runtime_status": "running",
        "agent_counts": {
            "total": 1,
            "starting": 0,
            "idle": 1,
            "running": 0,
            "waiting": 0,
            "failed": 0,
        },
        "agents": [
            {
                "agent_id": "nav-1",
                "display_name": "Navigator",
                "status": "idle",
                "has_unread_mail": False,
                "last_error": None,
            }
        ],
    }
    client.response = {"jsonrpc": "2.0", "id": 1, "result": expected}

    result = asyncio.run(client.get_swarm_overview())

    assert isinstance(result, SwarmOverviewResult)
    assert result.model_dump() == expected
    assert client.last_method == "swarm.get_overview"
    assert client.last_params == {}


def test_get_agent_detail_typed_success() -> None:
    client = _FakeHttpClient()
    expected: Dict[str, Any] = {
        "agent": {
            "agent_id": "nav-1",
            "display_name": "Navigator",
            "status": "idle",
            "agent_mail_identity": "nav-1@example.test",
            "conversation_id": "conv-1",
            "last_error": None,
        },
        "events": [
            {
                "event_id": "evt-1",
                "timestamp": "2024-01-01T00:00:00Z",
                "agent_id": "nav-1",
                "source": "runtime",
                "type": "started",
                "payload": {"foo": "bar"},
            }
        ],
    }
    client.response = {"jsonrpc": "2.0", "id": 1, "result": expected}

    result = asyncio.run(client.get_agent_detail("nav-1", max_events=10))

    assert isinstance(result, AgentDetailResult)
    assert result.model_dump() == expected
    assert client.last_method == "agent.get_detail"
    assert client.last_params == {"agent_id": "nav-1", "max_events": 10}


def test_typed_helpers_surface_jsonrpc_errors() -> None:
    client = _FakeHttpClient()
    client.response = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": 1100, "message": "Runtime state conflict", "data": {"state": "stopped"}},
    }

    with pytest.raises(JsonRpcClientError) as excinfo:
        asyncio.run(client.get_runtime_status())

    assert excinfo.value.code == 1100
    assert excinfo.value.message == "Runtime state conflict"
    assert excinfo.value.data == {"state": "stopped"}
