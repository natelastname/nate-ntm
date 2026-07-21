"""Shared Pydantic models for runtime control API results."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "AgentCounts",
    "RuntimeStatusResult",
    "AgentOverview",
    "SwarmOverviewResult",
    "AgentDetailResult",
]


class AgentCounts(BaseModel):
    total: int
    starting: int
    idle: int
    running: int
    waiting: int
    failed: int


class RuntimeStatusResult(BaseModel):
    status: str
    project_path: str
    swarm_id: str
    agent_counts: AgentCounts


class AgentOverview(BaseModel):
    agent_id: str
    display_name: str
    status: str
    has_unread_mail: bool
    last_error: str | None = None


class SwarmOverviewResult(BaseModel):
    swarm_id: str
    project_path: str
    runtime_status: str
    agent_counts: AgentCounts
    agents: list[AgentOverview]


class AgentDetailResult(BaseModel):
    """Result payload for ``agent.get_detail``."""

    agent_id: str
    display_name: str
    status: str
    agent_mail_identity: str
    conversation_id: str
    last_error: str | None = None
