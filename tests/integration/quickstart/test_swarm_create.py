from __future__ import annotations

from pathlib import Path

from nate_oha.config import build_default_config
from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.metadata_store import MetadataStore


runner = CliRunner()


def _write_config(path: Path) -> None:
    path.write_text(build_default_config().model_dump_json(), encoding="utf-8")


def test_swarm_create_persists_complete_agent_configs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    navigator = tmp_path / "navigator.json"
    reviewer = tmp_path / "code-reviewer.json"
    _write_config(navigator)
    _write_config(reviewer)

    result = runner.invoke(
        app,
        [
            "swarm",
            "create",
            "--project",
            str(project),
            "--agent",
            str(navigator),
            "--agent",
            str(reviewer),
        ],
    )

    assert result.exit_code == 0, result.output
    state = MetadataStore(load_runtime_config(project_path=project, env={})).load_swarm_state()
    assert set(state.agents) == {"navigator", "code-reviewer"}
    assert state.agents["navigator"].display_name == "Navigator"
    assert state.agents["code-reviewer"].display_name == "Code Reviewer"
    assert state.agents["navigator"].nate_oha_config == build_default_config()


def test_swarm_create_rejects_invalid_duplicate_and_existing_input(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    valid = tmp_path / "agent.json"
    duplicate = tmp_path / "other" / "agent.json"
    duplicate.parent.mkdir()
    invalid = tmp_path / "invalid.json"
    _write_config(valid)
    _write_config(duplicate)
    invalid.write_text("not json", encoding="utf-8")

    duplicate_result = runner.invoke(
        app,
        ["swarm", "create", "--project", str(project), "--agent", str(valid), "--agent", str(duplicate)],
    )
    assert duplicate_result.exit_code != 0
    assert "duplicate agent id" in duplicate_result.output

    invalid_result = runner.invoke(
        app,
        ["swarm", "create", "--project", str(project), "--agent", str(invalid)],
    )
    assert invalid_result.exit_code != 0
    assert "invalid agent config" in invalid_result.output

    assert runner.invoke(
        app,
        ["swarm", "create", "--project", str(project), "--agent", str(valid)],
    ).exit_code == 0
    existing_result = runner.invoke(
        app,
        ["swarm", "create", "--project", str(project), "--agent", str(valid)],
    )
    assert existing_result.exit_code != 0
    assert "already exists" in existing_result.output
