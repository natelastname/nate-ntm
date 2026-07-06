"""Unit tests for the Typer-based `api call` command (T009).

These tests exercise parameter parsing and JSON-RPC invocation behavior
for `nate_ntm.cli.api_call` without requiring a real HTTP server.

Network interactions are stubbed by replacing
:class:`JsonRpcHttpClient` with a small fake that records calls and
returns predefined responses.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from typer.testing import CliRunner

from nate_ntm.api.client import JsonRpcClientError
from nate_ntm.cli import app


runner = CliRunner()


class _FakeClient:
    """Test double for :class:`JsonRpcHttpClient`.

    It captures the last call and returns a configurable ``result`` or
    raises :class:`JsonRpcClientError` to simulate JSON-RPC error
    envelopes.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float | None = None) -> None:  # type: ignore[assignment]
        self.host = host
        self.port = port
        self.timeout = timeout
        self.last_method: str | None = None
        self.last_params: Mapping[str, Any] | None = None
        # Default success result; tests can override this or ``error``.
        self.result: Mapping[str, Any] = {"ok": True}
        self.error: Mapping[str, Any] | None = None

    async def call_for_result(self, method: str, params: Mapping[str, Any] | None = None, *, request_id: int = 1) -> Mapping[str, Any]:  # type: ignore[override]
        self.last_method = method
        self.last_params = params or {}
        if self.error is not None:
            raise JsonRpcClientError(
                code=int(self.error.get("code", -1)),
                message=str(self.error.get("message", "")),
                data=self.error.get("data"),
            )
        return self.result


def test_api_call_runtime_get_status_success(monkeypatch) -> None:
    from nate_ntm import cli as cli_mod

    fake = _FakeClient()
    # Provide a payload that matches the ``RuntimeStatusResult`` schema so
    # the CLI's typed normalisation path is exercised.
    expected: Dict[str, Any] = {
        "status": "running",
        "project_path": "/tmp/project",
        "swarm_id": "swarm-001",
        "agent_counts": {
            "total": 3,
            "starting": 1,
            "idle": 1,
            "running": 1,
            "waiting": 0,
            "failed": 0,
        },
    }
    fake.result = expected

    monkeypatch.setattr(cli_mod, "JsonRpcHttpClient", lambda host, port: fake)

    result = runner.invoke(app, ["api", "call", "runtime.get_status"])

    assert result.exit_code == 0, result.output
    assert fake.last_method == "runtime.get_status"
    assert fake.last_params == {}

    payload = json.loads(result.stdout)
    assert payload == expected


def test_api_call_parses_params_and_surfaces_jsonrpc_errors(monkeypatch) -> None:
    from nate_ntm import cli as cli_mod

    fake = _FakeClient()
    fake.error = {"code": 123, "message": "Boom"}

    monkeypatch.setattr(cli_mod, "JsonRpcHttpClient", lambda host, port: fake)

    result = runner.invoke(
        app,
        [
            "api",
            "call",
            "agent.get_detail",
            "--param",
            "agent_id=nav-1",
            "--param",
            "max_events=10",
        ],
    )

    # JSON-RPC errors should yield a non-zero exit code and the error
    # payload should be rendered to stderr as JSON.
    assert result.exit_code == 1
    assert fake.last_method == "agent.get_detail"
    assert fake.last_params == {"agent_id": "nav-1", "max_events": 10}

    error_payload = json.loads(result.stderr)
    assert error_payload == {"code": 123, "message": "Boom"}
