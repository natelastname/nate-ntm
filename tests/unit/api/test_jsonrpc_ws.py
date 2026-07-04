"""Tests for the WebSocket JSON-RPC runtime control server.

These tests exercise a minimal end-to-end flow over a real WebSocket
connection using the :class:`JsonRpcWebSocketServer` implementation.

The goal is to validate that:

* JSON-RPC requests are dispatched to :class:`RuntimeApiServer` and
  responses are returned to the client.
* ``events.subscribe`` wires up the subscription registry so that
  :meth:`JsonRpcWebSocketServer.publish_event` results in server-side
  ``events.notify`` notifications for matching subscribers.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import websockets

from nate_ntm.api.jsonrpc_ws import JsonRpcWebSocketServer
from nate_ntm.api.server import RuntimeApiServer
from nate_ntm.api.jsonrpc import JSONRPC_VERSION
from nate_ntm.config.runtime_config import load_runtime_config
from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.events import AgentEvent, AgentEventSource
from nate_ntm.runtime.metadata_store import MetadataStore, SwarmMetadata
from nate_ntm.runtime.state import AgentRuntimeState, AgentStatus, RuntimeState, RuntimeStatus


def _make_daemon(tmp_path: Path) -> RuntimeDaemon:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(project_path=project)

    store = MetadataStore(config=config)
    state = RuntimeState(config=config)
    now = datetime(2026, 7, 3, 12, 0, 0)
    swarm = SwarmMetadata(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
    )

    return RuntimeDaemon(
        config=config,
        metadata_store=store,
        swarm_metadata=swarm,
        state=state,
        startup_mode=None,  # type: ignore[arg-type]
    )


def test_websocket_jsonrpc_runtime_get_status_roundtrip(tmp_path: Path) -> None:
    """A client can call ``runtime.get_status`` over WebSocket JSON-RPC."""

    async def main() -> None:
        daemon = _make_daemon(tmp_path)

        # Seed minimal runtime state.
        daemon.state.agents = {
            "a1": AgentRuntimeState(agent_id="a1", status=AgentStatus.RUNNING),
            "a2": AgentRuntimeState(agent_id="a2", status=AgentStatus.IDLE),
        }
        daemon.state.status = RuntimeStatus.RUNNING

        api_server = RuntimeApiServer(daemon=daemon)
        ws_server = JsonRpcWebSocketServer(api_server=api_server, host="127.0.0.1", port=0)
        await ws_server.start()

        uri = f"ws://127.0.0.1:{ws_server.bound_port}"

        async with websockets.connect(uri) as client:
            request = {
                "jsonrpc": JSONRPC_VERSION,
                "method": "runtime.get_status",
                "params": {},
                "id": 1,
            }
            await client.send(json.dumps(request))

            raw = await client.recv()
            response = json.loads(raw)

            assert response["jsonrpc"] == JSONRPC_VERSION
            assert response["id"] == 1
            result = response["result"]
            assert result["status"] == RuntimeStatus.RUNNING.value
            assert result["project_path"] == str(daemon.config.project_path)

        await ws_server.stop()

    asyncio.run(main())


def test_websocket_jsonrpc_events_subscribe_and_notify(tmp_path: Path) -> None:
    """Subscribing over WebSocket results in ``events.notify`` messages."""

    async def main() -> None:
        daemon = _make_daemon(tmp_path)
        daemon.state.status = RuntimeStatus.RUNNING

        api_server = RuntimeApiServer(daemon=daemon)
        ws_server = JsonRpcWebSocketServer(api_server=api_server, host="127.0.0.1", port=0)
        await ws_server.start()

        uri = f"ws://127.0.0.1:{ws_server.bound_port}"

        async with websockets.connect(uri) as client:
            # Issue an events.subscribe request for a specific agent.
            subscribe_request = {
                "jsonrpc": JSONRPC_VERSION,
                "method": "events.subscribe",
                "params": {"agent_ids": ["agent-1"], "include_runtime": False},
                "id": 2,
            }
            await client.send(json.dumps(subscribe_request))

            raw_sub = await client.recv()
            sub_response = json.loads(raw_sub)

            assert sub_response["jsonrpc"] == JSONRPC_VERSION
            assert sub_response["id"] == 2
            sub_id = sub_response["result"]["subscription_id"]
            assert isinstance(sub_id, str)

            # Emit an event for agent-1 and publish it via the WebSocket
            # server. The client should observe an events.notify
            # notification for the matching subscription.
            event = AgentEvent(
                event_id="e1",
                timestamp=datetime(2026, 7, 3, 12, 0, 0),
                agent_id="agent-1",
                source=AgentEventSource.RUNTIME,
                type="TestEvent",
                payload={"k": "v"},
            )

            await ws_server.publish_event(event)

            raw_notify = await client.recv()
            notify = json.loads(raw_notify)

            assert notify["jsonrpc"] == JSONRPC_VERSION
            assert notify["method"] == "events.notify"
            params = notify["params"]
            assert params["subscription_id"] == sub_id
            assert params["event"]["event_id"] == "e1"
            assert params["event"]["agent_id"] == "agent-1"

        await ws_server.stop()

    asyncio.run(main())
