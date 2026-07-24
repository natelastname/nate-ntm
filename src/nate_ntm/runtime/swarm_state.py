from __future__ import annotations

"""Durable swarm state models."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from nate_oha.config import NateOHAConfig
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["AgentState", "SwarmState"]


class AgentState(BaseModel):
    """Durable state for one agent within a swarm."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    role: Optional[str] = None
    conversation_id: Optional[str] = None
    restart_policy: Dict[str, Any] = Field(default_factory=dict)
    last_known_status: str = "Idle"
    nate_oha_config: NateOHAConfig

    @field_validator("agent_id", "display_name")
    @classmethod
    def _must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class SwarmState(BaseModel):
    """Complete authoritative persisted state for one swarm."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    swarm_id: str
    project_path: Path
    agent_mail_project_id: str = ""
    created_at: datetime
    last_updated_at: datetime
    config_version: Optional[str] = None
    agents: Dict[str, AgentState] = Field(default_factory=dict)
    runtime_options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("swarm_id")
    @classmethod
    def _swarm_id_must_not_be_empty(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("swarm_id must be non-empty without surrounding whitespace")
        return value

    @field_validator("project_path")
    @classmethod
    def _normalize_project_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @model_validator(mode="after")
    def _validate_agent_mail_consistency(self) -> "SwarmState":
        configured = {
            (
                feature.project,
                feature.upstream_url,
            )
            for agent in self.agents.values()
            if (feature := agent.nate_oha_config.features.agent_mail) is not None
            and feature.enabled
        }
        if len(configured) > 1:
            raise ValueError("all Agent Mail-enabled agents must share one project and URL")
        if configured:
            project, _ = next(iter(configured))
            if self.agent_mail_project_id and str(project) != self.agent_mail_project_id:
                raise ValueError(
                    "SwarmState.agent_mail_project_id does not match agent configuration"
                )
        return self

    @classmethod
    def from_json(cls, data: str) -> "SwarmState":
        return cls.model_validate_json(data)

    def to_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def validate(self, *, expected_swarm_id: str) -> None:
        """Validate store-level identity without re-supplying project context."""

        if self.swarm_id != expected_swarm_id:
            raise ValueError(
                f"SwarmState.swarm_id {self.swarm_id!r} does not match expected "
                f"swarm_id {expected_swarm_id!r}"
            )
