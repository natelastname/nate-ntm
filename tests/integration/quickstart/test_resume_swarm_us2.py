"""Quickstart-style integration tests for US2 swarm resume semantics.

These tests correspond to T025 in ``tasks.md`` and exercise a thin
end-to-end path from a project directory on disk through:

* ``RuntimeConfig`` resolution for that project.
* ``RuntimeDaemon.create`` in ``create`` mode with a small agent set.
* Clean shutdown of the initial runtime instance.
* ``RuntimeDaemon.resume`` startup semantics against the same metadata.
* ``RuntimeApiServer`` handlers for ``runtime.get_status`` and
  ``swarm.get_overview``.

The goal for this first US2 slice is to validate FR-009 and SC-002 at a
basic level: when a swarm is created and later resumed, all agents must
reuse their persisted Agent Mail identities and ACP conversation
identifiers, and the runtime API must continue to expose consistent
swarm/agent views for the resumed instance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import pytest

from nate_ntm.api.server import RuntimeApiServer
from nate_ntm.config.runtime_config import AdapterKind, RuntimeConfig, load_runtime_config
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient
from nate_ntm.runtime.daemon import RuntimeDaemon, RuntimeStartupError
from nate_ntm.runtime.state import RuntimeStatus


def _get_persisted_identity_and_conversation(meta: object) -> Tuple[str, str]:
    """Return the persisted Agent Mail identity and conversation ID for ``meta``.

    The authoritative source of Agent Mail configuration is the effective
    NateOhaConfig attached to :class:`AgentState`. When available, we read the
    ``agent_identity`` from ``features.agent_mail``; otherwise we fall back to
    the legacy ``AgentState.agent_mail_identity`` field for older swarms that
    pre-date the embedded NateOhaConfig model.
    """

    cfg = getattr(meta, "nate_oha_config", None)
    features = getattr(cfg, "features", None) if cfg is not None else None
    agent_mail_cfg = getattr(features, "agent_mail", None) if features is not None else None

    if agent_mail_cfg is not None:
        identity = (getattr(agent_mail_cfg, "agent_identity", "") or "").strip()
    else:
        identity = (getattr(meta, "agent_mail_identity", "") or "").strip()

    conversation_id = (getattr(meta, "conversation_id", "") or "")
    return identity, conversation_id


def _create_swarm_with_agents(tmp_path: Path, agent_count: int) -> Tuple[RuntimeConfig, Dict[str, Tuple[str, str]]]:
    """Create a new swarm with ``agent_count`` agents via RuntimeDaemon.create.

    This helper mirrors the US1 quickstart behavior but returns the
    persisted identity/conversation tuples for each agent so that US2
    tests can assert that those values are reused on resume.
    """

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    config: RuntimeConfig = load_runtime_config(project_path=project)

    # Construct and start a fresh runtime in ``create`` mode.
    daemon = RuntimeDaemon.create(config, agent_count=agent_count)
    daemon.start()

    # Capture the persisted Agent Mail identities and ACP conversation IDs
    # from the swarm state. These are expected to be durable across
    # resume and must not be regenerated.
    swarm = daemon.swarm_state
    identities: Dict[str, Tuple[str, str]] = {}
    for agent_id, meta in swarm.agents.items():
        identities[agent_id] = _get_persisted_identity_and_conversation(meta)

    # Drive a clean, in-process shutdown to mirror the quickstart flow.
    daemon.request_shutdown()
    daemon.mark_stopped()

    return config, identities




def _create_swarm_with_agents_real_acp(tmp_path: Path, agent_count: int) -> Tuple[RuntimeConfig, Dict[str, Tuple[str, str]]]:
    """Create a swarm using NateOhaAcpClient (REAL ACP) for US2 tests.

    This helper mirrors :func:`_create_swarm_with_agents` but configures the
    runtime to use ``AdapterKind.REAL`` for ACP so that conversation
    identifiers are allocated via :class:`NateOhaAcpClient` while Agent Mail
    continues to use the in-memory fake adapter.
    """

    project = tmp_path / "project-real-acp"
    project.mkdir(parents=True, exist_ok=True)

    env = {
        # Restrict REAL mode to the ACP adapter so Agent Mail remains fake
        # and fully in-memory for offline CI.
        "NATE_NTM_ACP_ADAPTER": AdapterKind.REAL.value,
    }
    config: RuntimeConfig = load_runtime_config(project_path=project, env=env)

    daemon = RuntimeDaemon.create(config, agent_count=agent_count)
    # Sanity-check that the expected adapters are in use.
    assert isinstance(daemon.acp_client, NateOhaAcpClient)
    assert isinstance(daemon.agent_mail_client, FakeAgentMailClient)

    daemon.start()

    swarm = daemon.swarm_state
    identities: Dict[str, Tuple[str, str]] = {}
    for agent_id, meta in swarm.agents.items():
        identities[agent_id] = _get_persisted_identity_and_conversation(meta)

    daemon.request_shutdown()
    daemon.mark_stopped()

    return config, identities


def test_resume_swarm_us2_reuses_agent_identities_and_conversations(tmp_path: Path) -> None:
    """US2: resume reuses Agent Mail identities and ACP conversations.

    This test exercises a simple create → shutdown → resume cycle for a
    small fake swarm and asserts that the resumed runtime observes the
    same Agent Mail identities and ACP conversation identifiers for each
    agent as were persisted at creation time.
    """

    # Arrange: create a swarm with two agents and capture their identities.
    config, identities_before = _create_swarm_with_agents(tmp_path, agent_count=2)

    # Act: resume the swarm from the same project metadata.
    daemon = RuntimeDaemon.resume(config)
    daemon.start()

    # The resumed daemon should report ``Running`` at the runtime level.
    assert daemon.state.status is RuntimeStatus.RUNNING

    # The swarm state loaded on resume must contain the same agents and
    # the same identity/conversation tuples as at creation time.
    swarm_after = daemon.swarm_state
    identities_after: Dict[str, Tuple[str, str]] = {}
    for agent_id, meta in swarm_after.agents.items():
        identities_after[agent_id] = _get_persisted_identity_and_conversation(meta)

    assert identities_after == identities_before

    # Sanity-check: the runtime API still exposes consistent status and
    # overview information for the resumed swarm.
    server = RuntimeApiServer(daemon=daemon)

    status = server.get_runtime_status()
    assert status["status"] == RuntimeStatus.RUNNING.value
    assert status["project_path"] == str(config.project_path)
    assert status["swarm_id"] == config.swarm_id

    counts = status["agent_counts"]
    assert counts["total"] == len(identities_before)

    overview = server.get_swarm_overview()
    assert overview["swarm_id"] == config.swarm_id
    assert overview["project_path"] == str(config.project_path)
    assert overview["runtime_status"] == RuntimeStatus.RUNNING.value
    assert len(overview["agents"]) == len(identities_before)


def test_resume_swarm_us2_reuses_identities_and_conversations_with_real_acp(tmp_path: Path) -> None:
    """US2: REAL ACP resume reuses identities and nate_OHA conversations.

    This test mirrors the quickstart-style create 
    shutdown 
    resume flow but configures the runtime to use :class:`NateOhaAcpClient` for
    ACP. It asserts that both Agent Mail identities and nate_OHA-backed
    conversation identifiers are unchanged across resume.
    """

    config, identities_before = _create_swarm_with_agents_real_acp(tmp_path, agent_count=2)

    # Act: resume the swarm from the same project metadata, using fresh
    # runtime-owned adapters derived from the stored configuration.
    daemon = RuntimeDaemon.resume(config)
    daemon.start()

    assert daemon.state.status is RuntimeStatus.RUNNING
    assert isinstance(daemon.acp_client, NateOhaAcpClient)
    assert isinstance(daemon.agent_mail_client, FakeAgentMailClient)

    swarm_after = daemon.swarm_state
    identities_after: Dict[str, Tuple[str, str]] = {}
    for agent_id, meta in swarm_after.agents.items():
        identities_after[agent_id] = _get_persisted_identity_and_conversation(meta)

    assert identities_after == identities_before



