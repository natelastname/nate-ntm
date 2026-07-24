from __future__ import annotations

from typing import Any, Mapping

from nate_ntm.runtime.agent_mail_client import McpAgentMailClient


class RecordingClient(McpAgentMailClient):
    calls: list[tuple[Mapping[str, Any], str]]

    def __post_init__(self) -> None:
        super().__post_init__()
        self.calls = []

    def _post_jsonrpc(self, payload: Mapping[str, Any], *, request_name: str) -> Any:
        self.calls.append((payload, request_name))
        return {"name": "agent-one", "registration_token": "token-one"}


def test_client_uses_explicit_project_and_url_without_path_fallback(monkeypatch) -> None:
    monkeypatch.setenv("NATE_NTM_AGENT_MAIL_URL", "http://ignored.example")
    monkeypatch.setenv("AGENT_MAIL_URL", "http://also-ignored.example")
    client = RecordingClient(
        project_id="swarm-project",
        base_url="http://127.0.0.1:8765",
    )

    assert client.base_url == "http://127.0.0.1:8765/api"
    assert client.ensure_project() == "swarm-project"
    assert client.ensure_project() == "swarm-project"
    assert len(client.calls) == 1
    payload, _ = client.calls[0]
    assert payload["params"]["arguments"] == {"human_key": "swarm-project"}


def test_client_reuses_persisted_identity_and_credentials() -> None:
    client = RecordingClient(
        project_id="swarm-project",
        base_url="http://127.0.0.1:8765/api",
        agent_identities={"agent-1": "agent-one"},
        agent_tokens={"agent-1": "token-one"},
    )

    assert client.ensure_agent_identity_with_credentials("agent-1") == (
        "agent-one",
        "token-one",
    )
    assert client.calls == []
