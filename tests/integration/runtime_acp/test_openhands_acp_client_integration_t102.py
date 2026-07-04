"""Integration tests for the REAL OpenHands ACP adapter (T102).

These tests exercise :class:`OpenHandsAcpClient` against a running
OpenHands-compatible ACP server. They are **gated** behind environment
variables so that they only run when an ACP endpoint is explicitly
configured.

To enable these tests, set at least one of:

* ``NATE_NTM_ACP_URL``
* ``ACP_URL``

optionally along with an authentication token via one of:

* ``NATE_NTM_ACP_TOKEN``
* ``ACP_TOKEN``
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.acp_client import OpenHandsAcpClient


_ACP_URL = os.environ.get("NATE_NTM_ACP_URL") or os.environ.get("ACP_URL") or ""

pytestmark = pytest.mark.skipif(
    not _ACP_URL,
    reason=(
        "ACP server URL not configured; set NATE_NTM_ACP_URL or ACP_URL "
        "to run OpenHands ACP integration tests (T102)."
    ),
)


def _make_config(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_ACP_ADAPTER": AdapterKind.REAL.value,
    }
    return load_runtime_config(env=env)


def test_openhands_acp_client_ensure_conversation_is_idempotent(tmp_path: Path) -> None:
    """``ensure_conversation`` returns a stable ID for the same agent.

    This is a light smoke test that verifies the REAL adapter can talk to
    the configured ACP endpoint and that repeated calls for the same
    ``agent_id`` do not change the conversation identifier.
    """

    config = _make_config(tmp_path)
    client = OpenHandsAcpClient(config=config, base_url=_ACP_URL)

    agent_id = "runtime-t102-agent-1"

    conv1 = client.ensure_conversation(agent_id)
    conv2 = client.ensure_conversation(agent_id)

    assert conv1
    assert conv1 == conv2


def test_openhands_acp_client_start_turn_smoke(tmp_path: Path) -> None:
    """``start_turn`` can create a run for the agent's conversation."""

    config = _make_config(tmp_path)
    client = OpenHandsAcpClient(config=config, base_url=_ACP_URL)

    agent_id = "runtime-t102-agent-2"

    conv = client.ensure_conversation(agent_id)
    assert conv  # sanity

    run_id = client.start_turn(agent_id)
    assert run_id
