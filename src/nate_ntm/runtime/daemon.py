"""Runtime daemon lifecycle and introspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..config.runtime_config import RuntimeConfig
from .acp_client import BaseAcpClient
from .adapters import RuntimeAdapters, create_runtime_adapters
from .agent_mail_client import BaseAgentMailClient
from .metadata_store import MetadataStore
from .nate_oha_launch import build_effective_nate_oha_config
from .state import AgentRuntimeState, AgentStatus, RuntimeState, RuntimeStatus
from .swarm_state import AgentState, SwarmState

__all__ = [
    "StartupMode",
    "RuntimeStartupError",
    "MetadataAlreadyExistsError",
    "MetadataMissingError",
    "RuntimeDaemon",
    "check_startup_preconditions",
]


class StartupMode(str, Enum):
    CREATE = "create"
    RESUME = "resume"


class RuntimeStartupError(RuntimeError):
    pass


class MetadataAlreadyExistsError(RuntimeStartupError):
    pass


class MetadataMissingError(RuntimeStartupError):
    pass


def check_startup_preconditions(config: RuntimeConfig, mode: StartupMode) -> None:
    path = config.metadata_dir / "swarm.json"
    if mode is StartupMode.CREATE and path.exists():
        raise MetadataAlreadyExistsError(
            f"Swarm state already exists at {path}; refusing create mode"
        )
    if mode is StartupMode.RESUME and not path.exists():
        raise MetadataMissingError(f"Swarm state not found at {path}; cannot resume")


def _map_acp_status(value: str) -> str | None:
    value = value.strip().lower()
    if value == "running":
        return AgentStatus.RUNNING.value
    if value in {"idle", "terminated"}:
        return AgentStatus.IDLE.value
    if value == "failed":
        return AgentStatus.FAILED.value
    return None


@dataclass(slots=True)
class RuntimeDaemon:
    config: RuntimeConfig
    metadata_store: MetadataStore
    swarm_state: SwarmState
    state: RuntimeState
    startup_mode: StartupMode
    started_at: datetime | None = None
    agent_mail_client: BaseAgentMailClient | None = None
    acp_client: BaseAcpClient | None = None

    @classmethod
    def create(
        cls,
        config: RuntimeConfig,
        *,
        agent_count: int | None = None,
        adapters: RuntimeAdapters | None = None,
    ) -> RuntimeDaemon:
        check_startup_preconditions(config, StartupMode.CREATE)
        adapters = adapters or create_runtime_adapters(config)
        store = MetadataStore(config=config)
        project_id = adapters.agent_mail.ensure_project()

        agents: dict[str, AgentState] = {}
        for index in range(1, (agent_count or 0) + 1):
            agent_id = f"agent-{index}"
            identity, credentials_ref = (
                adapters.agent_mail.ensure_agent_identity_with_credentials(agent_id)
            )
            try:
                nate_oha_config = build_effective_nate_oha_config(
                    config=config,
                    agent_mail_identity=identity,
                    agent_mail_credentials_ref=credentials_ref,
                )
            except ValueError as exc:
                raise RuntimeStartupError(
                    f"Failed to build nate-oha config for {agent_id!r}: {exc}"
                ) from exc
            agents[agent_id] = AgentState(
                agent_id=agent_id,
                display_name=f"Agent {index}",
                nate_oha_config=nate_oha_config,
            )

        now = datetime.utcnow()
        swarm = SwarmState(
            swarm_id=config.swarm_id,
            project_path=config.project_path,
            agent_mail_project_id=project_id,
            created_at=now,
            last_updated_at=now,
            agents=agents,
        )
        store.save_swarm_state(swarm)
        return cls(
            config=config,
            metadata_store=store,
            swarm_state=swarm,
            state=RuntimeState(config=config),
            startup_mode=StartupMode.CREATE,
            agent_mail_client=adapters.agent_mail,
            acp_client=adapters.acp,
        )

    @classmethod
    def resume(
        cls,
        config: RuntimeConfig,
        *,
        adapters: RuntimeAdapters | None = None,
    ) -> RuntimeDaemon:
        check_startup_preconditions(config, StartupMode.RESUME)
        adapters = adapters or create_runtime_adapters(config)
        store = MetadataStore(config=config)
        return cls(
            config=config,
            metadata_store=store,
            swarm_state=store.load_swarm_state(),
            state=RuntimeState(config=config),
            startup_mode=StartupMode.RESUME,
            agent_mail_client=adapters.agent_mail,
            acp_client=adapters.acp,
        )

    def start(self) -> None:
        if self.state.status is RuntimeStatus.RUNNING:
            return
        if self.state.status is not RuntimeStatus.STARTING:
            raise RuntimeStartupError(
                f"Cannot start runtime from status {self.state.status!r}"
            )
        for agent_id in self.swarm_state.agents:
            self.state.agents.setdefault(
                agent_id,
                AgentRuntimeState(agent_id=agent_id, status=AgentStatus.IDLE),
            )
        self.state.status = RuntimeStatus.RUNNING
        self.started_at = datetime.utcnow()

    def request_shutdown(self) -> None:
        if self.state.status in {RuntimeStatus.STOPPED, RuntimeStatus.FAILED}:
            return
        self.state.shutdown_requested = True
        if self.state.status is RuntimeStatus.RUNNING:
            self.state.status = RuntimeStatus.SHUTTING_DOWN

    def mark_stopped(self) -> None:
        self.state.status = RuntimeStatus.STOPPED

    def mark_agent_failed(self, agent_id: str, error: str | None = None) -> None:
        agent = self._require_runtime_agent(agent_id)
        agent.status = AgentStatus.FAILED
        agent.last_error = error

    def restart_agent(self, agent_id: str) -> None:
        agent = self._require_runtime_agent(agent_id)
        agent.status = AgentStatus.IDLE
        agent.last_error = None

    def _require_runtime_agent(self, agent_id: str) -> AgentRuntimeState:
        agent = self.state.agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent_id: {agent_id!r}")
        return agent

    def _compute_agent_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in AgentStatus}
        for agent in self.state.agents.values():
            counts[agent.status] += 1
        return {
            "total": sum(counts.values()),
            "starting": counts[AgentStatus.STARTING],
            "idle": counts[AgentStatus.IDLE],
            "running": counts[AgentStatus.RUNNING],
            "waiting": counts[AgentStatus.WAITING],
            "failed": counts[AgentStatus.FAILED],
        }

    def get_runtime_status(self) -> dict[str, object]:
        return {
            "status": self.state.status.value,
            "project_path": str(self.config.project_path),
            "swarm_id": self.config.swarm_id,
            "agent_counts": self._compute_agent_counts(),
        }

    def get_swarm_status(self) -> dict[str, object]:
        agent_ids = sorted(set(self.swarm_state.agents) | set(self.state.agents))
        unread = (
            self.agent_mail_client.get_unread_mail_flags(agent_ids)
            if self.agent_mail_client is not None
            else {}
        )
        return {
            "swarm_id": self.config.swarm_id,
            "project_path": str(self.config.project_path),
            "runtime_status": self.state.status.value,
            "agent_counts": self._compute_agent_counts(),
            "agents": [
                {
                    "agent_id": agent_id,
                    "display_name": (
                        self.swarm_state.agents[agent_id].display_name
                        if agent_id in self.swarm_state.agents
                        else agent_id
                    ),
                    "status": (
                        self.state.agents[agent_id].status.value
                        if agent_id in self.state.agents
                        else AgentStatus.STARTING.value
                    ),
                    "has_unread_mail": bool(unread.get(agent_id, False)),
                    "last_error": (
                        self.state.agents[agent_id].last_error
                        if agent_id in self.state.agents
                        else None
                    ),
                }
                for agent_id in agent_ids
            ],
        }

    def get_agent_detail(self, agent_id: str) -> dict[str, object]:
        runtime = self.state.agents.get(agent_id)
        try:
            metadata = self.metadata_store.load_agent_state(agent_id)
        except FileNotFoundError:
            metadata = self.swarm_state.agents.get(agent_id)
        if runtime is None and metadata is None:
            raise KeyError(f"Unknown agent_id: {agent_id!r}")

        status = runtime.status.value if runtime else metadata.last_known_status or AgentStatus.STARTING.value
        last_error = runtime.last_error if runtime else None
        if runtime is None and self.acp_client is not None:
            try:
                status = _map_acp_status(self.acp_client.get_status(agent_id).state) or status
            except Exception:
                pass

        if metadata is None:
            return {
                "agent_id": agent_id,
                "display_name": agent_id,
                "status": status,
                "agent_mail_identity": "",
                "conversation_id": "",
                "last_error": last_error,
            }

        return {
            "agent_id": agent_id,
            "display_name": metadata.display_name,
            "status": status,
            "agent_mail_identity": (
                metadata.nate_oha_config.features.agent_mail.agent_identity or ""
            ).strip(),
            "conversation_id": metadata.conversation_id or "",
            "last_error": last_error,
        }
