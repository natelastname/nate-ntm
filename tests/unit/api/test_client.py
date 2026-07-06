"""Unit tests for the JSON-RPC HTTP client helper (T009 remainder).

These tests focus on the small surface of :class:`JsonRpcHttpClient`
that is used by the Typer CLI and other local tooling. End-to-end
network behaviour is exercised by the integration quickstart tests.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from nate_ntm.api.client import JsonRpcClientError, JsonRpcHttpClient
from nate_ntm.api.jsonrpc import JSONRPC_VERSION


class _FakeResponse:
    def __init__(self, payload: Mapping[str, Any], status: int = 200, reason: str = "OK") -> None:
        self._payload = payload
        self.status = status
        self.reason = reason

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")


def test_http_client_call_async_sends_jsonrpc_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    connections: list[_FakeConnection] = []

    class _FakeConnection:
        def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.request_args: tuple[str, str, bytes, Mapping[str, Any]] | None = None
            self._decoded: Mapping[str, Any] | None = None
            connections.append(self)

        def request(self, method: str, url: str, body: bytes, headers: Mapping[str, Any]) -> None:
            import json

            self.request_args = (method, url, body, headers)
            self._decoded = json.loads(body.decode("utf-8"))

        def getresponse(self) -> _FakeResponse:
            assert self._decoded is not None
            payload = {
                "jsonrpc": JSONRPC_VERSION,
                "id": self._decoded["id"],
                "result": {"ok": True},
            }
            return _FakeResponse(payload)

        def close(self) -> None:  # pragma: no cover - trivial
            return None

    import http.client as http_client

    monkeypatch.setattr(http_client, "HTTPConnection", _FakeConnection)

    client = JsonRpcHttpClient(host="127.0.0.1", port=9999, timeout=5.0)
    response = asyncio.run(client.call_async("runtime.get_status", {"x": 1}, request_id=42))

    # Exactly one connection should have been created with the expected parameters.
    assert len(connections) == 1
    conn = connections[0]
    assert conn.host == "127.0.0.1"
    assert conn.port == 9999
    assert conn.timeout == 5.0

    assert conn.request_args is not None
    method, url, body, headers = conn.request_args
    assert method == "POST"
    assert url == "/jsonrpc"
    assert headers["Content-Type"] == "application/json"

    import json

    decoded = json.loads(body.decode("utf-8"))
    assert decoded == {
        "jsonrpc": JSONRPC_VERSION,
        "method": "runtime.get_status",
        "params": {"x": 1},
        "id": 42,
    }

    assert response["jsonrpc"] == JSONRPC_VERSION
    assert response["id"] == 42
    assert response["result"] == {"ok": True}




def test_http_client_call_for_result_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeConnection:
        def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def request(self, method: str, url: str, body: bytes, headers: Mapping[str, Any]) -> None:
            # Body is ignored for this test.
            return None

        def getresponse(self) -> _FakeResponse:
            payload = {
                "jsonrpc": JSONRPC_VERSION,
                "id": 1,
                "error": {"code": 123, "message": "Boom", "data": {"detail": "x"}},
            }
            return _FakeResponse(payload)

        def close(self) -> None:  # pragma: no cover - trivial
            return None

    import http.client as http_client

    monkeypatch.setattr(http_client, "HTTPConnection", _FakeConnection)

    client = JsonRpcHttpClient(host="127.0.0.1", port=9999, timeout=5.0)

    with pytest.raises(JsonRpcClientError) as excinfo:
        asyncio.run(client.call_for_result("runtime.get_status", {}))

    err = excinfo.value
    assert err.code == 123
    assert err.message == "Boom"
    assert err.data == {"detail": "x"}
