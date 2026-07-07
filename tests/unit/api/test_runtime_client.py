from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, Mapping

import pytest

from nate_ntm.api.client import JsonRpcHttpClient
from nate_ntm.api.models import AgentDetailEvent, AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult
from nate_ntm.api.runtime_client import EventsNotify, RuntimeClient


class _FakeHttpClient(JsonRpcHttpClient):
    """Test double that bypasses the actual HTTP stack.

    This mirrors the approach used in ``test_client_typed.py`` but is
    specialised for exercising :class:`RuntimeClient` behaviour.
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


def test_runtime_client_typed_helpers_delegate_to_underlying_jsonrpc_client() -> None:
    fake = _FakeHttpClient()
    client = RuntimeClient(rpc_client=fake)

    # runtime.get_status -------------------------------------------------
    expected_status: Dict[str, Any] = {
        "status": "Running",
        "project_path": "/tmp/project",
        "swarm_id": "swarm-1",
        "agent_counts": {
            "total": 1,
            "starting": 0,
            "idle": 1,
            "running": 0,
            "waiting": 0,
            "failed": 0,
        },
    }
    fake.response = {"jsonrpc": "2.0", "id": 1, "result": expected_status}

    status = asyncio.run(client.get_runtime_status())

    assert isinstance(status, RuntimeStatusResult)
    assert status.model_dump() == expected_status
    assert fake.last_method == "runtime.get_status"
    assert fake.last_params == {}

    # swarm.get_overview -------------------------------------------------
    expected_overview: Dict[str, Any] = {
        "swarm_id": "swarm-1",
        "project_path": "/tmp/project",
        "runtime_status": "Running",
        "agent_counts": expected_status["agent_counts"],
        "agents": [
            {
                "agent_id": "nav-1",
                "display_name": "Navigator 1",
                "status": "Idle",
                "has_unread_mail": False,
                "last_error": None,
            }
        ],
    }
    fake.response = {"jsonrpc": "2.0", "id": 1, "result": expected_overview}

    overview = asyncio.run(client.get_swarm_overview())

    assert isinstance(overview, SwarmOverviewResult)
    assert overview.model_dump() == expected_overview
    assert fake.last_method == "swarm.get_overview"
    assert fake.last_params == {}

    # agent.get_detail ---------------------------------------------------
    expected_detail: Dict[str, Any] = {
        "agent": {
            "agent_id": "nav-1",
            "display_name": "Navigator 1",
            "status": "Idle",
            "agent_mail_identity": "nav-1@example.test",
            "conversation_id": "conv-1",
            "last_error": None,
        },
        "events": [
            {
                "event_id": "evt-1",
                "timestamp": "2026-07-03T12:00:00Z",
                "agent_id": "nav-1",
                "source": "Runtime",
                "type": "AgentFailed",
                "payload": {"error": "boom"},
            }
        ],
    }
    fake.response = {"jsonrpc": "2.0", "id": 1, "result": expected_detail}

    detail = asyncio.run(client.get_agent_detail("nav-1", max_events=5))

    assert isinstance(detail, AgentDetailResult)
    assert detail.model_dump() == expected_detail
    assert fake.last_method == "agent.get_detail"
    assert fake.last_params == {"agent_id": "nav-1", "max_events": 5}


def test_subscribe_and_unsubscribe_events_wrap_jsonrpc_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpClient()
    client = RuntimeClient(rpc_client=fake)

    # Simulate events.subscribe returning a subscription_id.
    fake.response = {"jsonrpc": "2.0", "id": 1, "result": {"subscription_id": "sub-1"}}

    sub_id = asyncio.run(client.subscribe_events(agent_ids=["nav-1"], include_runtime=True))

    assert sub_id == "sub-1"
    assert fake.last_method == "events.subscribe"
    assert fake.last_params == {"agent_ids": ["nav-1"], "include_runtime": True}

    # Simulate events.unsubscribe returning a small result payload.
    fake.response = {"jsonrpc": "2.0", "id": 1, "result": {"unsubscribed": True}}

    result = asyncio.run(client.unsubscribe_events("sub-1"))
    assert result == {"unsubscribed": True}
    assert fake.last_method == "events.unsubscribe"
    assert fake.last_params == {"subscription_id": "sub-1"}


def test_iter_events_yields_typed_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """iter_events parses events.notify messages into EventsNotify objects.

    This test stubs out both the JSON-RPC layer and the WebSocket transport
    so that no real network traffic is involved.
    """

    async def main() -> None:
        fake_rpc = _FakeHttpClient()
        client = RuntimeClient(rpc_client=fake_rpc)

        # When subscribe_events is called, return a deterministic subscription_id.
        async def _fake_call_for_result(
            method: str,
            params: Mapping[str, Any] | None = None,
            *,
            request_id: int = 1,
        ) -> Mapping[str, Any]:  # type: ignore[override]
            fake_rpc.last_method = method
            fake_rpc.last_params = params or {}
            if method == "events.subscribe":
                return {"subscription_id": "sub-42"}
            elif method == "events.unsubscribe":
                return {"unsubscribed": True}
            raise AssertionError(f"Unexpected method {method!r} in fake_call_for_result")

        monkeypatch.setattr(fake_rpc, "call_for_result", _fake_call_for_result)

        # Stub out websockets.connect with a fake context manager that sends
        # one well-formed notification and then exits.
        class _FakeWebSocket:
            def __init__(self, messages: Iterable[str]) -> None:
                self._messages = iter(messages)
                self.sent: list[str] = []

            async def __aenter__(self) -> "_FakeWebSocket":  # type: ignore[override]
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
                return None

            async def send(self, text: str) -> None:
                self.sent.append(text)

            async def recv(self) -> str:
                # Yield messages in order; this test will stop consuming after
                # the first notification, so we don't need special shutdown
                # behaviour here.
                return next(self._messages)

        # Build a single well-formed events.notify message.
        event_payload = {
            "event_id": "evt-1",
            "timestamp": "2026-07-03T12:00:00Z",
            "agent_id": "nav-1",
            "source": "Runtime",
            "type": "AgentFailed",
            "payload": {"error": "boom"},
        }
        notify_message = {
            "jsonrpc": "2.0",
            "method": "events.notify",
            "params": {"subscription_id": "sub-42", "event": event_payload},
        }

        def _fake_connect(uri: str) -> _FakeWebSocket:  # type: ignore[override]
            # The client should connect to /events on the configured host/port.
            assert uri.endswith("/events")
            text = json_dumps(notify_message)
            return _FakeWebSocket([text])

        # Local helper to avoid importing json at module import time.
        def json_dumps(obj: Any) -> str:
            import json

            return json.dumps(obj)

        import nate_ntm.api.runtime_client as runtime_client_module

        monkeypatch.setattr(runtime_client_module.websockets, "connect", _fake_connect)

        # Consume a single notification from iter_events and assert that it is
        # parsed into the expected EventsNotify/AgentDetailEvent pair.
        notifications: list[EventsNotify] = []

        async for note in client.iter_events(agent_ids=["nav-1"], reconnect=False):
            notifications.append(note)
            break  # Stop after the first notification

        assert len(notifications) == 1
        note = notifications[0]
        assert isinstance(note, EventsNotify)
        assert note.subscription_id == "sub-42"
        assert isinstance(note.event, AgentDetailEvent)
        assert note.event.event_id == "evt-1"
        assert note.event.agent_id == "nav-1"
        assert note.event.type == "AgentFailed"


    asyncio.run(main())

