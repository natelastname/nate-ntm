from __future__ import annotations

import ast
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from nate_oha.config import build_default_config

from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


def test_source_uses_json5_exclusively() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "nate_ntm"
    violations: list[str] = []

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "json" for alias in node.names):
                    violations.append(f"{path}: import json")
            elif isinstance(node, ast.ImportFrom) and node.module == "json":
                violations.append(f"{path}: from json import ...")
            elif isinstance(node, ast.Attribute) and node.attr in {
                "model_dump_json",
                "model_validate_json",
            }:
                violations.append(f"{path}: {node.attr}")

    assert not violations, "Strict-JSON path bypasses json5:\n" + "\n".join(violations)


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
