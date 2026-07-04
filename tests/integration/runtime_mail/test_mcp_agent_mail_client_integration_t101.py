"""Integration tests for the MCP-backed Agent Mail client (T101).

These tests exercise :class:`McpAgentMailClient` against a running
``mcp_agent_mail`` server using its MCP HTTP/JSON-RPC surface. They are
**gated** on an explicit Agent Mail URL environment variable so that
offline CI and developers without a local server do not run them by
accident.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.agent_mail_client import McpAgentMailClient


AGENT_MAIL_URL = os.environ.get("NATE_NTM_AGENT_MAIL_URL") or os.environ.get("AGENT_MAIL_URL") or ""

pytestmark = pytest.mark.skipif(
    not AGENT_MAIL_URL,
    reason=(
        "Agent Mail server URL not configured; set NATE_NTM_AGENT_MAIL_URL or "
        "AGENT_MAIL_URL to run MCP Agent Mail integration tests (T101)."
    ),
)


def _make_config(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    # Use a per-adapter REAL override for Agent Mail so the config
    # reflects the production posture without requiring a REAL ACP
    # adapter. We construct the client directly here to avoid depending on
    # other layers (daemon, scheduler) for these integration checks.
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_AGENT_MAIL_ADAPTER": AdapterKind.REAL.value,
    }
    return load_runtime_config(env=env)


def test_mcp_agent_mail_client_basic_roundtrip(tmp_path: Path) -> None:
    """Smoke-test ensure_project + register_agent + fetch_inbox.

    Expectations (given a healthy Agent Mail server):

    * ``ensure_project`` returns a stable, non-empty identifier.
    * ``ensure_agent_identity_with_credentials`` returns an identity and
      registration token and is idempotent when called with the same
      token.
    * ``get_unread_mail_flags`` reports ``False`` for a freshly
      registered agent with no inbox activity.
    """

    config = _make_config(tmp_path)
    client = McpAgentMailClient(config=config)

    project_id_1 = client.ensure_project()
    project_id_2 = client.ensure_project()

    assert project_id_1
    assert project_id_1 == project_id_2

    agent_id = "runtime-t101-agent-1"

    identity, token = client.ensure_agent_identity_with_credentials(agent_id)
    assert identity
    # New registrations should always return a non-empty registration token.
    assert token

    # A second call with the stored token should be idempotent and avoid
    # changing identity or credentials.
    identity2, token2 = client.ensure_agent_identity_with_credentials(agent_id, token)
    assert identity2 == identity
    assert token2 == token

    # Newly-registered agents should have no unread mail by default.
    flags = client.get_unread_mail_flags([agent_id])
    assert flags == {agent_id: False}

    # Unknown agents (no registration token cached) are treated
    # conservatively as having no unread mail.
    flags_unknown = client.get_unread_mail_flags(["unknown-agent-t101"])
    assert flags_unknown == {"unknown-agent-t101": False}
