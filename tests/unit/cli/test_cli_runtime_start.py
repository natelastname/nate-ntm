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



def test_runtime_start_with_control_api_delegates_to_runner(monkeypatch, tmp_path: Path) -> None:
    """When --with-control-api is set, CLI uses the runtime runner.

    This ensures that the Typer command delegates to
    :func:`run_runtime_with_control_api` with the correct startup mode
    instead of directly constructing a :class:`RuntimeDaemon` and
    performing the short start → shutdown cycle.
    """

    project = _init_project_without_metadata(tmp_path)

    called: dict[str, object] = {}

    def fake_run_runtime_with_control_api(config, mode, *args, **kwargs):  # type: ignore[override]
        called["config"] = config
        called["mode"] = mode

    # Patch the runner entrypoint used by the CLI.
    monkeypatch.setattr(
        "nate_ntm.cli.run_runtime_with_control_api",
        fake_run_runtime_with_control_api,
    )

    result = runner.invoke(
        app,
        [
            "runtime",
            "start",
            "--project",
            str(project),
            "--mode",
            "create",
            "--with-control-api",
        ],
    )

    assert result.exit_code == 0
    assert "config" in called and "mode" in called
    # The CLI should have mapped the string mode onto StartupMode.CREATE.
    from nate_ntm.runtime.daemon import StartupMode

    assert called["mode"] is StartupMode.CREATE

def test_runtime_start_default_mode_resume_is_applied(tmp_path: Path) -> None:
    project = _init_project_with_metadata(tmp_path)

    # No --mode flag: should behave like --mode resume and succeed.
    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project)],
    )

    assert result.exit_code == 0
