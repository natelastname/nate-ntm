"""Integration test for the `nate-ntm runtime start` quickstart flow (US1).

This test exercises the Typer-based CLI `runtime start` command end-to-end
in-process and verifies that, after startup, the runtime control API
(`runtime.get_status`) reports a `Running` status and correct aggregate
agent counts.

At this stage of the implementation we do **not** run a real long-lived
runtime loop or JSON-RPC server. Instead, we:

* Invoke the CLI via Typer's `CliRunner` to exercise argument parsing and
  wiring into `RuntimeDaemon`.
* Capture the constructed `RuntimeDaemon` instance and seed a minimal
  in-memory agent set to stand in for the eventual scheduler/agent
  lifecycle (T016/T017).
* Delegate to the `RuntimeApiServer` handlers to compute
  `runtime.get_status` results, mirroring how a future JSON-RPC layer
  will call into the daemon.

This provides a lightweight but realistic quickstart-style integration
that validates the CLI ↔ daemon ↔ control API path for User Story 1
without blocking on async server infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from typer.testing import CliRunner

from nate_ntm.api.server import RuntimeApiServer
from nate_ntm.cli import app as cli_app
from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime import daemon as daemon_mod
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeStatus


runner = CliRunner()


def _init_project(tmp_path: Path) -> Path:
    """Create a minimal project directory for the quickstart flow."""

    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_runtime_cli_us1_quickstart_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """US1 quickstart: CLI start followed by runtime.get_status via API.

    This test corresponds to T021 in ``tasks.md``: it runs
    ``nate-ntm runtime start --project <tmp_project>`` and then, using
    the in-process control API surface, verifies that ``runtime.get_status``
    reports ``Running`` with the expected aggregate agent counts.

    The agent set is currently synthetic; future tasks (T016/T017) will
    wire real agent lifecycle events into ``RuntimeState`` so that these
    counts reflect actual subprocess and scheduler behavior.
    """

    project = _init_project(tmp_path)

    # Resolve a RuntimeConfig for the project. The CLI does this internally
    # as well via _resolve_runtime_config, but we keep a copy here for
    # constructing expectations after the CLI invocation.
    config: RuntimeConfig = load_runtime_config(project_path=project)

    captured_daemons: List[RuntimeDaemon] = []

    # Patch RuntimeDaemon.create used by the CLI so we can:
    #
    # * Use the real implementation from nate_ntm.runtime.daemon.
    # * Capture the created daemon instance for inspection.
    # * Seed a minimal set of agents in the runtime state so that
    #   `agent_counts` has meaningful, non-zero values.
    real_create = daemon_mod.RuntimeDaemon.create

    def fake_create(fake_config: RuntimeConfig, *args, **kwargs) -> RuntimeDaemon:  # type: ignore[override]
        daemon = real_create(fake_config, *args, **kwargs)

        # Seed a small mixture of agent statuses to mirror
        # the ``agent_counts`` example in contracts/runtime-api.md.
        daemon.state.agents = {
            "agent-starting": AgentRuntimeState(
                agent_id="agent-starting", status=AgentStatus.STARTING
            ),
            "agent-idle": AgentRuntimeState(
                agent_id="agent-idle", status=AgentStatus.IDLE
            ),
            "agent-running": AgentRuntimeState(
                agent_id="agent-running", status=AgentStatus.RUNNING
            ),
            "agent-failed": AgentRuntimeState(
                agent_id="agent-failed", status=AgentStatus.FAILED
            ),
        }

        captured_daemons.append(daemon)
        return daemon

    monkeypatch.setattr(daemon_mod.RuntimeDaemon, "create", fake_create)

    # The current CLI implementation drives the daemon through a short
    # start → shutdown sequence. To keep the final status ``Running``
    # for this quickstart-style test, stub out the shutdown-related
    # methods invoked by the CLI so they become no-ops.
    def fake_request_shutdown(self: RuntimeDaemon) -> None:  # pragma: no cover - trivial
        return

    def fake_mark_stopped(self: RuntimeDaemon) -> None:  # pragma: no cover - trivial
        return

    monkeypatch.setattr(
        daemon_mod.RuntimeDaemon, "request_shutdown", fake_request_shutdown
    )
    monkeypatch.setattr(daemon_mod.RuntimeDaemon, "mark_stopped", fake_mark_stopped)

    # Invoke the CLI as a user would.
    result = runner.invoke(
        cli_app,
        [
            "runtime",
            "start",
            "--project",
            str(project),
            "--mode",
            "create",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured_daemons, "CLI did not construct a RuntimeDaemon instance"

    daemon = captured_daemons[0]

    # After the CLI call, the daemon should have transitioned to RUNNING
    # (via daemon.start()), and our patched shutdown hooks should not have
    # changed that status.
    assert daemon.state.status is RuntimeStatus.RUNNING

    # Use the in-process RuntimeApiServer as a stand-in for the unified
    # FastAPI-based JSON-RPC control API layer.
    server = RuntimeApiServer(daemon=daemon)
    payload = server.get_runtime_status()

    assert payload["status"] == RuntimeStatus.RUNNING.value
    assert payload["project_path"] == str(config.project_path)
    assert payload["swarm_id"] == config.swarm_id

    counts = payload["agent_counts"]
    assert counts == {
        "total": 4,
        "starting": 1,
        "idle": 1,
        "running": 1,
        "waiting": 0,
        "failed": 1,
    }
