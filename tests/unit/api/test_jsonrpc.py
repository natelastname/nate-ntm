from __future__ import annotations

from datetime import datetime
from pathlib import Path

from nate_ntm.api.jsonrpc import JSONRPC_VERSION, dispatch_request
from nate_ntm.api.server import RuntimeApiServer
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import RuntimeDaemon, StartupMode
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState, RuntimeStatus
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_oha.config import build_default_config


def _server(tmp_path: Path) -> RuntimeApiServer:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)
    daemon = RuntimeDaemon(
        config=config,
        metadata_store=MetadataStore(config=config),
        swarm_state=SwarmState(
            swarm_id=config.swarm_id,
            project_path=config.project_path,
            agent_mail_project_id="mail-project-1",
            created_at=datetime(2026, 7, 3, 12, 0, 0),
            last_updated_at=datetime(2026, 7, 3, 12, 0, 0),
        ),
        state=RuntimeState(config=config),
        startup_mode=StartupMode.RESUME,
    )
    return RuntimeApiServer(daemon)


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params or {},
        "id": request_id,
    }


def test_runtime_status_success_envelope(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.daemon.state.status = RuntimeStatus.RUNNING

    response = dispatch_request(server, _request("runtime.get_status"))

    assert response["jsonrpc"] == JSONRPC_VERSION
    assert response["result"]["status"] == RuntimeStatus.RUNNING.value


def test_agent_detail_is_event_free_and_unknown_agent_is_structured_error(tmp_path: Path) -> None:
    server = _server(tmp_path)
    metadata = AgentState(
        agent_id="agent-1",
        display_name="Agent One",
        nate_oha_config=build_default_config(),
    )
    server.daemon.swarm_state = server.daemon.swarm_state.model_copy(
        update={"agents": {metadata.agent_id: metadata}}
    )
    server.daemon.state.agents[metadata.agent_id] = AgentRuntimeState(
        agent_id=metadata.agent_id,
        status=AgentStatus.RUNNING,
    )

    response = dispatch_request(
        server,
        _request("agent.get_detail", {"agent_id": metadata.agent_id}),
    )
    assert response["result"]["agent_id"] == metadata.agent_id
    assert "events" not in response["result"]

    missing = dispatch_request(
        server,
        _request("agent.get_detail", {"agent_id": "missing"}),
    )
    assert missing["error"]["code"] == 1001


def test_shutdown_conflict_and_unknown_method_errors(tmp_path: Path) -> None:
    server = _server(tmp_path)

    conflict = dispatch_request(server, _request("runtime.shutdown"))
    assert conflict["error"]["code"] == 1100

    unknown = dispatch_request(server, _request("events.subscribe"))
    assert unknown["error"]["code"] == 1000
    assert "Unknown method" in unknown["error"]["message"]


def test_invalid_protocol_and_params(tmp_path: Path) -> None:
    server = _server(tmp_path)
    invalid_version = dispatch_request(
        server,
        {"jsonrpc": "1.0", "method": "runtime.get_status", "id": 1},
    )
    assert invalid_version["error"]["code"] == 1000

    invalid_params = dispatch_request(
        server,
        {
            "jsonrpc": JSONRPC_VERSION,
            "method": "runtime.get_status",
            "params": [],
            "id": 2,
        },
    )
    assert invalid_params["error"]["code"] == 1000
