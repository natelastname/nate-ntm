from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from nate_oha.config import build_default_config

from nate_ntm.runtime.metadata_store import MetadataStore, validate_swarm_id
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


@pytest.fixture
def store() -> MetadataStore:
    owned = MetadataStore(uuid4().hex)
    try:
        yield owned
    finally:
        shutil.rmtree(owned.metadata_dir, ignore_errors=True)


def _state(store: MetadataStore, project: Path) -> SwarmState:
    now = datetime(2026, 7, 3, 12, 0, 0)
    agent = AgentState(
        agent_id="agent-1",
        display_name="Agent One",
        conversation_id="conversation-1",
        nate_oha_config=build_default_config(),
    )
    return SwarmState(
        swarm_id=store.swarm_id,
        project_path=project,
        created_at=now,
        last_updated_at=now,
        agents={agent.agent_id: agent},
    )


def test_swarm_state_round_trips_through_canonical_store(
    store: MetadataStore, tmp_path: Path
) -> None:
    expected = _state(store, tmp_path)

    store.save_swarm_state(expected)

    assert store.swarm_path == (
        Path.home() / ".nate-ntm" / "swarms" / store.swarm_id / "swarm.json"
    )
    assert store.load_swarm_state() == expected
    assert store.load_agent_state("agent-1") == expected.agents["agent-1"]
    assert not list(store.metadata_dir.glob("*.tmp"))


def test_store_rejects_malformed_or_mismatched_state(
    store: MetadataStore, tmp_path: Path
) -> None:
    store.metadata_dir.mkdir(parents=True)
    store.swarm_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_swarm_state()

    wrong = _state(store, tmp_path).model_copy(update={"swarm_id": uuid4().hex})
    store.swarm_path.write_text(wrong.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match expected"):
        store.load_swarm_state()


@pytest.mark.parametrize("value", ["", " ", ".", "..", "a/b", "a\\b"])
def test_invalid_swarm_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_swarm_id(value)
