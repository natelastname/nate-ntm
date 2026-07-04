"""Unit tests for the OpenHands ACP client adapter (T015).

These tests exercise the in-memory / dev-mode implementation used by the
runtime and integration tests. The real ACP client that talks to an
OpenHands server will be built on top of the same interface.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.acp_client import FakeAcpClient


def _make_fake_client(tmp_path: Path) -> FakeAcpClient:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)
    return FakeAcpClient(config=config)


def test_fake_acp_client_ensures_stable_conversation_ids(tmp_path: Path) -> None:
    """``ensure_conversation`` returns stable, per-agent conversation IDs."""

    client = _make_fake_client(tmp_path)

    a1_conv_first = client.ensure_conversation("agent-1")
    a1_conv_second = client.ensure_conversation("agent-1")
    a2_conv = client.ensure_conversation("agent-2")

    assert a1_conv_first
    assert a1_conv_first == a1_conv_second
    assert a2_conv
    assert a1_conv_first != a2_conv


def test_fake_acp_client_allocates_unique_turn_ids(tmp_path: Path) -> None:
    """``start_turn`` allocates monotonically increasing, per-agent turn IDs."""

    client = _make_fake_client(tmp_path)

    conv = client.ensure_conversation("agent-1")
    assert conv  # sanity

    turn_1 = client.start_turn("agent-1")
    turn_2 = client.start_turn("agent-1")

    assert turn_1 != turn_2
    assert turn_1.startswith("fake-turn:agent-1:")
    assert turn_2.startswith("fake-turn:agent-1:")

    # Different agents receive their own turn sequences.
    client.ensure_conversation("agent-2")
    other_turn = client.start_turn("agent-2")
    assert other_turn.startswith("fake-turn:agent-2:")
