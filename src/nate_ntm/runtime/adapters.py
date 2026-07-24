"""Production runtime integrations and the test injection boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.runtime_config import RuntimeConfig
from .acp_client import BaseAcpClient, NateOhaAcpClient
from .agent_mail_client import BaseAgentMailClient, McpAgentMailClient
from .swarm_state import SwarmState

__all__ = ["RuntimeAdapters", "create_runtime_adapters"]


@dataclass(slots=True)
class RuntimeAdapters:
    agent_mail: BaseAgentMailClient | None
    acp: BaseAcpClient


def create_runtime_adapters(
    config: RuntimeConfig, swarm: SwarmState
) -> RuntimeAdapters:
    """Construct integrations from runtime config and materialized swarm state."""

    enabled = {
        agent_id: feature
        for agent_id, agent in swarm.agents.items()
        if (feature := agent.nate_oha_config.features.agent_mail) is not None
        and feature.enabled
    }
    agent_mail: BaseAgentMailClient | None = None
    if enabled:
        first = next(iter(enabled.values()))
        agent_mail = McpAgentMailClient(
            project_id=swarm.agent_mail_project_id,
            base_url=first.upstream_url or "",
            agent_identities={
                agent_id: feature.agent_identity or agent_id
                for agent_id, feature in enabled.items()
            },
            agent_tokens={
                agent_id: feature.credentials_ref
                for agent_id, feature in enabled.items()
                if feature.credentials_ref
            },
        )
    return RuntimeAdapters(
        agent_mail=agent_mail,
        acp=NateOhaAcpClient(config=config),
    )
