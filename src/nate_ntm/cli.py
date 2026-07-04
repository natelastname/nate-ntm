"""CLI entrypoint for the nate_ntm runtime and API.

For this feature branch we migrate to a Typer-based CLI as described in
`specs/001-swarm-runtime-orchestrator/tasks.md` (T009 and T010).

The CLI currently exposes a small `runtime` command group with a
`start` subcommand that wires through to the `RuntimeDaemon` startup
semantics without yet starting a real event loop or API server. This is
sufficient for early, API-first validation and can be extended in later
phases.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from .config.runtime_config import RuntimeConfig, load_runtime_config
from .runtime.daemon import (
    MetadataAlreadyExistsError,
    MetadataMissingError,
    RuntimeDaemon,
    StartupMode,
    check_startup_preconditions,
)

app = typer.Typer(help="nate_ntm command-line interface")
runtime_app = typer.Typer(help="Runtime daemon commands")
app.add_typer(runtime_app, name="runtime")


class CliStartupMode(str, Enum):
    CREATE = "create"
    RESUME = "resume"


def _resolve_runtime_config(project: Path) -> RuntimeConfig:
    """Resolve a RuntimeConfig from CLI options.

    For now we require an explicit `--project` path to keep behavior
    simple and predictable.
    """

    return load_runtime_config(project_path=project)


@runtime_app.command("start")
def runtime_start(
    project: Path = typer.Option(
        ..., "--project", "-p", exists=True, file_okay=False, dir_okay=True,
        help="Project directory containing or adjacent to .nate_ntm/",
    ),
    mode: CliStartupMode = typer.Option(
        CliStartupMode.RESUME,
        "--mode",
        help="Startup mode: create a new swarm or resume an existing one.",
    ),
) -> None:
    """Start the nate_ntm runtime daemon for a given project.

    In ``create`` mode this will create fresh swarm metadata under the
    project's metadata directory. In ``resume`` mode it will load
    existing metadata. In both cases we only exercise high-level daemon
    lifecycle transitions; the long-lived event loop and API server
    wiring are added in later tasks.
    """

    config = _resolve_runtime_config(project)

    try:
        if mode is CliStartupMode.CREATE:
            daemon = RuntimeDaemon.create(config)
        else:
            daemon = RuntimeDaemon.resume(config)
    except (MetadataAlreadyExistsError, MetadataMissingError) as exc:
        # Surface startup precondition failures as a non-zero exit code
        # without printing a full stack trace.
        raise typer.Exit(code=1) from exc

    # For now we do not run a long-lived loop; simply exercise the state
    # transitions to ensure wiring is correct.
    daemon.start()
    daemon.request_shutdown()
    daemon.mark_stopped()


def cli() -> None:
    """Primary console_script entrypoint (for pyproject.toml)."""

    app()