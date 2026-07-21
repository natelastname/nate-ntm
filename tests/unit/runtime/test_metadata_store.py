from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_oha.config import build_default_config


def _store(tmp_path: Path) -> MetadataStore:
    project = tmp_path / "project"
    project.mkdir()
    return MetadataStore(load_runtime_config(project_path=project))


def _state(store: MetadataStore) -> SwarmState:
    now = datetime(2026, 7, 3, 12, 0, 0)
    agent = AgentState(
        agent_id="agent-1",
        display_name="Agent One",
        conversation_id="conversation-1",
        nate_oha_config=build_default_config(),
    )
    return SwarmState(
        swarm_id=store.swarm_id,
        project_path=store.project_path,
        agent_mail_project_id="mail-project",
        created_at=now,
        last_updated_at=now,
        agents={agent.agent_id: agent},
    )


def test_swarm_state_round_trips_through_metadata_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    expected = _state(store)

    store.save_swarm_state(expected)

    assert store.load_swarm_state() == expected
    assert store.load_agent_state("agent-1") == expected.agents["agent-1"]
    assert not list(store.metadata_dir.glob("*.tmp"))


def test_invalid_swarm_metadata_fails_clearly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.metadata_dir.mkdir(parents=True)
    path = store.metadata_dir / "swarm.json"

    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_swarm_state()

    wrong = _state(store).model_copy(
        update={"project_path": tmp_path / "different-project"}
    )
    path.write_text(wrong.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="project_path"):
        store.load_swarm_state()
