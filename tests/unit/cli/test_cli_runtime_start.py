from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import StartupMode, check_startup_preconditions
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import SwarmState

runner = CliRunner()


def _project(tmp_path: Path, *, persisted: bool) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    if persisted:
        config = load_runtime_config(project_path=project, env={})
        now = datetime(2026, 7, 3, 12, 0, 0)
        MetadataStore(config).save_swarm_state(
            SwarmState(
                swarm_id=config.swarm_id,
                project_path=config.project_path,
                created_at=now,
                last_updated_at=now,
            )
        )
    return project


@pytest.mark.parametrize(
    ("mode", "persisted", "succeeds"),
    [
        ("resume", True, True),
        ("resume", False, False),
        ("create", False, True),
        ("create", True, False),
    ],
)
def test_runtime_start_enforces_create_resume_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    persisted: bool,
    succeeds: bool,
) -> None:
    project = _project(tmp_path, persisted=persisted)

    def run(config, startup_mode, **_kwargs):
        check_startup_preconditions(config, startup_mode)

    monkeypatch.setattr("nate_ntm.cli.run_runtime_with_control_api", run)
    result = runner.invoke(
        app,
        ["runtime", "start", "--project", str(project), "--mode", mode],
    )
    assert (result.exit_code == 0) is succeeds


@pytest.mark.parametrize("agents", ["0", "-1"])
def test_runtime_start_rejects_invalid_agent_count(
    tmp_path: Path,
    agents: str,
) -> None:
    project = _project(tmp_path, persisted=False)
    result = runner.invoke(
        app,
        [
            "runtime",
            "start",
            "--project",
            str(project),
            "--mode",
            "create",
            "--agents",
            agents,
        ],
    )
    assert result.exit_code != 0


def test_runtime_start_rejects_agents_when_resuming(tmp_path: Path) -> None:
    project = _project(tmp_path, persisted=True)
    result = runner.invoke(
        app,
        [
            "runtime",
            "start",
            "--project",
            str(project),
            "--mode",
            "resume",
            "--agents",
            "2",
        ],
    )
    assert result.exit_code != 0


def test_runtime_start_delegates_long_lived_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, persisted=False)
    called: dict[str, object] = {}

    def run(config, mode, **kwargs):
        called.update(config=config, mode=mode, **kwargs)

    monkeypatch.setattr("nate_ntm.cli.run_runtime_with_control_api", run)
    result = runner.invoke(
        app,
        [
            "runtime",
            "start",
            "--project",
            str(project),
            "--mode",
            "create",
            "--agents",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert called["mode"] is StartupMode.CREATE
    assert called["agent_count"] == 3
    assert called["acp_host"] == "127.0.0.1"
    assert called["acp_port"] == 8766


def test_runtime_start_forwards_nate_oha_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, persisted=False)
    base = project / "nate-oha.json"
    base.write_text("{}", encoding="utf-8")
    called: dict[str, object] = {}

    class Config:
        control_api_host = "127.0.0.1"
        control_api_port = 8765

    def load(**kwargs):
        called.update(kwargs)
        return Config()

    monkeypatch.setattr("nate_ntm.cli.load_runtime_config", load)
    monkeypatch.setattr(
        "nate_ntm.cli.run_runtime_with_control_api",
        lambda *_args, **_kwargs: None,
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
            "--nate-oha-config",
            str(base),
            "--nate-oha-runtime-mode",
            "echo",
            "--llm-model",
            "gpt-cli",
            "--prompt-soul-content",
            "Hello",
        ],
    )

    assert result.exit_code == 0
    assert called == {
        "project_path": project,
        "nate_oha_config_path": base.resolve(),
        "nate_oha_runtime_mode": "echo",
        "llm_model": "gpt-cli",
        "llm_api_key": None,
        "prompt_soul_content": "Hello",
    }
