"""Unit tests for the RuntimeDaemon entrypoint and startup semantics.

Covers Phase 2 tasks T008 and T037 at the Python API level:

* Explicit `create` vs `resume` precondition checks.
* Construction of `RuntimeDaemon` in `resume` mode from existing
  metadata.
* Basic lifecycle transitions for `start`, `request_shutdown`, and
  `mark_stopped`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.daemon import (
    MetadataAlreadyExistsError,
    MetadataMissingError,
    RuntimeDaemon,
    RuntimeStartupError,
    StartupMode,
    check_startup_preconditions,
)
from nate_ntm.runtime.metadata_store import AgentMetadata, MetadataStore, SwarmMetadata
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeStatus


def _make_config(project_root: Path) -> RuntimeConfig:
    project_root.mkdir(parents=True, exist_ok=True)
    return load_runtime_config(project_path=project_root)


def _write_minimal_swarm_metadata(config: RuntimeConfig) -> None:
    store = MetadataStore(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
    )
    store.save_swarm_metadata(swarm)


def test_check_startup_preconditions_create_fails_if_metadata_exists(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)

    _write_minimal_swarm_metadata(config)

    with pytest.raises(MetadataAlreadyExistsError) as excinfo:
        check_startup_preconditions(config, StartupMode.CREATE)

    msg = str(excinfo.value)
    assert "Swarm metadata already exists" in msg


def test_check_startup_preconditions_resume_fails_if_metadata_missing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)

    with pytest.raises(MetadataMissingError) as excinfo:
        check_startup_preconditions(config, StartupMode.RESUME)

    msg = str(excinfo.value)
    assert "Swarm metadata not found" in msg


def test_runtime_daemon_resume_constructs_state_from_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)

    daemon = RuntimeDaemon.resume(config)

    assert daemon.config is config
    assert daemon.metadata_store.metadata_dir == config.metadata_dir
    assert daemon.swarm_metadata.swarm_id == config.swarm_id
    assert daemon.swarm_metadata.project_path == config.project_path

    assert daemon.state.config is config
    assert daemon.state.status is RuntimeStatus.STARTING
    assert daemon.startup_mode is StartupMode.RESUME
    assert daemon.started_at is None



def test_runtime_daemon_create_initializes_and_persists_swarm_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)

    store = MetadataStore(config=config)
    swarm_path = store.metadata_dir / "swarm.json"
    assert not swarm_path.exists()

    daemon = RuntimeDaemon.create(config)

    assert daemon.config is config
    assert daemon.metadata_store.metadata_dir == config.metadata_dir
    assert daemon.swarm_metadata.swarm_id == config.swarm_id
    assert daemon.swarm_metadata.project_path == config.project_path
    # Agent Mail project ID is intentionally left empty until T014 wires it.
    assert daemon.swarm_metadata.agent_mail_project_id == ""

    assert daemon.state.config is config
    assert daemon.state.status is RuntimeStatus.STARTING
    assert daemon.startup_mode is StartupMode.CREATE
    assert daemon.started_at is None

    # Metadata should have been persisted and be readable via MetadataStore.
    assert swarm_path.is_file()
    loaded = store.load_swarm_metadata()
    assert loaded == daemon.swarm_metadata



def test_runtime_daemon_create_raises_if_metadata_already_exists(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)

    with pytest.raises(MetadataAlreadyExistsError):
        _ = RuntimeDaemon.create(config)


def test_runtime_daemon_start_and_shutdown_transitions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)
    daemon = RuntimeDaemon.resume(config)

    # Initially in STARTING state
    assert daemon.state.status is RuntimeStatus.STARTING
    assert daemon.state.shutdown_requested is False

    # After start(), runtime should be RUNNING and started_at set.
    daemon.start()
    assert daemon.state.status is RuntimeStatus.RUNNING
    assert isinstance(daemon.started_at, datetime)

    # Idempotent start() when already running should not fail.
    daemon.start()
    assert daemon.state.status is RuntimeStatus.RUNNING

    # Request shutdown moves to SHUTTING_DOWN from RUNNING.
    daemon.request_shutdown()
    assert daemon.state.shutdown_requested is True
    assert daemon.state.status is RuntimeStatus.SHUTTING_DOWN

    # Mark fully stopped.
    daemon.mark_stopped()
    assert daemon.state.status is RuntimeStatus.STOPPED


def test_runtime_daemon_start_rejects_invalid_transition(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)
    daemon = RuntimeDaemon.resume(config)

    # Move the state to STOPPED manually to simulate prior lifecycle.
    daemon.state.status = RuntimeStatus.STOPPED

    with pytest.raises(RuntimeStartupError):
        daemon.start()


def test_runtime_daemon_get_runtime_status_aggregates_agent_counts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)

    daemon = RuntimeDaemon.resume(config)

    # Seed runtime state with a mix of agent statuses.
    daemon.state.agents = {
        "a-start": AgentRuntimeState(agent_id="a-start", status=AgentStatus.STARTING),
        "a-idle": AgentRuntimeState(agent_id="a-idle", status=AgentStatus.IDLE),
        "a-run": AgentRuntimeState(agent_id="a-run", status=AgentStatus.RUNNING),
        "a-fail": AgentRuntimeState(agent_id="a-fail", status=AgentStatus.FAILED),
    }
    daemon.state.status = RuntimeStatus.RUNNING

    payload = daemon.get_runtime_status()

    assert payload["status"] == RuntimeStatus.RUNNING.value
    assert payload["project_path"] == str(config.project_path)
    assert payload["swarm_id"] == config.swarm_id

    counts = payload["agent_counts"]
    assert counts == {
        "total": 4,
        "starting": 1,
        "idle": 1,
        "running": 1,
        "waiting": 0,
        "failed": 1,
    }



def test_runtime_daemon_get_swarm_overview_joins_metadata_and_runtime_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    config = _make_config(project)
    _write_minimal_swarm_metadata(config)

    daemon = RuntimeDaemon.resume(config)

    # Attach agent metadata for two agents.
    base_swarm = daemon.swarm_metadata
    a1_meta = AgentMetadata(agent_id="a1", display_name="Agent One")
    a2_meta = AgentMetadata(agent_id="a2", display_name="Agent Two")
    daemon.swarm_metadata = SwarmMetadata(
        swarm_id=base_swarm.swarm_id,
        project_path=base_swarm.project_path,
        agent_mail_project_id=base_swarm.agent_mail_project_id,
        created_at=base_swarm.created_at,
        last_updated_at=base_swarm.last_updated_at,
        config_version=base_swarm.config_version,
        agents={"a1": a1_meta, "a2": a2_meta},
        runtime_options=base_swarm.runtime_options,
    )

    # Runtime state includes two configured agents plus one extra.
    daemon.state.agents = {
        "a1": AgentRuntimeState(agent_id="a1", status=AgentStatus.RUNNING),
        "a2": AgentRuntimeState(
            agent_id="a2", status=AgentStatus.FAILED, last_error="boom"
        ),
        "orphan": AgentRuntimeState(agent_id="orphan", status=AgentStatus.IDLE),
    }
    daemon.state.status = RuntimeStatus.RUNNING

    overview = daemon.get_swarm_overview()

    assert overview["swarm_id"] == config.swarm_id
    assert overview["project_path"] == str(config.project_path)
    assert overview["runtime_status"] == RuntimeStatus.RUNNING.value

    counts = overview["agent_counts"]
    assert counts["total"] == 3
    assert counts["running"] == 1
    assert counts["idle"] == 1
    assert counts["failed"] == 1

    agents_by_id = {a["agent_id"]: a for a in overview["agents"]}

    a1 = agents_by_id["a1"]
    assert a1["display_name"] == "Agent One"
    assert a1["status"] == AgentStatus.RUNNING.value
    assert a1["has_unread_mail"] is False
    assert a1["last_error"] is None

    a2 = agents_by_id["a2"]
    assert a2["display_name"] == "Agent Two"
    assert a2["status"] == AgentStatus.FAILED.value
    assert a2["has_unread_mail"] is False
    assert a2["last_error"] == "boom"

    orphan = agents_by_id["orphan"]
    # No metadata, so the display name should fall back to agent_id.
    assert orphan["display_name"] == "orphan"
    assert orphan["status"] == AgentStatus.IDLE.value
    assert orphan["has_unread_mail"] is False
    assert orphan["last_error"] is None

