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
persisted into :class:`AgentMetadata.conversation_id` and reused via
:meth:`ensure_conversation` and
:meth:`RuntimeDaemon.get_agent_detail`.

Unlike the focused unit tests in
``tests/unit/runtime/test_nate_oha_acp_client_async.py``, this test does
*not* patch :func:`open_nate_oha_acp_client`. It launches a real
``nate-oha`` subprocess via the ACP SDK and relies on the configured
``mcp_agent_mail`` service for the Agent Mail project lookup in resume
mode.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os

import pytest

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import AgentMetadata, MetadataStore, SwarmMetadata


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
      :class:`AgentMetadata.conversation_id` on disk and cached in the
      adapter's in-memory session map.
    * A fresh :class:`NateOhaAcpClient` instance with the same
      :class:`RuntimeConfig` reuses the same identifier via
      :meth:`ensure_conversation`.
    * :meth:`RuntimeDaemon.get_agent_detail` surfaces the persisted
      conversation identifier even when no live runtime state entry
      exists for the agent yet.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    # Take an explicit snapshot of the current environment so that
    # ``load_runtime_config`` does not consult repository-level .env
    # files. We then overlay the adapter-mode selection to force REAL
    # adapters for both Agent Mail and ACP.
    env_snapshot = dict(os.environ)
    env_snapshot.update(
        {
            "NATE_NTM_PROJECT_DIR": str(project),
            "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
        }
    )

    # Use an explicit Agent Mail project key so that FR-009 resume
    # rebinding checks for the REAL adapter compare deterministic
    # strings instead of relying on the project-path default.
    config = load_runtime_config(
        project_path=project,
        agent_mail_project="ntm-epic005-acp-e2e-project",
        env=env_snapshot,
    )

    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)

    # Seed a single agent with no pre-existing ACP conversation
    # identifier so that start_agent_async must call ``session/new``.
    meta = AgentMetadata(
        agent_id="nav-async-1",
        display_name="Navigator Async 1",
        agent_mail_identity="",  # Agent Mail is optional for this test.
        conversation_id="",  # Force the "session/new" path.
    )

    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id=config.agent_mail_project
        or "ntm-epic005-acp-e2e-project",
        created_at=now,
        last_updated_at=now,
        agents={meta.agent_id: meta},
    )
    store.save_swarm_metadata(swarm)
    store.save_agent_metadata(meta)

    # Construct REAL adapters (McpAgentMailClient + NateOhaAcpClient) and
    # hand them to RuntimeDaemon so the daemon owns the integration
    # clients for this run.
    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.acp, NateOhaAcpClient)

    # Point the ACP adapter at the installed ``nate-oha`` binary used in
    # this repository. The default ``"nate_OHA"`` name is correct for the
    # upstream CLI but does not match the local binary on all systems.
    adapters.acp.executable = "nate-oha"  # type: ignore[attr-defined]

    daemon = RuntimeDaemon.resume(config, adapters=adapters)

    # Sanity: the scheduler has not yet registered any runtime state
    # entries; this test focuses on metadata + ACP session semantics
    # rather than scheduler-driven status updates.
    assert daemon.state.agents == {}

    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    # Establish a real ACP session for the agent using the async
    # lifecycle. This launches a nate-oha subprocess via the ACP SDK and
    # negotiates capabilities + a new session.
    await acp_client.start_agent_async(meta.agent_id, metadata=meta)

    try:
        # After async start, the adapter should have a live session
        # record with an opaque ACP ``session_id``.
        session = acp_client._sessions.get(meta.agent_id)  # type: ignore[attr-defined]
        assert session is not None
        session_id = session.conversation_id
        assert isinstance(session_id, str) and session_id

        # The same identifier must have been persisted into
        # AgentMetadata.conversation_id on disk.
        reloaded_meta = store.load_agent_metadata(meta.agent_id)
        assert reloaded_meta.conversation_id == session_id

        # A fresh NateOhaAcpClient with the same configuration must reuse
        # that identifier via ensure_conversation, reflecting the Epic 005
        # invariant that ACP's opaque ``session_id`` is the canonical
        # conversation identifier.
        fresh_client = NateOhaAcpClient(config=config, executable="nate-oha")
        conv2 = fresh_client.ensure_conversation(meta.agent_id)
        assert conv2 == session_id

        # RuntimeDaemon.get_agent_detail should surface the persisted
        # conversation identifier even when no live runtime state exists
        # yet for the agent.
        detail = daemon.get_agent_detail(agent_id=meta.agent_id, max_events=10)
        agent_payload = detail["agent"]
        assert agent_payload["conversation_id"] == session_id

    finally:
        # Best-effort cleanup of the ACP session and underlying
        # subprocess so the test does not leak nate-oha processes.
        await acp_client.stop_agent_async(meta.agent_id, timeout=5.0)
