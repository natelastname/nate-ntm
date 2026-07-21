"""Production runtime integrations and the test injection boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.runtime_config import RuntimeConfig
from .acp_client import BaseAcpClient, NateOhaAcpClient
from .agent_mail_client import BaseAgentMailClient, McpAgentMailClient

__all__ = ["RuntimeAdapters", "create_runtime_adapters"]


@dataclass(slots=True)
class RuntimeAdapters:
    agent_mail: BaseAgentMailClient
    acp: BaseAcpClient


def create_runtime_adapters(config: RuntimeConfig) -> RuntimeAdapters:
    """Construct the single production implementation of each integration."""

    return RuntimeAdapters(
        agent_mail=McpAgentMailClient(config=config),
        acp=NateOhaAcpClient(config=config),
    )
