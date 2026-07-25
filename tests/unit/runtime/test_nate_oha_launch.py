from __future__ import annotations

import json
import shutil
from pathlib import Path

from nate_oha.config import AgentMailFeatureConfig, build_default_config

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.nate_oha_launch import (
    build_nate_oha_launch_spec,
    materialize_nate_oha_config,
)
from nate_ntm.runtime.swarm_state import AgentState


def _persisted_agent() -> AgentState:
    config = build_default_config()
    config.features.agent_mail = AgentMailFeatureConfig(
        enabled=True,
        project="mail-project",
        agent_identity="agent-one",
        credentials_ref="registration-token",
        upstream_url="https://mail.invalid",
    )
    return AgentState(
        agent_id="agent-1",
        display_name="Agent One",
        conversation_id="conversation-1",
        nate_oha_config=config,
    )


def test_launch_spec_materializes_complete_persisted_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    metadata = _persisted_agent()
    config = load_runtime_config(
        project_path=project,
        swarm_id="swarm-1",
        nate_oha_runtime_mode="echo",
        llm_model="gpt-cli",
        prompt_soul_content="ship it",
        env={},
    )

    spec = build_nate_oha_launch_spec(config=config, metadata=metadata)
    try:
        argv = list(spec.to_argv())
        assert argv[:4] == ["nate-oha", "acp", "--config", str(spec.base_config)]
        assert argv[4:6] == ["--resume", "conversation-1"]
        assert "runtime.mode=echo" in argv
        assert "llm.model=gpt-cli" in argv

        materialized = json.loads(spec.base_config.read_text())
        agent_mail = materialized["features"]["agent_mail"]
        assert agent_mail["project"] == "mail-project"
        assert agent_mail["agent_identity"] == "agent-one"
        assert agent_mail["credentials_ref"] == "registration-token"
        assert "conversation-1" not in json.dumps(materialized)
    finally:
        shutil.rmtree(spec.base_config.parent)


def test_acp_client_uses_canonical_launch_spec(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = load_runtime_config(
        project_path=project,
        swarm_id="swarm-1",
        nate_oha_runtime_mode="echo",
        env={},
    )
    client = NateOhaAcpClient(config)

    command = client._build_command("agent-1", _persisted_agent())
    try:
        assert command[-2:] == ["--set", "runtime.mode=echo"]
    finally:
        client._cleanup_temp_config("agent-1")


def test_materialize_nate_oha_config_round_trips_default_config() -> None:
    expected = build_default_config()
    path = materialize_nate_oha_config(config=expected)
    try:
        assert json.loads(path.read_text()) == expected.model_dump(mode="json")
    finally:
        shutil.rmtree(path.parent)
