"""Unit tests for the Typer-based CLI runtime start command (T009, T010).

These tests exercise the `nate_ntm.cli.runtime_start` command in a
side-effect-light way using Typer's `CliRunner`. The goal is to validate
argument parsing and the wiring to `RuntimeDaemon` startup semantics
without running a real long-lived daemon.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.metadata_store import MetadataStore, SwarmMetadata


runner = CliRunner()


def _init_project_with_metadata(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    config = load_runtime_config(project_path=project)
    store = MetadataStore(config=config)

    from datetime import datetime

    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
    )
    store.save_swarm_metadata(swarm)

    return project


def _init_project_without_metadata(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    # Do not create any metadata; this represents a fresh project.
    return project


def test_runtime_start_resume_with_existing_metadata_succeeds(tmp_path: Path) -> None:
    project = _init_project_with_metadata(tmp_path)

    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project), "--mode", "resume"],
    )

    assert result.exit_code == 0


def test_runtime_start_resume_without_metadata_fails(tmp_path: Path) -> None:
    project = _init_project_without_metadata(tmp_path)

    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project), "--mode", "resume"],
    )

    assert result.exit_code != 0


def test_runtime_start_create_with_existing_metadata_fails(tmp_path: Path) -> None:
    project = _init_project_with_metadata(tmp_path)

    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project), "--mode", "create"],
    )

    assert result.exit_code != 0




def test_runtime_start_create_without_metadata_succeeds_and_writes_swarm(tmp_path: Path) -> None:
    project = _init_project_without_metadata(tmp_path)

    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project), "--mode", "create"],
    )

    assert result.exit_code == 0

    # Swarm metadata should now exist and be loadable.
    config = load_runtime_config(project_path=project)
    store = MetadataStore(config=config)
    swarm_path = store.metadata_dir / "swarm.json"
    assert swarm_path.is_file()
    swarm = store.load_swarm_metadata()
    assert swarm.project_path == config.project_path
    assert swarm.swarm_id == config.swarm_id

def test_runtime_start_default_mode_resume_is_applied(tmp_path: Path) -> None:
    project = _init_project_with_metadata(tmp_path)

    # No --mode flag: should behave like --mode resume and succeed.
    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project)],
    )

    assert result.exit_code == 0
