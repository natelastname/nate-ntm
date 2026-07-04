"""Unit tests for the RuntimeApiServer skeleton (T011).

These tests are intentionally minimal and focus on the association
between the server and a `RuntimeDaemon` instance; networking is not yet
implemented.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import AgentMetadata, MetadataStore, SwarmMetadata
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState, RuntimeStatus
from nate_ntm.api.server import RuntimeApiServer


def _make_daemon(tmp_path: Path) -> RuntimeDaemon:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)

    # Construct a minimal in-memory daemon without pre-existing metadata.
    # This is sufficient for testing the `RuntimeApiServer` association.
    store = MetadataStore(config=config)
    state = RuntimeState(config=config)
    from datetime import datetime
    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
    )

    return RuntimeDaemon(
        config=config,
        metadata_store=store,
        swarm_metadata=swarm,
        state=state,
        startup_mode=None,  # type: ignore[arg-type]
    )


def test_runtime_api_server_get_runtime_status_delegates_to_daemon(tmp_path: Path) -> None:
    daemon = _make_daemon(tmp_path)

    # Seed minimal runtime state.
    daemon.state.agents = {
        "a1": AgentRuntimeState(agent_id="a1", status=AgentStatus.RUNNING),
        "a2": AgentRuntimeState(agent_id="a2", status=AgentStatus.IDLE),
    }
    daemon.state.status = RuntimeStatus.RUNNING

    server = RuntimeApiServer(daemon=daemon)

    payload = server.get_runtime_status()

    assert payload["status"] == RuntimeStatus.RUNNING.value
    assert payload["project_path"] == str(daemon.config.project_path)
    assert payload["swarm_id"] == daemon.swarm_metadata.swarm_id

    counts = payload["agent_counts"]
    assert counts["total"] == 2
    assert counts["running"] == 1
    assert counts["idle"] == 1



def test_runtime_api_server_get_swarm_overview_delegates_to_daemon(tmp_path: Path) -> None:
    daemon = _make_daemon(tmp_path)

    # Attach metadata and runtime state for a single agent.
    base_swarm = daemon.swarm_metadata
    agent_meta = AgentMetadata(agent_id="agent-1", display_name="Agent One")
    daemon.swarm_metadata = SwarmMetadata(
        swarm_id=base_swarm.swarm_id,
        project_path=base_swarm.project_path,
        agent_mail_project_id=base_swarm.agent_mail_project_id,
        created_at=base_swarm.created_at,
        last_updated_at=base_swarm.last_updated_at,
        config_version=base_swarm.config_version,
        agents={"agent-1": agent_meta},
        runtime_options=base_swarm.runtime_options,
    )

    daemon.state.agents = {
        "agent-1": AgentRuntimeState(agent_id="agent-1", status=AgentStatus.RUNNING)
    }
    daemon.state.status = RuntimeStatus.RUNNING

    server = RuntimeApiServer(daemon=daemon)

    overview = server.get_swarm_overview()

    assert overview["swarm_id"] == daemon.swarm_metadata.swarm_id
    assert overview["runtime_status"] == RuntimeStatus.RUNNING.value
    assert overview["agent_counts"]["total"] == 1

    agents = overview["agents"]
    assert len(agents) == 1
    agent = agents[0]
    assert agent["agent_id"] == "agent-1"
    assert agent["display_name"] == "Agent One"
    assert agent["status"] == AgentStatus.RUNNING.value


def test_runtime_api_server_binds_daemon(tmp_path: Path) -> None:
    daemon = _make_daemon(tmp_path)
    server = RuntimeApiServer(daemon=daemon)

    assert server.daemon is daemon

    # Stubbed start/stop should be callable without side effects.
    server.start()
    server.stop()
