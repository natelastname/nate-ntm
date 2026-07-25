from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from nate_ntm.cli import app
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import SwarmState


runner = CliRunner()


def test_runtime_start_forwards_non_lazy(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = MetadataStore(uuid4().hex)
    now = datetime(2026, 7, 25, 12, 0, 0)
    store.save_swarm_state(
        SwarmState(
            swarm_id=store.swarm_id,
            project_path=project,
            created_at=now,
            last_updated_at=now,
        )
    )
    called: dict[str, object] = {}

    monkeypatch.setattr(
        "nate_ntm.cli.run_runtime_with_control_api",
        lambda *_args, **kwargs: called.update(kwargs),
    )
    try:
        result = runner.invoke(
            app,
            ["runtime", "start", "--swarm-id", store.swarm_id, "--non-lazy"],
        )
    finally:
        shutil.rmtree(store.metadata_dir, ignore_errors=True)

    assert result.exit_code == 0, result.output
    assert called["non_lazy"] is True
