"""Transport-agnostic runtime control API handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..runtime.daemon import RuntimeDaemon
from ..runtime.state import RuntimeStatus

__all__ = ["RuntimeApiServer"]


@dataclass(slots=True)
class RuntimeApiServer:
    daemon: RuntimeDaemon

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def get_runtime_status(self) -> dict[str, Any]:
        return self.daemon.get_runtime_status()

    def get_swarm_overview(self) -> dict[str, Any]:
        return self.daemon.get_swarm_status()

    def shutdown_runtime(self, timeout_seconds: int = 30) -> dict[str, Any]:
        if self.daemon.state.status is not RuntimeStatus.RUNNING:
            raise RuntimeError(
                f"Cannot shutdown runtime from status "
                f"{self.daemon.state.status.value!r}"
            )
        self.daemon.request_shutdown()
        return {
            "accepted": True,
            "status": self.daemon.state.status.value,
        }

    def get_agent_detail(self, agent_id: str) -> dict[str, Any]:
        return self.daemon.get_agent_detail(agent_id=agent_id)
