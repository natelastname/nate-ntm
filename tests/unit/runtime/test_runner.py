from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import StartupMode
from nate_ntm.runtime.runner import create_runtime_control_context


def test_control_context_has_no_event_bridge(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)

    context = create_runtime_control_context(
        config,
        StartupMode.CREATE,
        host="127.0.0.1",
        port=0,
    )

    assert context.api_server.daemon is context.daemon
    assert not hasattr(context.app.state, "publish_event")
    assert context.daemon.scheduler is not None
    assert not hasattr(context.daemon.scheduler.agent_supervisor, "on_agent_event")
