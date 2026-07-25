"""Agent Mail HTTP/JSON-RPC integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ["AgentMailClientError", "BaseAgentMailClient", "McpAgentMailClient"]


class AgentMailClientError(RuntimeError):
    pass


def _extract_jsonrpc_result(payload: Any, *, request_name: str) -> Any:
    if not isinstance(payload, Mapping):
        raise AgentMailClientError(f"{request_name}: invalid server response")
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = str(error.get("message") or "server request failed")
        detail = error.get("data")
        if isinstance(detail, Mapping):
            detail = detail.get("message") or detail.get("detail") or detail
        if detail not in (None, "", message):
            message = f"{message}: {detail}"
        raise AgentMailClientError(f"{request_name}: {message}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return result
    missing = object()
    structured = result.get("structuredContent", missing)
    if structured is missing:
        structured = result.get("structured_content", missing)
    if structured is missing:
        return result
    return structured.get("result", structured) if isinstance(structured, Mapping) else structured


class BaseAgentMailClient:
    def ensure_project(self) -> str:
        raise NotImplementedError

    def ensure_agent_identity(self, agent_id: str) -> str:
        raise NotImplementedError

    def ensure_agent_identity_with_credentials(
        self, agent_id: str, credentials_hint: str | None = None
    ) -> tuple[str, str | None]:
        return self.ensure_agent_identity(agent_id), credentials_hint

    def get_unread_mail_flags(self, agent_ids: Iterable[str]) -> dict[str, bool]:
        raise NotImplementedError


@dataclass(slots=True)
class McpAgentMailClient(BaseAgentMailClient):
    """Agent Mail client built only from materialized swarm configuration."""

    project_id: str
    base_url: str
    bearer_token: str | None = None
    timeout: float = 5.0
    agent_identities: Mapping[str, str] = field(default_factory=dict)
    agent_tokens: Mapping[str, str] = field(default_factory=dict)

    _project_ensured: bool = field(default=False, init=False)
    _identities: dict[str, str] = field(default_factory=dict, init=False)
    _tokens: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.project_id = self.project_id.strip()
        if not self.project_id:
            raise ValueError("Agent Mail project_id must not be empty")
        url = self.base_url.strip().rstrip("/")
        if not url:
            raise ValueError("Agent Mail base_url must not be empty")
        self.base_url = url if url.endswith("/api") else f"{url}/api"
        token = self.bearer_token
        if token is None:
            token = os.environ.get("NATE_NTM_AGENT_MAIL_TOKEN") or os.environ.get(
                "AGENT_MAIL_TOKEN"
            )
        self.bearer_token = token.strip() if token else None
        self._identities.update(self.agent_identities)
        self._tokens.update(self.agent_tokens)

    def ensure_project(self) -> str:
        if not self._project_ensured:
            self._call_tool(
                name="ensure_project",
                arguments={"human_key": self.project_id},
                request_id="nate-ntm-ensure-project",
                request_name="Agent Mail ensure_project",
            )
            self._project_ensured = True
        return self.project_id

    def ensure_agent_identity(self, agent_id: str) -> str:
        identity, _ = self.ensure_agent_identity_with_credentials(agent_id)
        return identity

    def ensure_agent_identity_with_credentials(
        self, agent_id: str, credentials_hint: str | None = None
    ) -> tuple[str, str | None]:
        if agent_id in self._identities:
            return self._identities[agent_id], self._tokens.get(agent_id) or credentials_hint
        result = self._call_tool(
            name="register_agent",
            arguments={
                "project_key": self.ensure_project(),
                "program": "nate-ntm-runtime",
                "model": "nate-ntm-swarm",
                "name": agent_id,
                "task_description": "",
                **({"registration_token": credentials_hint} if credentials_hint else {}),
            },
            request_id=f"nate-ntm-register-agent:{agent_id}",
            request_name=f"Agent Mail register_agent({agent_id})",
        )
        identity = str(result.get("name") or agent_id) if isinstance(result, Mapping) else agent_id
        raw_token = result.get("registration_token") if isinstance(result, Mapping) else None
        token = str(raw_token).strip() if raw_token is not None else credentials_hint
        self._identities[agent_id] = identity
        if token:
            self._tokens[agent_id] = token
        return identity, token or None

    def get_unread_mail_flags(self, agent_ids: Iterable[str]) -> dict[str, bool]:
        ids = list(agent_ids)
        if not ids:
            return {}
        project_id = self.ensure_project()
        flags: dict[str, bool] = {}
        for agent_id in ids:
            token = self._tokens.get(agent_id)
            if not token:
                flags[agent_id] = False
                continue
            try:
                result = self._call_tool(
                    name="fetch_inbox",
                    arguments={
                        "project_key": project_id,
                        "agent_name": agent_id,
                        "limit": 1,
                        "urgent_only": False,
                        "include_bodies": False,
                        "unread_only": True,
                        "registration_token": token,
                    },
                    request_id=f"nate-ntm-fetch-inbox:{agent_id}",
                    request_name=f"Agent Mail fetch_inbox({agent_id})",
                )
            except AgentMailClientError:
                flags[agent_id] = False
            else:
                flags[agent_id] = isinstance(result, list) and bool(result)
        return flags

    def _call_tool(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        request_id: str,
        request_name: str,
    ) -> Any:
        return self._post_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            },
            request_name=request_name,
        )

    def _post_jsonrpc(self, payload: Mapping[str, Any], *, request_name: str) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            raise AgentMailClientError(
                f"{request_name}: HTTP {exc.code} error from Agent Mail server"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise AgentMailClientError(
                f"{request_name}: failed to reach Agent Mail server"
            ) from exc
        try:
            decoded = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            raise AgentMailClientError(
                f"{request_name}: invalid JSON response from Agent Mail server"
            ) from exc
        return _extract_jsonrpc_result(decoded, request_name=request_name)
