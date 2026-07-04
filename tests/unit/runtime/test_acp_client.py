"""Unit tests for the OpenHands ACP client adapters (T015/T102).

These tests exercise the in-memory / dev-mode implementation used by the
runtime and integration tests and a small amount of behavior from the
production :class:`OpenHandsAcpClient`. The bulk of the real client's
HTTP behavior is covered by gated integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.acp_client import FakeAcpClient, OpenHandsAcpClient


def _make_fake_client(tmp_path: Path) -> FakeAcpClient:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)
    return FakeAcpClient(config=config)


def _make_openhands_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OpenHandsAcpClient:
    """Construct an OpenHandsAcpClient with network I/O stubbed out.

    The client's low-level ``_request`` method is monkeypatched to avoid any
    real HTTP calls and to return predictable payloads for the operations
    under test.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)

    calls: list[tuple[str, str, dict, str]] = []

    def _fake_request(self, method: str, path: str, *, body: dict | None = None, request_name: str):  # type: ignore[override]
        calls.append((method, path, body or {}, request_name))

        if path == "/threads":
            # Echo back the requested thread_id to simulate a successful
            # ThreadCreate response.
            assert body is not None
            return {"thread_id": body.get("thread_id")}

        # Runs are returned with a simple fixed run_id.
        assert path.startswith("/threads/") and path.endswith("/runs")
        return {"run_id": "run-123"}

    monkeypatch.setattr(OpenHandsAcpClient, "_request", _fake_request, raising=True)

    client = OpenHandsAcpClient(config=config, base_url="http://example.invalid")
    # Attach the call log for assertions in tests.
    client._test_calls = calls  # type: ignore[attr-defined]
    return client


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


def test_openhands_acp_client_ensures_stable_conversation_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """OpenHands client returns stable conversation IDs per agent.

    This test uses a stubbed HTTP layer to avoid network access and
    verifies that:

    * repeated calls for the same ``agent_id`` within a process reuse the
      cached thread ID and do not issue extra HTTP calls, and
    * a fresh client with the same configuration derives the same
      thread ID for that agent.
    """

    client = _make_openhands_client(tmp_path, monkeypatch)

    conv1 = client.ensure_conversation("agent-1")
    conv2 = client.ensure_conversation("agent-1")

    assert conv1
    assert conv1 == conv2

    calls = getattr(client, "_test_calls")
    assert len(calls) == 1
    method, path, body, _ = calls[0]
    assert method == "POST"
    assert path == "/threads"
    assert body["metadata"]["nate_ntm_agent_id"] == "agent-1"

    # A new client with the same config should derive the same thread ID.
    client2 = _make_openhands_client(tmp_path, monkeypatch)
    conv3 = client2.ensure_conversation("agent-1")
    assert conv3 == conv1


def test_openhands_acp_client_start_turn_uses_thread_and_returns_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``start_turn`` delegates to the runs endpoint and returns ``run_id``."""

    client = _make_openhands_client(tmp_path, monkeypatch)

    run_id = client.start_turn("agent-42")
    assert run_id == "run-123"

    calls = getattr(client, "_test_calls")
    # One call to create the thread, one to create the run.
    assert len(calls) == 2
    _, path_thread, _, _ = calls[0]
    method_run, path_run, body_run, _ = calls[1]

    assert path_thread == "/threads"
    assert method_run == "POST"
    assert path_run.startswith("/threads/") and path_run.endswith("/runs")
    assert body_run["metadata"]["nate_ntm_agent_id"] == "agent-42"

