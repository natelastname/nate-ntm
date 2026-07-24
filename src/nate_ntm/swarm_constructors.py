"""One-time transformations applied while materializing a swarm."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from secrets import token_urlsafe

from nate_oha.config import AgentMailFeatureConfig

from .runtime.swarm_state import SwarmState

_DEFAULT_AGENT_MAIL_URL = "http://127.0.0.1:8765"
_INVALID_IDENTITY_CHARS = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True, slots=True)
class ConstructionContext:
    agent_mail_project_id: str | None = None
    agent_mail_url: str | None = None


SwarmConstructor = Callable[[SwarmState, ConstructionContext], SwarmState]


def _identity(agent_id: str) -> str:
    identity = _INVALID_IDENTITY_CHARS.sub("-", agent_id.strip().lower()).strip("-")
    if not identity:
        raise ValueError(f"cannot derive Agent Mail identity from agent id {agent_id!r}")
    return identity


def agent_mail_constructor(
    swarm: SwarmState,
    context: ConstructionContext,
) -> SwarmState:
    """Add one shared Agent Mail setup to every agent in ``swarm``."""

    result = swarm.model_copy(deep=True)
    project_id = context.agent_mail_project_id or result.swarm_id
    upstream_url = context.agent_mail_url or _DEFAULT_AGENT_MAIL_URL
    identities: set[str] = set()

    for agent_id, agent in result.agents.items():
        identity = _identity(agent_id)
        if identity in identities:
            raise ValueError(f"duplicate generated Agent Mail identity {identity!r}")
        identities.add(identity)

        existing = agent.nate_oha_config.features.agent_mail
        if existing is not None:
            if existing.project is not None and str(existing.project) != project_id:
                raise ValueError(
                    f"agent {agent_id!r} has conflicting Agent Mail project "
                    f"{str(existing.project)!r}"
                )
            if existing.agent_identity and existing.agent_identity != identity:
                raise ValueError(
                    f"agent {agent_id!r} has conflicting Agent Mail identity "
                    f"{existing.agent_identity!r}"
                )
            if existing.upstream_url and existing.upstream_url != upstream_url:
                raise ValueError(
                    f"agent {agent_id!r} has conflicting Agent Mail URL "
                    f"{existing.upstream_url!r}"
                )

        agent.nate_oha_config.features.agent_mail = AgentMailFeatureConfig(
            enabled=True,
            project=project_id,
            agent_identity=identity,
            credentials_ref=(
                existing.credentials_ref
                if existing is not None and existing.credentials_ref
                else token_urlsafe(24)
            ),
            upstream_url=upstream_url,
        )

    result.agent_mail_project_id = project_id
    return result


CONSTRUCTORS: Mapping[str, SwarmConstructor] = {
    "agent-mail": agent_mail_constructor,
}


def apply_constructors(
    swarm: SwarmState,
    names: Sequence[str],
    context: ConstructionContext | None = None,
    *,
    registry: Mapping[str, SwarmConstructor] = CONSTRUCTORS,
) -> SwarmState:
    """Apply named constructors once, in the order supplied."""

    if len(names) != len(set(names)):
        raise ValueError("a constructor may not be selected more than once")

    context = context or ConstructionContext()
    result = swarm
    for name in names:
        try:
            constructor = registry[name]
        except KeyError as exc:
            raise ValueError(f"unknown swarm constructor {name!r}") from exc
        result = constructor(result, context)

    if names:
        result = result.model_copy(deep=True)
        result.runtime_options["constructors"] = list(names)
    return result
