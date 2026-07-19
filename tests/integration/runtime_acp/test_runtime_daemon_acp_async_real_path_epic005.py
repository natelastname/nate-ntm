"""Epic 005: end-to-end async ACP session persistence with REAL adapters.

This integration test ties together several runtime components using their
production implementations:

* :class:`RuntimeDaemon` in ``resume`` mode.
* :func:`create_runtime_adapters` with ``AdapterKind.REAL`` so that
  :class:`McpAgentMailClient` and :class:`NateOhaAcpClient` are used.
* The async ACP lifecycle on :class:`NateOhaAcpClient` via
  :meth:`start_agent_async` / :meth:`stop_agent_async`.

    The goal is to exercise the real ACP SDK wiring for Epic 005 and to
    validate that the opaque ``session_id`` returned by ``session/new`` is
    persisted into :class:`AgentState.conversation_id` and reused across
    runs via :meth:`NateOhaAcpClient.start_agent_async` and
    :meth:`RuntimeDaemon.get_agent_detail`.

Unlike the focused unit tests in
``tests/unit/runtime/test_nate_oha_acp_client_async.py``, this test does
*not* patch :func:`open_nate_oha_acp_client`. It launches a real
``nate-oha`` subprocess via the ACP SDK and relies on the configured
``mcp_agent_mail`` service for the Agent Mail project lookup in resume
mode.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable

import pytest

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.acp_update_stream import ReceivedSessionUpdate
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.agent_mail_client import McpAgentMailClient
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.nate_oha_launch import build_effective_nate_oha_config
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


def _extract_text_from_updates(updates: list[ReceivedSessionUpdate]) -> list[str]:
    """Return all text content payloads from ACP session updates.

    This helper is intentionally tolerant of different ACP update kinds
    (for example ``user_message_chunk`` vs ``agent_message_chunk``) and
    focuses solely on the ``content.text`` field when present in the
    underlying ACP model.
    """

    texts: list[str] = []
    for received in updates:
        update = received.update
        # ACP SDK models are Pydantic; prefer model_dump(by_alias=True) so
        # field names match the wire protocol.
        if hasattr(update, "model_dump"):
            payload = update.model_dump(by_alias=True)
        elif isinstance(update, dict):
            payload = update
        else:
            continue

        if not isinstance(payload, dict):
            continue

        content = payload.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return texts


async def collect_updates_for(
    updates: AsyncIterator[ReceivedSessionUpdate],
    sink: list[ReceivedSessionUpdate],
    *,
    duration: float,
) -> None:
    """Collect updates into ``sink`` for approximately ``duration`` seconds.

    The helper stops when the duration elapses, the underlying update stream
    closes, or no further updates arrive before the deadline.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            item = await asyncio.wait_for(updates.__anext__(), timeout=remaining)
        except (asyncio.TimeoutError, StopAsyncIteration):
            break
        sink.append(item)


async def _wait_for_text(
    updates: AsyncIterator[ReceivedSessionUpdate],
    expected: str,
    *,
    timeout: float = 5.0,
    sink: list[ReceivedSessionUpdate] | None = None,
) -> ReceivedSessionUpdate:
    """Wait for a single update whose text content contains ``expected``.

    The caller is responsible for creating the subscription via
    :meth:`NateOhaAcpClient.subscribe_acp_updates` so that the subscription is
    active before any prompts or other actions that may emit updates.
    """

    async def _runner() -> ReceivedSessionUpdate:
        async for item in updates:
            if sink is not None:
                sink.append(item)
            texts = _extract_text_from_updates([item])
            if any(expected in text for text in texts):
                return item

        raise RuntimeError("update stream closed before expected text observed")

    if timeout is None:
        return await _runner()

    return await asyncio.wait_for(_runner(), timeout=timeout)


@pytest.mark.asyncio
async def test_runtime_daemon_acp_async_persists_session_id_and_exposes_via_detail(
    tmp_path: Path,
) -> None:
    """REAL-path async ACP session persistence and reuse (Epic 005).

    This test exercises the async ACP lifecycle using the real
    :class:`NateOhaAcpClient` and ACP SDK:

    * Swarm and agent metadata are created with an empty
      ``conversation_id`` so that :meth:`start_agent_async` takes the
      ``session/new`` path.
    * :class:`RuntimeDaemon` is constructed in ``resume`` mode with REAL
      adapters provided by :func:`create_runtime_adapters`, wiring in a
      :class:`McpAgentMailClient` and :class:`NateOhaAcpClient`.
    * :meth:`NateOhaAcpClient.start_agent_async` establishes an ACP
      session and receives an opaque ``session_id`` from the server.
    * That ``session_id`` is persisted into
      :class:`AgentState.conversation_id` on disk and cached in the
      adapter's in-memory session map.
    * A fresh :class:`NateOhaAcpClient` instance with the same
      :class:`RuntimeConfig` reuses the same identifier when
      :meth:`start_agent_async` is invoked with the persisted metadata.
    * :meth:`RuntimeDaemon.get_agent_detail` surfaces the persisted
      conversation identifier even when no live runtime state entry
      exists for the agent yet.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    # Point nate-oha at the sample profile used throughout this repository
    # for real-path tests. Using an existing config mirrors the quickstart
    # flow and ensures that ``--set runtime.mode=...`` overrides operate on
    # a valid base tree.
    repo_root = Path(__file__).resolve().parents[3]
    base_config = repo_root / "nate-oha-profiles" / "profile1.json"

    # Take an explicit snapshot of the current environment so that
    # ``load_runtime_config`` does not consult repository-level .env
    # files. We then overlay the adapter-mode selection to force REAL
    # adapters for both Agent Mail and ACP and supply the nate-oha
    # launch settings required by :func:`build_nate_oha_launch_spec`.
    env_snapshot = dict(os.environ)
    env_snapshot.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
            # Minimal nate-oha launch configuration: point nate-oha at the
            # repository's sample profile and run in "echo" mode so the
            # test focuses on ACP/session semantics rather than model
            # behaviour.
            "NATE_NTM_NATE_OHA_CONFIG": str(base_config),
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
        }
    )

    # Resolve a REAL-adapter RuntimeConfig. For the REAL Agent Mail
    # adapter, the project key used for ensure_project is derived from
    # :attr:`RuntimeConfig.agent_mail_project` when set, otherwise from
    # the absolute project path. In this test we rely on that default so
    # that the swarm's ``agent_mail_project_id`` matches the project
    # directory path.
    config = load_runtime_config(
        project_path=project,
        env=env_snapshot,
    )

    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)

    # Seed a single agent with no pre-existing ACP conversation
    # identifier so that start_agent_async must call ``session/new``.
    # Agent Mail is optional for this scenario and is therefore omitted
    # from the durable AgentState schema; the effective nate-oha
    # configuration is derived purely from the runtime config, and the
    # ACP conversation identifier remains a separate field on
    # :class:`AgentState`.
    nate_oha_cfg = build_effective_nate_oha_config(config=config)

    meta = AgentState(
        agent_id="nav-async-1",
        display_name="Navigator Async 1",
        conversation_id="",  # Force the "session/new" path.
        nate_oha_config=nate_oha_cfg,
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        # For REAL adapters the Agent Mail project identifier used by the
        # runtime and persisted into swarm metadata is derived from
        # :attr:`RuntimeConfig.agent_mail_project` or, when unset, from the
        # absolute project path. Here we mirror the latter so that
        # RuntimeDaemon.resume's FR-009 project rebinding checks compare
        # the same key that :class:`McpAgentMailClient.ensure_project`
        # will derive.
        agent_mail_project_id=str(config.project_path),
        created_at=now,
        last_updated_at=now,
        agents={meta.agent_id: meta},
    )
    store.save_swarm_state(swarm)

    # Construct REAL adapters (McpAgentMailClient + NateOhaAcpClient) and
    # hand them to RuntimeDaemon so the daemon owns the integration
    # clients for this run.
    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.acp, NateOhaAcpClient)

    adapters.acp.executable = "nate-oha"  # type: ignore[attr-defined]

    daemon = RuntimeDaemon.resume(config, adapters=adapters)

    # Sanity: the scheduler has not yet registered any runtime state
    # entries; this test focuses on metadata + ACP session semantics
    # rather than scheduler-driven status updates.
    assert daemon.state.agents == {}

    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    # Capture ACP session updates emitted during the initial async session so
    # we can assert that the real ACP SDK wiring is exercised. Updates are
    # observed via the typed subscription-based API rather than a global
    # callback.
    updates_run1: list[ReceivedSessionUpdate] = []

    # Establish a real ACP session for the agent using the async
    # lifecycle. This launches a nate-oha subprocess via the ACP SDK and
    # negotiates capabilities + a new session.
    await acp_client.start_agent_async(meta.agent_id, metadata=meta)

    async with acp_client.subscribe_acp_updates(meta.agent_id) as updates:
        # Allow a short window for ACP session updates to be delivered
        # through the protocol client while collecting typed
        # ReceivedSessionUpdate values.
        await collect_updates_for(updates, updates_run1, duration=0.5)

    fresh_client: NateOhaAcpClient | None = None

    try:
        # After async start, the canonical conversation identifier is the
        # value persisted into :class:`AgentState.conversation_id` on disk.
        # For nate-oha / ACP this must be the opaque ``session_id`` assigned
        # by the server.
        reloaded_meta = store.load_agent_state(meta.agent_id)
        session_id = reloaded_meta.conversation_id
        assert isinstance(session_id, str) and session_id

        # If any ACP updates were observed during the first run, this
        # confirms that the real ACP SDK connection was active for the
        # newly created session.
        assert updates_run1

        # Construct a fresh NateOhaAcpClient with the same configuration for
        # the second run. The async lifecycle helpers will reuse the
        # persisted ACP ``session_id`` via ``start_agent_async``.
        fresh_client = NateOhaAcpClient(config=config, executable="nate-oha")

        # Second run: resume the existing ACP session from persisted
        # metadata using the async lifecycle. This exercises the
        # ``load_session`` path in start_agent_async against a real Nate
        # OHA instance.
        updates_run2: list[ReceivedSessionUpdate] = []

        resume_meta = store.load_agent_state(meta.agent_id)
        assert resume_meta.conversation_id == session_id

        await fresh_client.start_agent_async(meta.agent_id, metadata=resume_meta)

        async with fresh_client.subscribe_acp_updates(meta.agent_id) as updates2:
            # Collect a short burst of ACP updates from the resumed session.
            await collect_updates_for(updates2, updates_run2, duration=0.5)

        # Across both runs we expect to see at least one ACP-derived
        # session update, confirming that the real ACP SDK wiring was
        # exercised using the typed update stream.
        all_updates = updates_run1 + updates_run2
        assert all_updates

    finally:
        # Best-effort cleanup of the resumed session, if it was started.
        if fresh_client is not None:
            try:
                await fresh_client.stop_agent_async(meta.agent_id, timeout=5.0)
            except Exception:
                # Cleanup failures should not mask assertion failures.
                pass

        # RuntimeDaemon.get_agent_detail should surface the persisted
        # conversation identifier even when no live runtime state exists
        # yet for the agent.
        detail = daemon.get_agent_detail(agent_id=meta.agent_id, max_events=10)
        agent_payload = detail["agent"]
        assert agent_payload["conversation_id"] == session_id

        # Best-effort cleanup of the ACP session and underlying
        # subprocess so the test does not leak nate-oha processes.
        await acp_client.stop_agent_async(meta.agent_id, timeout=5.0)


@pytest.mark.asyncio
async def test_runtime_daemon_acp_async_with_agent_mail_real_path_epic005(tmp_path: Path) -> None:
    """REAL-path async ACP + Agent Mail integration (Epic 005).

    This test extends the main Epic 005 scenario to exercise the REAL
    :class:`McpAgentMailClient` alongside the REAL
    :class:`NateOhaAcpClient` and ACP SDK wiring. It assumes that a
    live Agent Mail MCP server is reachable at the URL resolved by
    :class:`McpAgentMailClient` (for example,
    ``http://127.0.0.1:8765/api``) and treats missing or unreachable
    Agent Mail as a **hard failure** rather than skipping the test.

    High-level invariants:

    * Agent Mail project/identity/credentials are allocated via
      :class:`McpAgentMailClient` and persisted into swarm + agent
      metadata before any ACP session is created.
    * :meth:`RuntimeDaemon.resume` revalidates the Agent Mail project
      and per-agent identity against the live service using the REAL
      adapter, enforcing FR-009.
    * :meth:`NateOhaAcpClient.start_agent_async` establishes a real ACP
      session for the agent, obtaining an opaque ``session_id`` that is
      persisted into :class:`AgentState.conversation_id`.
    * A fresh :class:`NateOhaAcpClient` instance with the same
      :class:`RuntimeConfig` reuses the same identifier when
      :meth:`start_agent_async` is invoked with the persisted metadata.
    * :meth:`RuntimeDaemon.get_agent_detail` surfaces the persisted
      ``conversation_id`` even when no live runtime state entry exists
      yet for the agent.

    Any misconfiguration of Agent Mail (for example missing project ID
    or upstream URL) or failure to reach the Agent Mail server is
    surfaced as an :class:`AgentMailClientError` or
    :class:`RuntimeStartupError`, causing this test to fail rather than
    being skipped.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[3]
    base_config = repo_root / "nate-oha-profiles" / "profile1.json"

    # Configure REAL adapters, including Agent Mail. We explicitly set
    # the Agent Mail project key and upstream URL so that
    # :class:`RuntimeConfig` and :class:`McpAgentMailClient` derive the
    # same values and :meth:`NateOhaAcpClient._build_env` sees a fully
    # configured Agent Mail environment when an identity is present.
    env_snapshot = dict(os.environ)
    env_snapshot.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
            "NATE_NTM_NATE_OHA_CONFIG": str(base_config),
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
            # Agent Mail configuration: hard requirement for this test.
            # The project key is chosen to be the absolute project path
            # so that it matches the FR-009 rebinding semantics used by
            # other REAL-path tests.
            "NATE_NTM_AGENT_MAIL_PROJECT": str(project),
            # Upstream URL must point at a live Agent Mail MCP server.
            # If the server is unreachable or misconfigured, the test
            # fails via AgentMailClientError.
            "NATE_NTM_AGENT_MAIL_URL": "http://127.0.0.1:8765/api",
            # Explicitly enable Agent Mail so that build_effective_nate_oha_config
            # materialises ``features.agent_mail`` in the effective config.
            "NATE_NTM_AGENT_MAIL_ENABLED": "true",
        }
    )

    config = load_runtime_config(
        project_path=project,
        env=env_snapshot,
    )

    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)

    # Construct REAL adapters and use the REAL Agent Mail client to
    # allocate a project and per-agent identity/credentials **before**
    # seeding swarm metadata. This ensures that the on-disk metadata
    # reflects the live Agent Mail registration state.
    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.agent_mail, McpAgentMailClient)
    assert isinstance(adapters.acp, NateOhaAcpClient)

    agent_mail_client = adapters.agent_mail
    acp_client = adapters.acp

    agent_id = "nav-async-mail-1"

    # Ensure the Agent Mail project exists and record the canonical
    # project identifier used by the runtime. Any network or
    # authentication error here is treated as a hard failure.
    agent_mail_project_id = agent_mail_client.ensure_project()

    # Allocate an Agent Mail identity + credentials for this agent via
    # the REAL adapter. The returned values are persisted into the
    # effective NateOhaConfig instead of separate AgentState fields so
    # that later resume flows and ACP launches can reuse them.
    identity, token = agent_mail_client.ensure_agent_identity_with_credentials(agent_id)
    assert identity
    assert token

    nate_oha_cfg = build_effective_nate_oha_config(
        config=config,
        agent_mail_identity=identity,
        agent_mail_credentials_ref=token,
    )

    meta = AgentState(
        agent_id=agent_id,
        display_name="Navigator Async Mail 1",
        conversation_id="",  # Force the ACP "session/new" path on first run.
        nate_oha_config=nate_oha_cfg,
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id=agent_mail_project_id,
        created_at=now,
        last_updated_at=now,
        agents={meta.agent_id: meta},
    )

    store.save_swarm_state(swarm)

    # Reuse the already-constructed REAL adapters when resuming the
    # runtime so that :meth:`RuntimeDaemon.resume` can rebind Agent Mail
    # and ACP identifiers against the same adapter instances.
    daemon = RuntimeDaemon.resume(config, adapters=adapters)

    # Sanity: scheduler has not yet registered any runtime state
    # entries; this test focuses on metadata + Agent Mail + ACP session
    # semantics rather than scheduler-driven status updates.
    assert daemon.state.agents == {}

    assert isinstance(daemon.agent_mail_client, McpAgentMailClient)
    assert isinstance(daemon.acp_client, NateOhaAcpClient)

    # Align the ACP adapter's executable with the installed ``nate-oha``
    # binary used in this repository.
    daemon.acp_client.executable = "nate-oha"  # type: ignore[attr-defined]

    acp_client = daemon.acp_client

    updates_run1: list[ReceivedSessionUpdate] = []

    # First async run: establish a real ACP session for the agent using
    # the async lifecycle. This launches ``nate-oha acp`` via the ACP
    # SDK with Agent Mail integration enabled.
    start_meta = store.load_agent_state(agent_id)
    await acp_client.start_agent_async(agent_id, metadata=start_meta)

    async with acp_client.subscribe_acp_updates(agent_id) as updates:
        # Collect a short burst of ACP updates from the initial session.
        await collect_updates_for(updates, updates_run1, duration=0.5)

    fresh_client: NateOhaAcpClient | None = None

    try:
        # The canonical conversation identifier is the value persisted
        # into :class:`AgentState.conversation_id` on disk. For Nate
        # OHA / ACP this must be the opaque ``session_id`` assigned by
        # the server.
        reloaded_meta = store.load_agent_state(agent_id)
        session_id = reloaded_meta.conversation_id
        assert isinstance(session_id, str) and session_id

        # Agent Mail identity and credentials must remain unchanged
        # across the ACP session. These are now stored inside the
        # embedded NateOhaConfig rather than as separate AgentState
        # fields.
        cfg = getattr(reloaded_meta, "nate_oha_config", None)
        features = getattr(cfg, "features", None) if cfg is not None else None
        agent_mail_cfg = getattr(features, "agent_mail", None) if features is not None else None
        assert agent_mail_cfg is not None
        assert (agent_mail_cfg.agent_identity or "").strip() == identity
        assert (agent_mail_cfg.credentials_ref or "") == (token or "")

        # Any ACP updates observed during the first run confirm that the
        # real ACP SDK connection was active for the new session.
        assert updates_run1

        # Construct a fresh NateOhaAcpClient with the same configuration for
        # the second run. The async lifecycle helpers will reuse the
        # persisted ACP ``session_id`` via ``start_agent_async``.
        fresh_client = NateOhaAcpClient(config=config, executable="nate-oha")

        # Second async run: resume the existing ACP session from
        # persisted metadata using the async lifecycle. This exercises
        # the ``load_session`` path in start_agent_async against a real
        # nate-oha instance with Agent Mail enabled.
        updates_run2: list[ReceivedSessionUpdate] = []

        resume_meta = store.load_agent_state(agent_id)
        assert resume_meta.conversation_id == session_id

        await fresh_client.start_agent_async(agent_id, metadata=resume_meta)

        async with fresh_client.subscribe_acp_updates(agent_id) as updates2:
            # Collect a short burst of ACP updates from the resumed session.
            await collect_updates_for(updates2, updates_run2, duration=0.5)

        # Across both runs we expect to see at least one ACP-derived
        # session update, confirming that the real ACP SDK wiring was
        # exercised with Agent Mail enabled using the typed update stream.
        all_updates = updates_run1 + updates_run2
        assert all_updates

        # RuntimeDaemon.get_agent_detail should surface both the
        # persisted Agent Mail identity and the ACP-owned conversation
        # identifier even when no live runtime state exists yet for the
        # agent.
        detail = daemon.get_agent_detail(agent_id=agent_id, max_events=10)
        agent_payload = detail["agent"]
        assert agent_payload["conversation_id"] == session_id
        assert agent_payload["agent_mail_identity"] == identity

    finally:
        # Best-effort cleanup of the resumed session, if it was started.
        if fresh_client is not None:
            try:
                await fresh_client.stop_agent_async(agent_id, timeout=5.0)
            except Exception:
                # Cleanup failures should not mask assertion failures.
                pass

        # Best-effort cleanup of the initial ACP session and underlying
        # subprocess so the test does not leak nate-oha processes.
        await acp_client.stop_agent_async(agent_id, timeout=5.0)


@pytest.mark.asyncio
async def test_runtime_daemon_acp_async_prompt_echo_and_replay_real_path(tmp_path: Path) -> None:
    """REAL-path async prompt -> echo -> resume -> replay semantics (Epic 005).

    This test extends the basic async session-persistence scenario by
    driving a full prompt/response cycle through the real nate-oha ACP
    adapter:

    * Start a nate-oha ACP session in echo mode via start_agent_async.
    * Send a user prompt via NateOhaAcpClient.prompt.
    * Observe echoed text in ACP session updates.
    * Stop the session and resume it using the persisted ACP session_id.
    * Observe the prior conversation history being replayed on resume.
    * Send a new prompt after replay and observe continued interaction.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[3]
    base_config = repo_root / "nate-oha-profiles" / "profile1.json"

    env_snapshot = dict(os.environ)
    env_snapshot.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
            "NATE_NTM_NATE_OHA_CONFIG": str(base_config),
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
        }
    )

    config = load_runtime_config(
        project_path=project,
        env=env_snapshot,
    )

    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)

    agent_id = "nav-async-echo-replay-1"

    # Build the effective NateOhaConfig for this agent based solely on
    # the runtime configuration. Agent Mail is not required for this
    # echo/replay scenario and the ACP conversation identifier remains a
    # separate field on :class:`AgentState`.
    nate_oha_cfg = build_effective_nate_oha_config(config=config)

    meta = AgentState(
        agent_id=agent_id,
        display_name="Navigator Async Echo Replay",
        conversation_id="",      # Force ACP session/new on first run.
        nate_oha_config=nate_oha_cfg,
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id=str(config.project_path),
        created_at=now,
        last_updated_at=now,
        agents={meta.agent_id: meta},
    )
    store.save_swarm_state(swarm)

    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.acp, NateOhaAcpClient)
    adapters.acp.executable = "nate-oha"  # type: ignore[attr-defined]

    daemon = RuntimeDaemon.resume(config, adapters=adapters)
    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    updates_run1: list[ReceivedSessionUpdate] = []

    # ------------------------------
    # First run: start, prompt, echo
    # ------------------------------

    prompt_text1 = "hello from async epic005"

    # Establish the async ACP session, then subscribe to the typed update
    # stream before sending the prompt so we observe both replayed history
    # and live echo updates.
    await acp_client.start_agent_async(agent_id, metadata=meta)

    async with acp_client.subscribe_acp_updates(agent_id) as updates1:
        await acp_client.prompt(agent_id, prompt_text1)
        await _wait_for_text(updates1, prompt_text1, timeout=5.0, sink=updates_run1)

    reloaded_meta = store.load_agent_state(agent_id)
    session_id = reloaded_meta.conversation_id
    assert isinstance(session_id, str) and session_id

    # Extract all text content carried in ACP updates from the first run and
    # ensure that at least one update contains the echoed prompt.
    texts_run1 = _extract_text_from_updates(updates_run1)
    assert any(prompt_text1 in text for text in texts_run1)

    # Use the first echoed text containing the prompt as the canonical
    # conversation fragment we expect to be replayed on resume.
    canonical_echo1 = next(text for text in texts_run1 if prompt_text1 in text)

    # ------------------------------
    # Stop and resume: replay history
    # ------------------------------

    await acp_client.stop_agent_async(agent_id, timeout=5.0)

    fresh_client = NateOhaAcpClient(config=config, executable="nate-oha")
    updates_run2: list[ReceivedSessionUpdate] = []

    resume_meta = store.load_agent_state(agent_id)
    assert resume_meta.conversation_id == session_id

    try:
        # Replay phase: observe prior conversation history on resume.
        await fresh_client.start_agent_async(agent_id, metadata=resume_meta)

        async with fresh_client.subscribe_acp_updates(agent_id) as updates2:
            # Wait explicitly for replay of the canonical echoed text from the
            # first run rather than relying on a fixed time window.
            await _wait_for_text(updates2, canonical_echo1, timeout=5.0, sink=updates_run2)

        texts_run2_before = _extract_text_from_updates(updates_run2)
        assert canonical_echo1 in texts_run2_before

        # ------------------------------
        # New prompt after replay
        # ------------------------------

        prompt_text2 = "second prompt after replay"

        async with fresh_client.subscribe_acp_updates(agent_id) as updates3:
            await fresh_client.prompt(agent_id, prompt_text2)
            await _wait_for_text(updates3, prompt_text2, timeout=5.0, sink=updates_run2)

    finally:
        # Best-effort cleanup of the resumed session.
        try:
            await fresh_client.stop_agent_async(agent_id, timeout=5.0)
        finally:
            # Nothing else to clean; the original daemon's session was already
            # stopped above.
            pass
