"""Runtime package for the nate_ntm Swarm Runtime Orchestrator.

This package contains the event-driven runtime daemon, state management,
agent lifecycle supervision, and adapters for external services.

Refer to `specs/001-swarm-runtime-orchestrator/plan.md` for the
high-level architecture and to the beads in `.beads/` for
implementation guidance.
"""

from .daemon import RuntimeDaemon
from .swarm_acp_mux import (
    ExternalACPConnection,
    NoAttachedAgentError,
    PreparedAttachment,
    StaleAttachmentError,
    SwarmACPMux,
    SwarmACPMuxClosedError,
    SwarmACPMuxError,
    SwarmAgentClient,
    UnknownAgentError,
    UnsupportedReservedUpdateError,
)

__all__ = [
    "RuntimeDaemon",
    "SwarmACPMux",
    "PreparedAttachment",
    "SwarmACPMuxError",
    "SwarmACPMuxClosedError",
    "UnknownAgentError",
    "NoAttachedAgentError",
    "StaleAttachmentError",
    "UnsupportedReservedUpdateError",
    "SwarmAgentClient",
    "ExternalACPConnection",
]
