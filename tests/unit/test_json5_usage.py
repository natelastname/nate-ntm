from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import json5
from nate_oha.config import build_default_config

from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


def test_persisted_swarm_accepts_json5_comments(tmp_path: Path) -> None:
    swarm_id = uuid4().hex
    store = MetadataStore(swarm_id)
    now = datetime.now(timezone.utc)
    state = SwarmState(
        swarm_id=swarm_id,
        project_path=tmp_path,
        created_at=now,
        last_updated_at=now,
        agents={
            "agent": AgentState(
                agent_id="agent",
                display_name="Agent",
                nate_oha_config=build_default_config(),
            )
        },
    )

    try:
        store.save_swarm_state(state)
        text = store.swarm_path.read_text(encoding="utf-8")
        store.swarm_path.write_text(
            "// persisted swarm metadata may contain comments\n" + text,
            encoding="utf-8",
        )
        assert store.load_swarm_state() == state
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)


def test_json5_round_trip_preserves_config_data() -> None:
    config = build_default_config()
    text = "// nate-oha config\n" + json5.dumps(config.model_dump(mode="json"), indent=2)
    assert type(config).model_validate(json5.loads(text)) == config
