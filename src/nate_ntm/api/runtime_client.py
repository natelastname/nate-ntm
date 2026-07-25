from __future__ import annotations

"""High-level async client for the runtime control API and event stream."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, Mapping, Optional

import json5
import websockets
from pydantic import ValidationError
from websockets.exceptions import WebSocketException

from .client import JsonRpcClientError, JsonRpcHttpClient
from .jsonrpc import JSONRPC_VERSION
from .models import AgentDetailEvent, AgentDetailResult, RuntimeStatusResult, SwarmOverviewResult

__all__ = ["EventsNotify", "RuntimeClient"]

logger = logging.getLogger(__name__)


def _wire_dumps(value: Any) -> str:
    """Encode strict JSON with json-five for protocol interoperability."""

    return json5.dumps(value, quote_keys=True, trailing_commas=False)


@dataclass(slots=True)
class EventsNotify:
    subscription_id: str
    event: AgentDetailEvent


@dataclass(slots=True)
class RuntimeClient:
    host: str = "127.0.0.1"
    port: int = 8765
    timeout: Optional[float] = 10.0
    rpc_client: Optional[JsonRpcHttpClient] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.rpc_client is None:
            self.rpc_client = JsonRpcHttpClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
            )

    @property
    def _rpc(self) -> JsonRpcHttpClient:
        assert self.rpc_client is not None
        return self.rpc_client

    async def get_runtime_status(self) -> RuntimeStatusResult:
        return await self._rpc.get_runtime_status()

    async def get_swarm_overview(self) -> SwarmOverviewResult:
        return await self._rpc.get_swarm_overview()

    async def get_agent_detail(self, agent_id: str, max_events: int = 100) -> AgentDetailResult:
        result = await self._rpc.call_for_result(
            "agent.get_detail",
            {"agent_id": agent_id, "max_events": max_events},
        )
        return AgentDetailResult.model_validate(result)

    async def shutdown_runtime(self, timeout_seconds: int = 30) -> Mapping[str, Any]:
        result = await self._rpc.call_for_result(
            "runtime.shutdown",
            {"timeout_seconds": int(timeout_seconds)},
        )
        assert isinstance(result, Mapping)
        return result

    async def subscribe_events(
        self,
        *,
        agent_ids: Optional[Iterable[str]] = None,
        include_runtime: bool = True,
    ) -> str:
        params: Dict[str, Any] = {"include_runtime": bool(include_runtime)}
        if agent_ids is not None:
            params["agent_ids"] = list(agent_ids)
        result = await self._rpc.call_for_result("events.subscribe", params)
        sub_id = result.get("subscription_id") if isinstance(result, Mapping) else None
        if not isinstance(sub_id, str):
            raise ValueError("events.subscribe did not return a string subscription_id")
        return sub_id

    async def unsubscribe_events(self, subscription_id: str) -> Mapping[str, Any]:
        result = await self._rpc.call_for_result(
            "events.unsubscribe",
            {"subscription_id": subscription_id},
        )
        assert isinstance(result, Mapping)
        return result

    def _events_ws_uri(self) -> str:
        return f"ws://{self.host}:{self.port}/events"

    def iter_events(
        self,
        *,
        subscription_id: Optional[str] = None,
        agent_ids: Optional[Iterable[str]] = None,
        include_runtime: bool = True,
        reconnect: bool = True,
        reconnect_initial_backoff: float = 0.5,
        reconnect_max_backoff: float = 5.0,
    ) -> AsyncIterator[EventsNotify]:
        if subscription_id is not None and agent_ids is not None:
            raise ValueError("Provide either subscription_id or agent_ids, not both")

        async def iterate() -> AsyncIterator[EventsNotify]:
            auto_unsubscribe = subscription_id is None
            sub_id = subscription_id or await self.subscribe_events(
                agent_ids=agent_ids,
                include_runtime=include_runtime,
            )
            backoff = float(reconnect_initial_backoff)
            try:
                while True:
                    try:
                        async with websockets.connect(self._events_ws_uri()) as websocket:
                            await websocket.send(_wire_dumps({"subscription_id": sub_id}))
                            backoff = float(reconnect_initial_backoff)
                            while True:
                                raw = await websocket.recv()
                                text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
                                try:
                                    message = json5.loads(text)
                                except ValueError:
                                    logger.debug("runtime_client_ignored_non_json_frame")
                                    continue
                                if not isinstance(message, Mapping):
                                    continue
                                if message.get("jsonrpc") != JSONRPC_VERSION:
                                    continue
                                if message.get("method") != "events.notify":
                                    continue
                                params = message.get("params") or {}
                                if not isinstance(params, Mapping):
                                    continue
                                if str(params.get("subscription_id")) != str(sub_id):
                                    continue
                                payload = params.get("event")
                                if not isinstance(payload, Mapping):
                                    continue
                                try:
                                    event = AgentDetailEvent.model_validate(payload)
                                except ValidationError:
                                    logger.debug(
                                        "runtime_client_ignored_malformed_event",
                                        extra={"payload": payload},
                                    )
                                    continue
                                yield EventsNotify(subscription_id=str(sub_id), event=event)
                    except (WebSocketException, OSError) as exc:
                        logger.warning(
                            "runtime_client_events_ws_disconnected",
                            extra={"error": str(exc)},
                        )
                        if not reconnect:
                            raise
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2.0, reconnect_max_backoff)
            finally:
                if auto_unsubscribe:
                    try:
                        await self.unsubscribe_events(sub_id)
                    except (JsonRpcClientError, OSError):
                        logger.warning(
                            "runtime_client_unsubscribe_failed",
                            extra={"subscription_id": sub_id},
                        )

        return iterate()
