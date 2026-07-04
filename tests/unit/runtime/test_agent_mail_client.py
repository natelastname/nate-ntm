"""Unit tests for the Agent Mail coordination adapter (T014).

These tests focus on the in-memory / dev-mode implementation used in
unit and integration tests. The real adapter that talks to a running
Agent Mail service will be layered on later.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient


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
