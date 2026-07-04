"""Unit tests for the RuntimeApiServer skeleton (T011).

These tests are intentionally minimal and focus on the association
between the server and a `RuntimeDaemon` instance; networking is not yet
implemented.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.metadata_store import MetadataStore, SwarmMetadata
from nate_ntm.runtime.state import RuntimeState
from nate_ntm.api.server import RuntimeApiServer


def _make_daemon(tmp_path: Path) -> RuntimeDaemon:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)

    # Construct a minimal in-memory daemon without pre-existing metadata.
    # This is sufficient for testing the `RuntimeApiServer` association.
    store = MetadataStore(config=config)
    state = RuntimeState(config=config)
    from datetime import datetime
    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
    )

    return RuntimeDaemon(
        config=config,
        metadata_store=store,
        swarm_metadata=swarm,
        state=state,
        startup_mode=None,  # type: ignore[arg-type]
    )


def test_runtime_api_server_binds_daemon(tmp_path: Path) -> None:
    daemon = _make_daemon(tmp_path)
    server = RuntimeApiServer(daemon=daemon)

    assert server.daemon is daemon

    # Stubbed start/stop should be callable without side effects.
    server.start()
    server.stop()
