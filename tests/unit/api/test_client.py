"""Unit tests for the JSON-RPC/WebSocket client helper (T009 remainder).

These tests focus on the small surface of :class:`JsonRpcWebSocketClient`
that is used by the Typer CLI and other local tooling. Network behavior is
covered more extensively by `tests/unit/api/test_jsonrpc_ws.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from nate_ntm.api.client import JsonRpcClientError, JsonRpcWebSocketClient
from nate_ntm.api.jsonrpc import JSONRPC_VERSION


class _FakeWebSocket:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self._response = response
        self.sent_messages: list[str] = []

    async def __aenter__(self) -> "_FakeWebSocket":  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
        return None

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def recv(self) -> str:
        import json

        return json.dumps(self._response)


def test_client_call_async_sends_jsonrpc_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_uri: list[str] = []

    def fake_connect(uri: str, open_timeout: float | None = None) -> _FakeWebSocket:  # type: ignore[override]
        recorded_uri.append(uri)
        # Echo back a simple result so the client returns normally.
        return _FakeWebSocket({"jsonrpc": JSONRPC_VERSION, "id": 1, "result": {"ok": True}})

    import nate_ntm.api.client as client_mod

    monkeypatch.setattr(client_mod.websockets, "connect", fake_connect)

    client = JsonRpcWebSocketClient(host="127.0.0.1", port=9999, timeout=5.0)
    response = asyncio.run(client.call_async("runtime.get_status", {"x": 1}, request_id=42))

    assert recorded_uri == ["ws://127.0.0.1:9999"]
    assert response["jsonrpc"] == JSONRPC_VERSION
    assert response["id"] == 1
    assert response["result"] == {"ok": True}


def test_client_call_for_result_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_connect(uri: str, open_timeout: float | None = None) -> _FakeWebSocket:  # type: ignore[override]
        return _FakeWebSocket(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": 1,
                "error": {"code": 123, "message": "Boom", "data": {"detail": "x"}},
            }
        )

    import nate_ntm.api.client as client_mod

    monkeypatch.setattr(client_mod.websockets, "connect", fake_connect)

    client = JsonRpcWebSocketClient(host="127.0.0.1", port=9999, timeout=5.0)

    with pytest.raises(JsonRpcClientError) as excinfo:
        asyncio.run(client.call_for_result("runtime.get_status", {}))

    err = excinfo.value
    assert err.code == 123
    assert err.message == "Boom"
    assert err.data == {"detail": "x"}
