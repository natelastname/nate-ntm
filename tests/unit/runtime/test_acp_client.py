"""Unit tests for the OpenHands ACP client adapters (T015/T102).

These tests exercise the in-memory / dev-mode implementation used by the
runtime and integration tests and a small amount of behavior from the
production :class:`OpenHandsAcpClient`. The bulk of the real client's
HTTP behavior is covered by gated integration tests.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
import os

import pytest

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime import acp_client as acp_mod
from nate_ntm.runtime.acp_client import AcpClientError, AcpAgentStatus, FakeAcpClient, OpenHandsAcpClient, NateOhaAcpClient
from nate_ntm.runtime.adapters import RuntimeAdapters
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.events import AgentEventSource
from nate_ntm.runtime.metadata_store import AgentMetadata, MetadataStore


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



def _make_nate_oha_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NateOhaAcpClient:
    """Construct a NateOhaAcpClient with external dependencies stubbed.

    These tests focus on adapter-level lifecycle semantics (start/stop/status)
    and do not exercise the real ``nate_OHA`` binary. The version
    compatibility check is bypassed here and covered explicitly in later
    tests.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    # For NateOhaAcpClient tests we take an explicit snapshot of the
    # current process environment so that ``load_runtime_config`` does not
    # consult the repository-level ``.env`` file. Individual tests control
    # Agent Mail-related variables via ``monkeypatch``.
    env_snapshot = dict(os.environ)
    config = load_runtime_config(project_path=project, env=env_snapshot)

    client = NateOhaAcpClient(config=config)

    # Avoid invoking the real nate_OHA CLI during unit tests that focus on
    # adapter behavior.
    monkeypatch.setattr(client, "_check_version", lambda: None)

    # Stub out ``subprocess.Popen`` so that no real processes are spawned.
    popen_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class DummyPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs
            self.pid = 12345
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self, timeout: float | None = None) -> int:
            if self._returncode is None:
                # Simulate a clean exit when waited on.
                self._returncode = 0
            return self._returncode

        def terminate(self) -> None:
            # Simulate graceful termination.
            if self._returncode is None:
                self._returncode = 0

        def kill(self) -> None:
            # Simulate forced termination.
            self._returncode = -9

        @property
        def returncode(self) -> int | None:
            return self._returncode

    def fake_popen(*args: object, **kwargs: object) -> DummyPopen:
        popen_calls.append((args, kwargs))
        return DummyPopen(*args, **kwargs)

    monkeypatch.setattr(acp_mod.subprocess, "Popen", fake_popen)

    # Attach the call log so later tests can make assertions about the
    # constructed command and environment.
    client._test_popen_calls = popen_calls  # type: ignore[attr-defined]

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


def test_fake_acp_client_start_and_stop_agent_update_status(tmp_path: Path) -> None:
    """``start_agent``/``stop_agent`` update adapter-level status for agents."""

    client = _make_fake_client(tmp_path)

    # Before an agent is started, status should default to ``idle``.
    status_before = client.get_status("agent-1")
    assert isinstance(status_before, AcpAgentStatus)
    assert status_before.agent_id == "agent-1"
    assert status_before.state == "idle"

    # After starting the agent, status should report it as running.
    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    client.start_agent("agent-1", metadata=meta)

    status_running = client.get_status("agent-1")
    assert status_running.state == "running"

    # Stopping the agent should transition it to a terminated state.
    client.stop_agent("agent-1", timeout=1.0)
    status_stopped = client.get_status("agent-1")
    assert status_stopped.state == "terminated"


def test_fake_acp_client_start_turn_emits_event_when_callback_configured(tmp_path: Path) -> None:
    """``start_turn`` emits an AgentEvent via the optional callback."""

    events: list[dict] = []

    def _on_event(event) -> None:
        events.append(event)

    client = _make_fake_client(tmp_path)
    client.on_event = _on_event

    # Calling ``start_turn`` should allocate a turn ID and emit an event.
    turn_id = client.start_turn("agent-1", prompt="hello world")
    assert turn_id

    assert len(events) == 1
    event = events[0]

    assert event.agent_id == "agent-1"
    assert event.source is AgentEventSource.ACP
    assert event.type == "TurnCompleted"
    assert event.payload["adapter"] == "fake"
    assert event.payload["turn_id"] == turn_id

    # The conversation ID in the payload should match ensure_conversation.
    conv = client.ensure_conversation("agent-1")
    assert event.payload["conversation_id"] == conv

    # When a prompt is provided it should be echoed into the payload.
    assert event.payload["prompt"] == "hello world"



@pytest.mark.asyncio
async def test_fake_acp_client_async_lifecycle_shims(tmp_path: Path) -> None:
    """Async lifecycle helpers delegate to the synchronous FakeAcpClient API.

    This covers the transitional ``*_async`` and ``prompt``/``interrupt``
    methods added for T016 so that new runtime code can rely on an
    awaitable agent-lifecycle interface while legacy call sites continue
    to use the synchronous methods.
    """

    client = _make_fake_client(tmp_path)

    # Before an agent is started, status should default to ``idle``.
    status_before = client.get_status("agent-1")
    assert status_before.state == "idle"

    # ``start_agent_async`` should delegate to ``start_agent``.
    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    await client.start_agent_async("agent-1", metadata=meta)

    status_running = client.get_status("agent-1")
    assert status_running.state == "running"

    # ``prompt`` should delegate to ``start_turn`` and return a turn ID.
    turn_id = await client.prompt("agent-1", prompt="hello async")
    assert isinstance(turn_id, str)
    assert turn_id.startswith("fake-turn:agent-1:")

    # ``interrupt`` is a no-op for the fake adapter but must be awaitable.
    await client.interrupt("agent-1")

    # ``stop_agent_async`` should delegate to ``stop_agent`` and update status.
    await client.stop_agent_async("agent-1", timeout=1.0)
    status_stopped = client.get_status("agent-1")
    assert status_stopped.state == "terminated"


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




@pytest.mark.asyncio
async def test_openhands_acp_client_async_lifecycle_shims(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Async lifecycle helpers delegate to the HTTP adapter primitives.

    This mirrors the FakeAcpClient coverage for T016 but exercises the
    OpenHands HTTP adapter using the stubbed ``_request`` implementation.
    """

    client = _make_openhands_client(tmp_path, monkeypatch)

    # ``start_agent_async`` should be a no-op beyond ensuring a conversation.
    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    await client.start_agent_async("agent-1", metadata=meta)

    # ``prompt`` should delegate to ``start_turn`` and return a run_id from
    # the stubbed HTTP layer.
    run_id = await client.prompt("agent-1")
    assert run_id == "run-123"

    calls = getattr(client, "_test_calls")
    # One call to /threads from ensure_conversation and one to /runs.
    assert len(calls) == 2
    methods_paths = [(m, p) for (m, p, _body, _name) in calls]
    assert methods_paths[0] == ("POST", "/threads")
    assert methods_paths[1][0] == "POST"
    assert methods_paths[1][1].startswith("/threads/") and methods_paths[1][1].endswith("/runs")

    # ``interrupt`` and ``stop_agent_async`` are defined and awaitable but
    # currently act as no-ops for this legacy HTTP adapter.
    await client.interrupt("agent-1")
    await client.stop_agent_async("agent-1", timeout=1.0)


def test_nate_oha_acp_client_start_and_stop_update_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``start_agent``/``stop_agent`` should update adapter-level status for agents.

    This test describes the expected lifecycle semantics for
    :class:`NateOhaAcpClient` without depending on the concrete subprocess
    implementation. It is written before T212–T214 and will initially fail
    until the implementation is complete.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    # Before an agent is started, status should default to ``idle``.
    status_before = client.get_status("agent-1")
    assert isinstance(status_before, AcpAgentStatus)
    assert status_before.agent_id == "agent-1"
    assert status_before.state == "idle"
    assert status_before.last_exit_code is None
    assert status_before.last_error is None
    assert status_before.restart_count == 0

    # After starting the agent, status should report it as running.
    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    client.start_agent("agent-1", metadata=meta)

    status_running = client.get_status("agent-1")
    assert isinstance(status_running, AcpAgentStatus)
    assert status_running.agent_id == "agent-1"
    assert status_running.state == "running"
    assert status_running.last_exit_code is None
    assert status_running.last_error is None

    # Stopping the agent should transition it to a terminated state and record
    # the last exit code.
    client.stop_agent("agent-1", timeout=5.0)
    status_stopped = client.get_status("agent-1")
    assert isinstance(status_stopped, AcpAgentStatus)
    assert status_stopped.agent_id == "agent-1"
    assert status_stopped.state == "terminated"
    # Exit code may vary by implementation but should be an int once the
    # process has terminated.
    assert isinstance(status_stopped.last_exit_code, (int, type(None)))




def test_nate_oha_acp_client_start_agent_emits_started_and_ready_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """start_agent emits process-started and ready events via on_event.

    This covers the happy-path lifecycle where nate_OHA starts successfully
    and remains running after the initial readiness check.
    """

    events: list[object] = []

    def _on_event(event: object) -> None:
        events.append(event)

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    client.on_event = _on_event

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    client.start_agent("agent-1", metadata=meta)

    # The adapter should emit a started event followed by a ready event.
    assert len(events) == 2

    from nate_ntm.runtime.events import AgentEvent

    started, ready = events
    assert isinstance(started, AgentEvent)
    assert isinstance(ready, AgentEvent)

    assert started.agent_id == "agent-1"
    assert started.source is AgentEventSource.ACP
    assert started.type == "nate_oha_process_started"
    assert started.payload["pid"] == 12345

    assert ready.agent_id == "agent-1"
    assert ready.source is AgentEventSource.ACP
    assert ready.type == "nate_oha_process_ready"
    assert ready.payload["pid"] == 12345



def test_nate_oha_acp_client_start_agent_emits_start_failed_event_on_immediate_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """start_agent emits a start_failed event when nate_OHA exits early.

    This simulates a process that exits during the initial readiness check,
    causing ``start_agent`` to mark the record as failed and raise
    :class:`AcpClientError`.
    """

    events: list[object] = []

    def _on_event(event: object) -> None:
        events.append(event)

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    client.on_event = _on_event

    # Override the subprocess stub so that the spawned process appears to
    # exit immediately with a non-zero code.
    class FailingPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pid = 4242
            self._returncode = 17

        def poll(self) -> int:
            return self._returncode

        def wait(self, timeout: float | None = None) -> int:  # pragma: no cover - safety
            return self._returncode

        def terminate(self) -> None:  # pragma: no cover - safety
            pass

        def kill(self) -> None:  # pragma: no cover - safety
            pass

        @property
        def returncode(self) -> int:
            return self._returncode

    monkeypatch.setattr(acp_mod.subprocess, "Popen", FailingPopen)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    with pytest.raises(AcpClientError) as excinfo:
        client.start_agent("agent-1", metadata=meta)

    msg = str(excinfo.value)
    assert "exited during startup" in msg

    # Two events should have been emitted: started and start_failed.
    assert [e.type for e in events] == [
        "nate_oha_process_started",
        "nate_oha_process_start_failed",
    ]

    started, failed = events
    assert started.payload["pid"] == 4242
    assert failed.payload["exit_code"] == 17



def test_nate_oha_acp_client_stop_agent_emits_exited_event_on_clean_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """stop_agent emits nate_oha_process_exited for a clean termination."""

    events: list[object] = []

    def _on_event(event: object) -> None:
        events.append(event)

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    client.on_event = _on_event

    # Stub Popen so that the process appears to be running when started and
    # exits cleanly (exit code 0) when terminated.
    class ExitingPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pid = 1111
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self, timeout: float | None = None) -> int:
            if self._returncode is None:
                self._returncode = 0
            return self._returncode

        def terminate(self) -> None:
            if self._returncode is None:
                self._returncode = 0

        def kill(self) -> None:  # pragma: no cover - safety
            self._returncode = -9

        @property
        def returncode(self) -> int | None:
            return self._returncode

    monkeypatch.setattr(acp_mod.subprocess, "Popen", ExitingPopen)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    client.start_agent("agent-1", metadata=meta)
    client.stop_agent("agent-1", timeout=5.0)

    # We expect three events: started, ready, exited.
    types = [e.type for e in events]
    assert types == [
        "nate_oha_process_started",
        "nate_oha_process_ready",
        "nate_oha_process_exited",
    ]

    exited = events[-1]
    assert exited.payload["exit_code"] == 0



def test_nate_oha_acp_client_stop_agent_emits_crashed_event_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """stop_agent emits nate_oha_process_crashed when exit code is non-zero."""

    events: list[object] = []

    def _on_event(event: object) -> None:
        events.append(event)

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    client.on_event = _on_event

    # Stub Popen so that the process appears to be running and then exits
    # with a non-zero code when terminated.
    class CrashingPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pid = 2222
            self._returncode: int | None = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self, timeout: float | None = None) -> int:
            if self._returncode is None:
                self._returncode = 1
            return self._returncode

        def terminate(self) -> None:
            if self._returncode is None:
                self._returncode = 1

        def kill(self) -> None:  # pragma: no cover - safety
            self._returncode = -9

        @property
        def returncode(self) -> int | None:
            return self._returncode

    monkeypatch.setattr(acp_mod.subprocess, "Popen", CrashingPopen)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    client.start_agent("agent-1", metadata=meta)
    client.stop_agent("agent-1", timeout=5.0)

    # We expect three events: started, ready, crashed.
    types = [e.type for e in events]
    assert types == [
        "nate_oha_process_started",
        "nate_oha_process_ready",
        "nate_oha_process_crashed",
    ]

    crashed = events[-1]
    assert crashed.payload["exit_code"] == 1



def test_nate_oha_acp_client_ensure_conversation_is_idempotent_and_deterministic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ensure_conversation`` is stable per agent and across clients.

    This covers the core T220 requirement that the nate_OHA-backed ACP
    adapter derive deterministic, idempotent conversation identifiers for
    agents, suitable for reuse on resume.
    """

    client1 = _make_nate_oha_client(tmp_path, monkeypatch)

    a1_first = client1.ensure_conversation("agent-1")
    a1_second = client1.ensure_conversation("agent-1")
    a2_conv = client1.ensure_conversation("agent-2")

    assert a1_first
    assert a1_first == a1_second
    assert a2_conv
    assert a1_first != a2_conv

    # A fresh client with the same configuration should derive the same
    # identifier for a given agent.
    client2 = _make_nate_oha_client(tmp_path, monkeypatch)
    a1_third = client2.ensure_conversation("agent-1")
    assert a1_third == a1_first



def test_nate_oha_acp_client_ensure_conversation_reuses_existing_metadata_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing ``AgentMetadata.conversation_id`` values are reused.

    When per-agent metadata already has a non-empty ``conversation_id``,
    ``ensure_conversation`` must return that value instead of deriving a
    new one so that conversation continuity is preserved.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    store = MetadataStore(config=client.config)

    preexisting_id = "conv-preexisting-123"
    meta = AgentMetadata(agent_id="nav-1", display_name="Navigator 1", conversation_id=preexisting_id)
    store.save_agent_metadata(meta)

    conv = client.ensure_conversation("nav-1")
    assert conv == preexisting_id

    # Metadata should still report the same ID.
    reloaded = store.load_agent_metadata("nav-1")
    assert reloaded.conversation_id == preexisting_id



def test_nate_oha_acp_client_ensure_conversation_persists_allocated_id_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing ``conversation_id`` in metadata is filled and persisted.

    When ``AgentMetadata`` exists but ``conversation_id`` is empty,
    ``ensure_conversation`` must allocate a stable identifier and write it
    back to the metadata store so later runs can reuse it.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    store = MetadataStore(config=client.config)

    meta = AgentMetadata(agent_id="nav-1", display_name="Navigator 1")
    store.save_agent_metadata(meta)

    conv1 = client.ensure_conversation("nav-1")
    assert conv1

    reloaded1 = store.load_agent_metadata("nav-1")
    assert reloaded1.conversation_id == conv1

    # Idempotent: subsequent calls return the same ID and keep metadata in sync.
    conv2 = client.ensure_conversation("nav-1")
    assert conv2 == conv1

    reloaded2 = store.load_agent_metadata("nav-1")
    assert reloaded2.conversation_id == conv1



def test_nate_oha_acp_client_start_agent_includes_conversation_id_env_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``start_agent`` propagates ``conversation_id`` into the child env.

    When metadata has a non-empty ``conversation_id``, the launch
    environment must include ``NATE_NTM_AGENT_CONVERSATION_ID`` so that
    nate_OHA/OpenHands can reconnect to the correct ACP conversation.
    """

    # Minimal Agent Mail configuration so environment construction succeeds.
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_URL", raising=False)
    monkeypatch.setenv("AGENT_MAIL_PROJECT", "test-project")
    monkeypatch.setenv("AGENT_MAIL_UPSTREAM_URL", "https://agent-mail.invalid/mcp")

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    meta = AgentMetadata(
        agent_id="agent-1",
        display_name="Agent One",
        agent_mail_identity="agent-mail-identity",
        agent_mail_credentials_ref="secret-token-ref",
        conversation_id="conv-123",
    )

    client.start_agent("agent-1", metadata=meta)

    popen_calls = getattr(client, "_test_popen_calls")
    assert len(popen_calls) == 1
    (args, kwargs) = popen_calls[0]

    env = kwargs.get("env")
    assert isinstance(env, dict)
    assert env["NATE_NTM_AGENT_CONVERSATION_ID"] == "conv-123"





@pytest.mark.asyncio
async def test_nate_oha_acp_client_start_agent_async_creates_new_acp_session_when_missing_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """start_agent_async uses ACP SDK to create a new session when no ID.

    This test exercises the initial NateOhaAcpClient async lifecycle wiring:

    * ``start_agent_async`` must invoke ``open_nate_oha_acp_client`` with the
      same command/env as the synchronous ``start_agent`` helper.
    * The resulting ACP connection is initialized with the expected
      protocol version and client capabilities.
    * When ``AgentMetadata.conversation_id`` is empty, a new ACP session is
      created and the returned ``session_id`` is stored in
      :class:`AcpAgentSession`.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    captured: dict[str, object] = {}

    class DummyConnection:
        def __init__(self) -> None:
            self.initialized_args: tuple[object, ...] | None = None
            self.new_session_args: dict[str, object] | None = None
            self.load_session_args: dict[str, object] | None = None
            self.closed: bool = False

        async def initialize(self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs):
            self.initialized_args = (protocol_version, client_capabilities)

        async def new_session(self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs):
            self.new_session_args = {
                "cwd": cwd,
                "additional_directories": additional_directories,
                "mcp_servers": mcp_servers,
            }

            class _Resp:
                def __init__(self, session_id: str) -> None:
                    self.session_id = session_id

            return _Resp("acp-session-123")

        async def load_session(self, cwd: str, session_id: str, mcp_servers=None, additional_directories=None, **kwargs):
            self.load_session_args = {
                "cwd": cwd,
                "session_id": session_id,
                "mcp_servers": mcp_servers,
                "additional_directories": additional_directories,
            }

        async def close(self) -> None:
            self.closed = True

    class DummyProcess:
        def __init__(self) -> None:
            self.closed: bool = False

    class DummyProtocolClient:
        def __init__(self, agent_id: str, event_sink) -> None:
            self.agent_id = agent_id
            self.event_sink = event_sink

    @asynccontextmanager
    async def fake_open_nate_oha_acp_client(*, command, env, cwd, agent_id, event_sink, capabilities):  # type: ignore[override]
        conn = DummyConnection()
        proc = DummyProcess()
        proto = DummyProtocolClient(agent_id, event_sink)

        captured["command"] = command
        captured["env"] = env
        captured["cwd"] = cwd
        captured["agent_id"] = agent_id
        captured["connection"] = conn
        captured["process"] = proc
        captured["protocol_client"] = proto

        try:
            yield conn, proc, proto
        finally:
            await conn.close()
            proc.closed = True

    import nate_ntm.runtime.acp_connection as acp_conn

    # Patch the symbol imported into nate_ntm.runtime.acp_client rather than
    # the acp_connection module itself so that NateOhaAcpClient.start_agent_async
    # sees the stub.
    monkeypatch.setattr(acp_mod, "open_nate_oha_acp_client", fake_open_nate_oha_acp_client, raising=True)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    # Invoke the async lifecycle entrypoint.
    await client.start_agent_async("agent-1", metadata=meta)

    # The helper must be called with the same command/env as the synchronous
    # process-launch helper.
    expected_cmd = client._build_command(meta)
    expected_env = client._build_env("agent-1", meta)
    assert captured["command"] == expected_cmd
    assert captured["env"] == expected_env
    assert captured["cwd"] == client.config.project_path

    # The ACP connection should have been initialized with the correct
    # protocol version and client capabilities.
    from acp.meta import PROTOCOL_VERSION as ACP_PROTOCOL_VERSION
    from nate_ntm.runtime.acp_protocol_client import NATE_NTM_CLIENT_CAPABILITIES as CAPS

    conn = captured["connection"]
    assert isinstance(conn, DummyConnection)
    assert conn.initialized_args == (ACP_PROTOCOL_VERSION, CAPS)

    # Because metadata had no conversation_id, ``new_session`` should have
    # been used and ``load_session`` should not.
    assert conn.new_session_args is not None
    assert conn.new_session_args["cwd"] == str(client.config.project_path)
    assert conn.load_session_args is None

    # An AcpAgentSession record should exist for the agent with the
    # ACP-derived session identifier.
    session = client._sessions.get("agent-1")
    assert session is not None
    assert session.agent_id == "agent-1"
    assert session.conversation_id == "acp-session-123"
    assert session.status == "running"


@pytest.mark.asyncio
async def test_nate_oha_acp_client_start_agent_async_loads_existing_acp_session_when_conversation_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """start_agent_async uses ``load_session`` when metadata has an ID."""

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    captured: dict[str, object] = {}

    class DummyConnection:
        def __init__(self) -> None:
            self.initialized_args: tuple[object, ...] | None = None
            self.new_session_called: bool = False
            self.load_session_args: dict[str, object] | None = None
            self.closed: bool = False

        async def initialize(self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs):
            self.initialized_args = (protocol_version, client_capabilities)

        async def new_session(self, *args, **kwargs):  # pragma: no cover - should not be called
            self.new_session_called = True
            raise AssertionError("new_session should not be called when conversation_id is present")

        async def load_session(self, cwd: str, session_id: str, mcp_servers=None, additional_directories=None, **kwargs):
            self.load_session_args = {
                "cwd": cwd,
                "session_id": session_id,
            }

        async def close(self) -> None:
            self.closed = True

    class DummyProcess:
        def __init__(self) -> None:
            self.closed: bool = False

    class DummyProtocolClient:
        def __init__(self, agent_id: str, event_sink) -> None:
            self.agent_id = agent_id
            self.event_sink = event_sink

    @asynccontextmanager
    async def fake_open_nate_oha_acp_client(*, command, env, cwd, agent_id, event_sink, capabilities):  # type: ignore[override]
        conn = DummyConnection()
        proc = DummyProcess()
        proto = DummyProtocolClient(agent_id, event_sink)

        captured["connection"] = conn

        try:
            yield conn, proc, proto
        finally:
            await conn.close()
            proc.closed = True

    import nate_ntm.runtime.acp_connection as acp_conn

    # Patch the symbol imported into nate_ntm.runtime.acp_client rather than
    # the acp_connection module itself so that NateOhaAcpClient.start_agent_async
    # sees the stub.
    monkeypatch.setattr(acp_mod, "open_nate_oha_acp_client", fake_open_nate_oha_acp_client, raising=True)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One", conversation_id="existing-session-42")

    await client.start_agent_async("agent-1", metadata=meta)

    conn = captured["connection"]
    assert isinstance(conn, DummyConnection)

    # ``load_session`` should have been invoked with the metadata ID and
    # ``new_session`` must not have been called.
    assert conn.load_session_args is not None
    assert conn.load_session_args["session_id"] == "existing-session-42"
    assert conn.new_session_called is False

    session = client._sessions.get("agent-1")
    assert session is not None
    assert session.conversation_id == "existing-session-42"




@pytest.mark.asyncio
async def test_nate_oha_acp_client_start_agent_async_persists_new_session_id_to_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """start_agent_async persists ACP-assigned session_id into AgentMetadata.

    When ``AgentMetadata.conversation_id`` is empty, ``start_agent_async`` must
    create a new ACP session via ``new_session`` and persist the returned
    ``session_id`` back into the per-agent metadata store so that later
    resume flows can reuse it.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    # Use a metadata store wired to the client's config so we can observe
    # persisted changes.
    store = MetadataStore(config=client.config)

    # Seed an AgentMetadata record without a conversation_id.
    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    store.save_agent_metadata(meta)

    class DummyConnection:
        def __init__(self) -> None:
            self.closed: bool = False

        async def initialize(self, *args, **kwargs):  # pragma: no cover - not relevant
            pass

        async def new_session(self, cwd: str, **kwargs):
            class _Resp:
                def __init__(self, session_id: str) -> None:
                    self.session_id = session_id

            # Return a deterministic session identifier so assertions are
            # straightforward.
            return _Resp("acp-session-meta-123")

        async def load_session(self, *args, **kwargs):  # pragma: no cover - not used here
            raise AssertionError(
                "load_session should not be called when metadata.conversation_id is empty"
            )

        async def close(self) -> None:
            self.closed = True

    class DummyProcess:
        def __init__(self) -> None:
            self.closed: bool = False

    class DummyProtocolClient:
        def __init__(self, agent_id: str, event_sink) -> None:
            self.agent_id = agent_id
            self.event_sink = event_sink

    @asynccontextmanager
    async def fake_open_nate_oha_acp_client(*, command, env, cwd, agent_id, event_sink, capabilities):  # type: ignore[override]
        conn = DummyConnection()
        proc = DummyProcess()
        proto = DummyProtocolClient(agent_id, event_sink)

        try:
            yield conn, proc, proto
        finally:
            await conn.close()
            proc.closed = True

    # Patch the symbol imported into nate_ntm.runtime.acp_client so that
    # NateOhaAcpClient.start_agent_async uses the dummy connection above.
    monkeypatch.setattr(acp_mod, "open_nate_oha_acp_client", fake_open_nate_oha_acp_client, raising=True)

    # Invoke the async lifecycle entrypoint. The adapter should allocate a
    # new ACP session and persist the returned ``session_id`` into
    # per-agent metadata.
    await client.start_agent_async("agent-1", metadata=meta)

    # Reload metadata from disk and verify that conversation_id was
    # updated to the ACP-assigned session identifier.
    reloaded = store.load_agent_metadata("agent-1")
    assert reloaded.conversation_id == "acp-session-meta-123"

    # ``ensure_conversation`` should also observe the new ACP identifier via
    # its in-memory cache.
    conv_from_adapter = client.ensure_conversation("agent-1")
    assert conv_from_adapter == "acp-session-meta-123"




@pytest.mark.asyncio
async def test_nate_oha_acp_client_acp_session_id_is_deterministic_via_metadata_across_clients(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """ACP-assigned session_id persists into metadata and is reused.

    This test verifies that once ``start_agent_async`` has created a new
    ACP session for an agent and persisted the returned ``session_id``
    into :class:`AgentMetadata`, a fresh :class:`NateOhaAcpClient` with
    the same runtime configuration will derive the same conversation ID
    via :meth:`ensure_conversation`.
    """

    # First client: create a new ACP session via start_agent_async and
    # persist the resulting session_id into per-agent metadata.
    client1 = _make_nate_oha_client(tmp_path, monkeypatch)
    store1 = MetadataStore(config=client1.config)

    # Seed a minimal AgentMetadata record for the agent without any
    # pre-existing conversation_id.
    seed_meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    store1.save_agent_metadata(seed_meta)

    class DummyConnection:
        def __init__(self) -> None:
            self.closed: bool = False

        async def initialize(self, *args, **kwargs):  # pragma: no cover - not relevant
            pass

        async def new_session(self, cwd: str, **kwargs):
            class _Resp:
                def __init__(self, session_id: str) -> None:
                    self.session_id = session_id

            # Use a fixed session identifier to keep assertions simple.
            return _Resp("acp-session-cross-client-1")

        async def load_session(self, *args, **kwargs):  # pragma: no cover - not used here
            raise AssertionError(
                "load_session should not be called when metadata.conversation_id is empty"
            )

        async def close(self) -> None:
            self.closed = True

    class DummyProcess:
        def __init__(self) -> None:
            self.closed: bool = False

    class DummyProtocolClient:
        def __init__(self, agent_id: str, event_sink) -> None:
            self.agent_id = agent_id
            self.event_sink = event_sink

    @asynccontextmanager
    async def fake_open_nate_oha_acp_client(*, command, env, cwd, agent_id, event_sink, capabilities):  # type: ignore[override]
        conn = DummyConnection()
        proc = DummyProcess()
        proto = DummyProtocolClient(agent_id, event_sink)

        try:
            yield conn, proc, proto
        finally:
            await conn.close()
            proc.closed = True

    # Ensure that client1.start_agent_async uses the dummy ACP
    # connection above so we control the session_id value.
    monkeypatch.setattr(acp_mod, "open_nate_oha_acp_client", fake_open_nate_oha_acp_client, raising=True)

    await client1.start_agent_async("agent-1", metadata=seed_meta)

    # Metadata on disk should now reflect the ACP-assigned
    # "acp-session-cross-client-1" identifier.
    reloaded1 = store1.load_agent_metadata("agent-1")
    assert reloaded1.conversation_id == "acp-session-cross-client-1"

    # Second client: with the same project path and config, ensure that
    # ensure_conversation returns the persisted ACP session identifier
    # without talking to ACP again.
    client2 = _make_nate_oha_client(tmp_path, monkeypatch)

    conv2 = client2.ensure_conversation("agent-1")
    assert conv2 == "acp-session-cross-client-1"

@pytest.mark.asyncio
async def test_nate_oha_acp_client_stop_agent_async_closes_acp_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """stop_agent_async should close the ACP connection and subprocess."""

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    captured: dict[str, object] = {}

    class DummyConnection:
        def __init__(self) -> None:
            self.closed: bool = False

        async def initialize(self, *args, **kwargs):  # pragma: no cover - not relevant
            pass

        async def new_session(self, cwd: str, **kwargs):
            class _Resp:
                def __init__(self, session_id: str) -> None:
                    self.session_id = session_id

            return _Resp("acp-session-terminate")

        async def load_session(self, *args, **kwargs):  # pragma: no cover - not used in this test
            pass

        async def close(self) -> None:
            self.closed = True

    class DummyProcess:
        def __init__(self) -> None:
            self.closed: bool = False

    class DummyProtocolClient:
        def __init__(self, agent_id: str, event_sink) -> None:
            self.agent_id = agent_id
            self.event_sink = event_sink

    @asynccontextmanager
    async def fake_open_nate_oha_acp_client(*, command, env, cwd, agent_id, event_sink, capabilities):  # type: ignore[override]
        conn = DummyConnection()
        proc = DummyProcess()
        proto = DummyProtocolClient(agent_id, event_sink)

        captured["connection"] = conn
        captured["process"] = proc

        try:
            yield conn, proc, proto
        finally:
            await conn.close()
            proc.closed = True

    import nate_ntm.runtime.acp_connection as acp_conn

    # Patch the symbol imported into nate_ntm.runtime.acp_client rather than
    # the acp_connection module itself so that NateOhaAcpClient.start_agent_async
    # sees the stub.
    monkeypatch.setattr(acp_mod, "open_nate_oha_acp_client", fake_open_nate_oha_acp_client, raising=True)

    meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")

    await client.start_agent_async("agent-1", metadata=meta)

    conn = captured["connection"]
    proc = captured["process"]

    assert isinstance(conn, DummyConnection)
    assert isinstance(proc, DummyProcess)
    assert conn.closed is False
    assert proc.closed is False

    # Stopping the agent via the async API should trigger the context
    # manager's cleanup, closing the ACP connection and marking the process
    # as closed.
    await client.stop_agent_async("agent-1", timeout=5.0)

    assert conn.closed is True
    assert proc.closed is True

    # The in-memory session should be marked as terminated for future
    # status queries.
    session = client._sessions.get("agent-1")
    assert session is not None
    assert session.status == "terminated"


def test_runtime_create_with_nate_oha_acp_persists_conversation_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """REAL-style runtime creation works with NateOhaAcpClient (T220).

    This regression test exercises the create-path wiring used in US1/US2:

    * ``RuntimeDaemon.create`` uses the ACP adapter's
      ``ensure_conversation`` to allocate per-agent conversation IDs.
    * With :class:`NateOhaAcpClient` as the ACP adapter, this should no
      longer raise ``NotImplementedError`` and must result in persisted
      metadata with a non-empty, stable ``conversation_id`` for each
      created agent.
    """

    client = _make_nate_oha_client(tmp_path, monkeypatch)
    config = client.config

    # Use the in-memory FakeAgentMailClient to avoid any external I/O
    # while still exercising the RuntimeDaemon.create path.
    agent_mail = FakeAgentMailClient(config=config)
    adapters = RuntimeAdapters(agent_mail=agent_mail, acp=client)

    daemon = RuntimeDaemon.create(config, agent_count=1, adapters=adapters)

    # Metadata should contain a single agent with a non-empty
    # conversation identifier that matches the adapter's view.
    store = daemon.metadata_store
    all_meta = store.load_all_agent_metadata()
    assert set(all_meta.keys()) == {"agent-1"}

    meta = all_meta["agent-1"]
    assert meta.conversation_id
    assert daemon.swarm_metadata.agents["agent-1"].conversation_id == meta.conversation_id

    conv_from_adapter = client.ensure_conversation("agent-1")
    assert conv_from_adapter == meta.conversation_id



def test_nate_oha_acp_client_builds_command_and_env_for_agent_mail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """start_agent constructs the expected command and Agent Mail env.

    This test focuses on the process-launch contract for nate_OHA when
    Agent Mail is enabled. It verifies that the adapter:

    * builds the ``nate_OHA --enable-agent-mail`` command line
    * derives Agent Mail launch settings from :class:`RuntimeConfig` and
      :class:`AgentMetadata`
    * populates the required ``AGENT_MAIL_*`` variables, the runtime
      correlation ``NATE_NTM_*`` variables, and the ``LLM_MODEL``
      default in the child environment.
    """

    # Ensure NATE_NTM-specific Agent Mail URL variables do not interfere
    # with this test's expectations about how ``load_runtime_config``
    # resolves ``agent_mail_upstream_url``.
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_URL", raising=False)

    # Configure minimal Agent Mail settings via environment so that
    # :func:`load_runtime_config` populates ``RuntimeConfig.agent_mail_project``
    # and ``RuntimeConfig.agent_mail_upstream_url``. ``NateOhaAcpClient``
    # itself no longer reads these variables directly from :mod:`os.environ`;
    # it relies solely on the resolved runtime config.
    monkeypatch.setenv("AGENT_MAIL_PROJECT", "test-project")
    monkeypatch.setenv("AGENT_MAIL_UPSTREAM_URL", "https://agent-mail.invalid/mcp")

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    # Sanity-check that the runtime config captured the Agent Mail launch
    # settings; the ACP client uses these, not the ambient environment,
    # when constructing the child process environment.
    assert client.config.agent_mail_project == "test-project"
    assert client.config.agent_mail_upstream_url == "https://agent-mail.invalid/mcp"

    meta = AgentMetadata(
        agent_id="agent-1",
        display_name="Agent One",
        agent_mail_identity="agent-mail-identity",
        agent_mail_credentials_ref="secret-token-ref",
    )

    client.start_agent("agent-1", metadata=meta)

    popen_calls = getattr(client, "_test_popen_calls")
    assert len(popen_calls) == 1
    (args, kwargs) = popen_calls[0]

    # The first positional argument is the command list.
    cmd = args[0]
    assert cmd == ["nate_OHA", "--enable-agent-mail"]

    # The environment must include the Agent Mail and nate_ntm correlation
    # variables required by the process-launch contract, as well as the
    # default LLM model selection.
    env = kwargs.get("env")
    assert isinstance(env, dict)

    assert env["NATE_NTM_PROJECT_PATH"] == str(client.config.project_path)
    assert env["NATE_NTM_SWARM_ID"] == client.config.swarm_id
    assert env["NATE_NTM_AGENT_ID"] == "agent-1"
    assert env["LLM_MODEL"] == "openai/gpt-4o"

    # Agent Mail variables: project, identity, token, and upstream URL
    assert env["AGENT_MAIL_PROJECT"] == client.config.agent_mail_project
    assert env["AGENT_MAIL_AGENT"] == "agent-mail-identity"
    assert env["AGENT_MAIL_TOKEN"] == "secret-token-ref"
    assert env["AGENT_MAIL_UPSTREAM_URL"] == client.config.agent_mail_upstream_url


def test_nate_oha_acp_client_fails_fast_when_agent_mail_project_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Agent Mail identity set but project missing → fail before Popen.

    When ``AgentMetadata.agent_mail_identity`` is non-empty, the adapter
    # Ensure NATE_NTM-specific Agent Mail URL variables do not interfere
    # with this test's expectations about how ``load_runtime_config``
    # resolves ``agent_mail_upstream_url``.
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_URL", raising=False)


    must require a configured Agent Mail project. If neither
    ``AGENT_MAIL_PROJECT`` nor ``NATE_NTM_AGENT_MAIL_PROJECT`` is set,
    ``start_agent`` should raise :class:`AcpClientError` and avoid
    spawning a nate_OHA subprocess.
    """

    # Ensure NATE_NTM-specific Agent Mail URL variables do not interfere
    # with this test's expectations about how ``load_runtime_config``
    # resolves ``agent_mail_upstream_url``.
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_URL", raising=False)


    # Ensure no Agent Mail project is visible in the environment.
    monkeypatch.delenv("AGENT_MAIL_PROJECT", raising=False)
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_PROJECT", raising=False)

    # Provide other required Agent Mail settings so that the missing
    # project is the only failure reason.
    monkeypatch.setenv("AGENT_MAIL_UPSTREAM_URL", "https://agent-mail.invalid/mcp")

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    # Sanity-check that the runtime config reflects the intended
    # misconfiguration: project missing but upstream URL present.
    assert client.config.agent_mail_project is None
    assert client.config.agent_mail_upstream_url == "https://agent-mail.invalid/mcp"


    meta = AgentMetadata(
        agent_id="agent-1",
        display_name="Agent One",
        agent_mail_identity="agent-mail-identity",
        agent_mail_credentials_ref="secret-token-ref",
    )

    with pytest.raises(AcpClientError) as excinfo:
        client.start_agent("agent-1", metadata=meta)

    msg = str(excinfo.value)
    assert "Agent Mail project is not configured" in msg

    # The subprocess layer should not be invoked on configuration errors.
    popen_calls = getattr(client, "_test_popen_calls")
    assert popen_calls == []



def test_nate_oha_acp_client_fails_fast_when_agent_mail_upstream_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Agent Mail identity set but upstream URL missing → fail before Popen.

    This is the symmetric case to the missing-project test: with a
    configured project and identity but no upstream URL, ``start_agent``
    must raise :class:`AcpClientError` and never call ``subprocess.Popen``.
    """

    # Configure a project but deliberately omit all recognized upstream
    # URL variables.
    monkeypatch.setenv("AGENT_MAIL_PROJECT", "test-project")
    monkeypatch.delenv("AGENT_MAIL_UPSTREAM_URL", raising=False)
    monkeypatch.delenv("NATE_NTM_AGENT_MAIL_URL", raising=False)
    monkeypatch.delenv("AGENT_MAIL_URL", raising=False)

    client = _make_nate_oha_client(tmp_path, monkeypatch)

    # Sanity-check that the runtime config reflects the intended
    # misconfiguration: project present but upstream URL missing.
    assert client.config.agent_mail_project == "test-project"
    assert client.config.agent_mail_upstream_url is None


    meta = AgentMetadata(
        agent_id="agent-1",
        display_name="Agent One",
        agent_mail_identity="agent-mail-identity",
        agent_mail_credentials_ref="secret-token-ref",
    )

    with pytest.raises(AcpClientError) as excinfo:
        client.start_agent("agent-1", metadata=meta)

    msg = str(excinfo.value)
    assert "Agent Mail upstream URL is not configured" in msg

    popen_calls = getattr(client, "_test_popen_calls")
    assert popen_calls == []



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

