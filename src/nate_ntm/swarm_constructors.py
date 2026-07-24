"""One-time transformations applied while materializing a swarm."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from secrets import token_urlsafe

from nate_oha.config import AgentMailFeatureConfig

from .runtime.swarm_state import SwarmState

SwarmConstructor = Callable[[SwarmState], SwarmState]

_DEFAULT_AGENT_MAIL_URL = "http://127.0.0.1:8765"
_INVALID_IDENTITY_CHARS = re.compile(r"[^a-z0-9-]+")


def _identity(agent_id: str) -> str:
    identity = _INVALID_IDENTITY_CHARS.sub("-", agent_id.strip().lower()).strip("-")
    if not identity:
        raise ValueError(f"cannot derive Agent Mail identity from agent id {agent_id!r}")
    return identity


def _first_environment_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def agent_mail_constructor(swarm: SwarmState) -> SwarmState:
    """Add one shared Agent Mail setup to every agent in ``swarm``."""

    result = swarm.model_copy(deep=True)
    project_id = (
        result.agent_mail_project_id
        or _first_environment_value("NATE_NTM_AGENT_MAIL_PROJECT", "AGENT_MAIL_PROJECT")
        or f"{result.swarm_id}-agent-mail"
    )
    upstream_url = _first_environment_value(
        "NATE_NTM_AGENT_MAIL_URL",
        "AGENT_MAIL_UPSTREAM_URL",
        "AGENT_MAIL_URL",
    ) or _DEFAULT_AGENT_MAIL_URL

    identities: set[str] = set()
    for agent_id, agent in result.agents.items():
        identity = _identity(agent_id)
        if identity in identities:
            raise ValueError(f"duplicate generated Agent Mail identity {identity!r}")
        identities.add(identity)

        existing = agent.nate_oha_config.features.agent_mail
        if existing is not None:
            if existing.project is not None and Path(existing.project) != Path(project_id):
                raise ValueError(
                    f"agent {agent_id!r} has conflicting Agent Mail project "
                    f"{str(existing.project)!r}"
                )
            if existing.agent_identity and existing.agent_identity != identity:
                raise ValueError(
                    f"agent {agent_id!r} has conflicting Agent Mail identity "
                    f"{existing.agent_identity!r}"
                )

        credentials_ref = (
            existing.credentials_ref
            if existing is not None and existing.credentials_ref
            else token_urlsafe(24)
        )
        configured_url = (
            existing.upstream_url
            if existing is not None and existing.upstream_url
            else upstream_url
        )
        agent.nate_oha_config.features.agent_mail = AgentMailFeatureConfig(
            enabled=True,
            project=Path(project_id),
            agent_identity=identity,
            credentials_ref=credentials_ref,
            upstream_url=configured_url,
        )

    result.agent_mail_project_id = project_id
    return result


CONSTRUCTORS: Mapping[str, SwarmConstructor] = {
    "agent-mail": agent_mail_constructor,
}


def apply_constructors(
    swarm: SwarmState,
    names: Sequence[str],
    *,
    registry: Mapping[str, SwarmConstructor] = CONSTRUCTORS,
) -> SwarmState:
    """Apply named constructors once, in the order supplied."""

    if len(names) != len(set(names)):
        raise ValueError("a constructor may not be selected more than once")

    result = swarm
    for name in names:
        result = registry[name](result)

    if names:
        result = result.model_copy(deep=True)
        result.runtime_options["constructors"] = list(names)
    return result
