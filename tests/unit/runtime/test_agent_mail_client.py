"""Unit tests for the Agent Mail coordination adapters (T014/T101).

This module primarily exercises the in-memory / dev-mode implementation
used in unit and integration tests. It also includes a few small,
network-free checks for the production MCP-backed adapter's project/ID
semantics. End-to-end behavior against a real ``mcp_agent_mail`` server
remains covered by separate gated integration tests (see T101/T242).
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient, McpAgentMailClient


def _make_fake_client(tmp_path: Path) -> FakeAgentMailClient:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)
    return FakeAgentMailClient(config=config)


def test_fake_agent_mail_client_ensures_single_project_id(tmp_path: Path) -> None:
    """``ensure_project`` returns a stable, non-empty project identifier.

    The fake implementation is deterministic so that tests can make
    assertions about the Agent Mail project ID without depending on
    external services or randomness.
    """

    client = _make_fake_client(tmp_path)

    project_id_1 = client.ensure_project()
    project_id_2 = client.ensure_project()

    assert project_id_1
    assert project_id_1 == project_id_2



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



def test_fake_agent_mail_client_ensures_stable_agent_identities(tmp_path: Path) -> None:
    """Agent identities are stable and unique per agent within a project."""

    client = _make_fake_client(tmp_path)
    client.ensure_project()

    a1_id_first = client.ensure_agent_identity("agent-1")
    a1_id_second = client.ensure_agent_identity("agent-1")
    a2_id = client.ensure_agent_identity("agent-2")

    assert a1_id_first
    assert a1_id_first == a1_id_second
    assert a2_id
    assert a1_id_first != a2_id


def test_fake_agent_mail_client_reports_unread_mail_flags(tmp_path: Path) -> None:
    """Unread mail flags default to False and can be overridden for tests."""

    client = _make_fake_client(tmp_path)
    client.ensure_project()

    # By default there is no unread mail for any agent.
    flags = client.get_unread_mail_flags(["agent-1", "agent-2"])
    assert flags == {"agent-1": False, "agent-2": False}

    # Tests can mark specific agents as having unread mail.
    client.set_unread_count_for_test("agent-1", 3)

    flags = client.get_unread_mail_flags(["agent-1", "agent-2", "agent-3"])
    assert flags == {"agent-1": True, "agent-2": False, "agent-3": False}
