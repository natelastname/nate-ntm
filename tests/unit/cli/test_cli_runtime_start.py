from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import SwarmState

runner = CliRunner()


def _persist(project: Path) -> MetadataStore:
    store = MetadataStore(uuid4().hex)
    now = datetime(2026, 7, 3, 12, 0, 0)
    store.save_swarm_state(
        SwarmState(
            swarm_id=store.swarm_id,
            project_path=project,
            created_at=now,
            last_updated_at=now,
        )
    )
    return store


def test_runtime_start_loads_swarm_by_id_and_recovers_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = _persist(project)
    called: dict[str, object] = {}

    def run(config, swarm, **kwargs):
        called.update(config=config, swarm=swarm, **kwargs)

    monkeypatch.setattr("nate_ntm.cli.run_runtime_with_control_api", run)
    try:
        result = runner.invoke(app, ["runtime", "start", "--swarm-id", store.swarm_id])
        assert result.exit_code == 0, result.output
        assert called["swarm"].swarm_id == store.swarm_id
        assert called["config"].swarm_id == store.swarm_id
        assert called["config"].project_path == project.resolve()
        assert called["acp_host"] == "127.0.0.1"
        assert called["acp_port"] == 8766
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)


def test_runtime_start_rejects_missing_swarm() -> None:
    result = runner.invoke(app, ["runtime", "start", "--swarm-id", uuid4().hex])
    assert result.exit_code != 0
    assert "swarm not found" in result.output


@pytest.mark.parametrize(
    "obsolete",
    ["--project", "--mode", "--agents", "--nate-oha-config"],
)
def test_runtime_start_rejects_removed_options(obsolete: str) -> None:
    result = runner.invoke(
        app,
        ["runtime", "start", "--swarm-id", uuid4().hex, obsolete, "value"],
    )
    assert result.exit_code != 0


def test_runtime_start_forwards_runtime_only_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = _persist(project)
    called: dict[str, object] = {}

    def load(**kwargs):
        called.update(kwargs)

        class Config:
            control_api_host = "127.0.0.1"
            control_api_port = 8765

        return Config()

    monkeypatch.setattr("nate_ntm.cli.load_runtime_config", load)
    monkeypatch.setattr(
        "nate_ntm.cli.run_runtime_with_control_api",
        lambda *_args, **_kwargs: None,
    )
    try:
        result = runner.invoke(
            app,
            [
                "runtime",
                "start",
                "--swarm-id",
                store.swarm_id,
                "--nate-oha-runtime-mode",
                "echo",
                "--llm-model",
                "gpt-cli",
                "--prompt-soul-content",
                "Hello",
            ],
        )
        assert result.exit_code == 0, result.output
        assert called == {
            "project_path": project.resolve(),
            "swarm_id": store.swarm_id,
            "nate_oha_runtime_mode": "echo",
            "llm_model": "gpt-cli",
            "llm_api_key": None,
            "prompt_soul_content": "Hello",
        }
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)
