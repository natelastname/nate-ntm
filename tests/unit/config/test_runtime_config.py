from __future__ import annotations

from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config


def test_defaults_are_runtime_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = load_runtime_config(project_path=project, swarm_id="swarm-1", env={})

    assert isinstance(config, RuntimeConfig)
    assert config.project_path == project.resolve()
    assert config.swarm_id == "swarm-1"
    assert config.control_api_host == "127.0.0.1"
    assert config.control_api_port == 8765
    assert config.nate_oha_executable == "nate-oha"
    assert config.nate_oha_config_path is None
    assert not hasattr(config, "metadata_dir")
    assert not hasattr(config, "agent_mail_project")
    assert not hasattr(config, "agent_mail_enabled")


def test_explicit_runtime_values_override_environment(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = load_runtime_config(
        project_path=project,
        swarm_id="persisted-swarm",
        control_api_port=9998,
        env={
            "NATE_NTM_CONTROL_PORT": "9999",
            "NATE_NTM_SWARM_ID": "ignored",
            "NATE_NTM_AGENT_MAIL_PROJECT": "ignored",
        },
    )

    assert config.control_api_port == 9998
    assert config.swarm_id == "persisted-swarm"


def test_environment_supplies_only_runtime_overrides(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = load_runtime_config(
        project_path=project,
        swarm_id="persisted-swarm",
        env={
            "NATE_NTM_CONTROL_HOST": "127.0.0.2",
            "NATE_NTM_CONTROL_PORT": "9999",
            "NATE_NTM_NATE_OHA_CONFIG": "config/base.json",
            "NATE_NTM_NATE_OHA_RUNTIME_MODE": "echo",
            "NATE_NTM_LLM_MODEL": "gpt-test",
        },
    )

    assert config.control_api_host == "127.0.0.2"
    assert config.control_api_port == 9999
    assert config.nate_oha_config_path == (project / "config/base.json").resolve()
    assert config.nate_oha_runtime_mode == "echo"
    assert config.llm_model == "gpt-test"


@pytest.mark.parametrize("port", ["not-an-int", 0, 1024, 70000])
def test_invalid_port_raises(tmp_path: Path, port: object) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        load_runtime_config(
            project_path=project,
            swarm_id="swarm-1",
            control_api_port=port,  # type: ignore[arg-type]
            env={},
        )


def test_invalid_materialized_identity_raises(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        load_runtime_config(project_path=tmp_path / "missing", swarm_id="swarm-1", env={})
    with pytest.raises(ValueError):
        load_runtime_config(project_path=project, swarm_id=" ", env={})


def test_dotenv_cannot_replace_persisted_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / ".env").write_text(
        "NATE_NTM_PROJECT_DIR=/wrong\nNATE_NTM_SWARM_ID=wrong\nNATE_NTM_CONTROL_PORT=9999\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_runtime_config(project_path=project, swarm_id="persisted")
    assert config.project_path == project.resolve()
    assert config.swarm_id == "persisted"
    assert config.control_api_port == 9999
