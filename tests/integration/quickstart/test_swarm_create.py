from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

import json5
import pytest
from nate_oha.config import build_default_config
from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.runtime.metadata_store import MetadataStore

runner = CliRunner()


def _write_config(path: Path) -> None:
    path.write_text(
        json5.dumps(build_default_config().model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _agent(agent_id: str, path: Path) -> str:
    return f"{agent_id}:{path}"


def _created_id(output: str) -> str:
    match = re.search(r"Swarm ID: ([0-9a-f]{32})", output)
    assert match is not None, output
    return match.group(1)


def test_create_defaults_to_working_directory_and_generated_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "shared.json"
    _write_config(config)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "swarm",
            "create",
            "--agent",
            _agent("planner", config),
            "--agent",
            _agent("implementer", config),
        ],
    )
    assert result.exit_code == 0, result.output
    swarm_id = _created_id(result.output)
    store = MetadataStore(swarm_id)
    try:
        state = store.load_swarm_state()
        assert state.swarm_id == swarm_id
        assert state.project_path == project.resolve()
        assert set(state.agents) == {"planner", "implementer"}
        assert not (project / ".nate_ntm").exists()
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)


def test_create_accepts_commented_json5_agent_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = tmp_path / "shared.json"
    config = json5.dumps(
        build_default_config().model_dump(mode="json"),
        indent=2,
        trailing_commas=True,
    )
    config_path.write_text("// human-maintained nate-oha config\n" + config, encoding="utf-8")
    swarm_id = uuid4().hex
    store = MetadataStore(swarm_id)

    try:
        result = runner.invoke(
            app,
            [
                "swarm",
                "create",
                "--project",
                str(project),
                "--swarm-id",
                swarm_id,
                "--agent",
                _agent("commented", config_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert set(store.load_swarm_state().agents) == {"commented"}
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)


def test_two_swarms_for_one_project_are_independent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "agent.json"
    _write_config(config)
    stores: list[MetadataStore] = []
    try:
        for _ in range(2):
            result = runner.invoke(
                app,
                [
                    "swarm",
                    "create",
                    "--project",
                    str(project),
                    "--agent",
                    _agent("agent", config),
                ],
            )
            assert result.exit_code == 0, result.output
            stores.append(MetadataStore(_created_id(result.output)))
        assert stores[0].swarm_id != stores[1].swarm_id
        assert stores[0].swarm_path != stores[1].swarm_path
        assert stores[0].load_swarm_state().project_path == project.resolve()
        assert stores[1].load_swarm_state().project_path == project.resolve()
    finally:
        for store in stores:
            shutil.rmtree(store.metadata_dir, ignore_errors=True)


def test_create_rejects_invalid_inputs_without_writing_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    valid = tmp_path / "agent.json"
    invalid = tmp_path / "invalid.json"
    _write_config(valid)
    invalid.write_text("not json", encoding="utf-8")

    duplicate_result = runner.invoke(
        app,
        [
            "swarm",
            "create",
            "--project",
            str(project),
            "--agent",
            _agent("agent", valid),
            "--agent",
            _agent("agent", valid),
        ],
    )
    assert duplicate_result.exit_code != 0
    assert "duplicate agent id" in duplicate_result.output

    for invalid_spec in (
        str(valid),
        f":{valid}",
        "agent:",
        f"agent:{tmp_path / 'missing.json'}",
    ):
        result = runner.invoke(
            app,
            ["swarm", "create", "--project", str(project), "--agent", invalid_spec],
        )
        assert result.exit_code != 0

    invalid_result = runner.invoke(
        app,
        [
            "swarm",
            "create",
            "--project",
            str(project),
            "--agent",
            _agent("agent", invalid),
        ],
    )
    assert invalid_result.exit_code != 0
    assert "invalid agent config" in invalid_result.output

    for option, value in (
        ("--agent-mail-project-id", "mail-project"),
        ("--agent-mail-url", "http://127.0.0.1:8765"),
    ):
        swarm_id = uuid4().hex
        unused_option = runner.invoke(
            app,
            [
                "swarm",
                "create",
                "--project",
                str(project),
                "--swarm-id",
                swarm_id,
                "--agent",
                _agent("agent", valid),
                option,
                value,
            ],
        )
        assert unused_option.exit_code != 0
        assert "require --constructor agent-mail" in unused_option.output
        assert not MetadataStore(swarm_id).metadata_dir.exists()
