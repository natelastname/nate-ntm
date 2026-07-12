"""Unit tests for the Agent Mail MCP-backed client.

This module focuses on the production :class:`McpAgentMailClient` behavior
that we still rely on in the Nate OHA / ACP-centric design. Tests that
exercise the in-memory ``FakeAgentMailClient`` (including deterministic
project IDs, identities, and unread-mail flags) have been removed as part
of the migration away from fake adapters.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.agent_mail_client import McpAgentMailClient


def _make_mcp_client(tmp_path: Path, project_key: str | None = None) -> McpAgentMailClient:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    # ``load_runtime_config`` will resolve ``agent_mail_project`` from the
    # explicit argument when provided, falling back to the project path
    # otherwise. We rely on that behavior here to match the runtime's
    # production configuration logic.
    config = load_runtime_config(
        project_path=project,
        agent_mail_project=project_key,
    )
    return McpAgentMailClient(config=config)



def test_mcp_agent_mail_client_ensure_project_uses_configured_project_key(tmp_path: Path) -> None:
    """McpAgentMailClient.ensure_project returns the configured project key.

    For REAL adapters the Agent Mail *project key* comes from
    :class:`RuntimeConfig.agent_mail_project` (or, by default, the
    absolute project path). The client must return that same key from
    :meth:`ensure_project` so that it can be stored in
    ``SwarmMetadata.agent_mail_project_id`` and propagated into
    ``AGENT_MAIL_PROJECT`` for nate_OHA launches.
    """

    # Use an explicit project key that does not look like a path to make
    # the expectation clear and robust.
    project_key = "proj-explicit-key-123"
    client = _make_mcp_client(tmp_path, project_key=project_key)

    # Stub out the underlying tool call so the test remains network-free
    # while still verifying the arguments passed to the MCP client.
    calls: list[dict[str, object]] = []

    def fake_call_tool(*, name: str, arguments: dict, request_id: str, request_name: str):  # type: ignore[override]
        calls.append(
            {
                "name": name,
                "arguments": arguments,
                "request_id": request_id,
                "request_name": request_name,
            }
        )
        # The return value is ignored by ensure_project, so keep it simple.
        return {"id": "ignored", "slug": "ignored"}

    client._call_tool = fake_call_tool  # type: ignore[assignment]

    project_id_1 = client.ensure_project()
    project_id_2 = client.ensure_project()

    # ``ensure_project`` must always return the configured project key and
    # cache it so that subsequent calls avoid new tool invocations.
    assert project_id_1 == project_key
    assert project_id_2 == project_key
    assert len(calls) == 1

    call = calls[0]
    assert call["name"] == "ensure_project"
    assert call["arguments"] == {"human_key": project_key}
