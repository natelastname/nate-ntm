from __future__ import annotations

"""Unit tests for the durable swarm/agent state models.

These tests focus on the ConfigOverhaul MS2 tightening of
:class:`nate_ntm.runtime.swarm_state.AgentState`.

They ensure that:

* ``nate_oha_config`` is required for all persisted agents.
* Legacy per-agent Agent Mail fields (``agent_mail_identity`` and
  ``agent_mail_credentials_ref``) are rejected via ``extra="forbid"``.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from nate_oha.config import build_default_config
from nate_ntm.runtime.swarm_state import AgentState, SwarmState


def test_agent_state_requires_nate_oha_config() -> None:
    """AgentState must always include an embedded NateOhaConfig.

    This mirrors the MS2 design where the effective nate-oha configuration is
    resolved once at create time and then persisted as part of AgentState.
    Persisted agents without a config are considered invalid.
    """

    with pytest.raises(ValidationError) as excinfo:
        AgentState(agent_id="nav-1", display_name="Navigator 1")  # type: ignore[call-arg]

    msg = str(excinfo.value)
    assert "nate_oha_config" in msg
    assert "Field required" in msg


def test_agent_state_rejects_legacy_agent_mail_fields() -> None:
    """Legacy Agent Mail fields are rejected by AgentState (extra="forbid").

    Older on-disk schemas stored per-agent Agent Mail data directly on
    AgentState via ``agent_mail_identity`` and ``agent_mail_credentials_ref``.
    MS2 removes those fields in favour of the embedded NateOhaConfig. When
    loading persisted state that still uses the legacy format, validation
    should fail rather than silently ignoring the extra fields.
    """

    cfg = build_default_config()

    # Use ``model_validate`` so we exercise the same code path as
    # :class:`MetadataStore` when loading swarm.json from disk.
    with pytest.raises(ValidationError) as excinfo:
        AgentState.model_validate(
            {
                "agent_id": "nav-1",
                "display_name": "Navigator 1",
                "nate_oha_config": cfg,
                "agent_mail_identity": "nav-1@example.test",
                "agent_mail_credentials_ref": "token-123",
            }
        )

    msg = str(excinfo.value)
    assert "agent_mail_identity" in msg
    assert "Extra inputs are not permitted" in msg


def test_swarm_state_round_trip_with_tight_agent_state() -> None:
    """SwarmState can round-trip JSON with a tightened AgentState.

    This provides a lightweight sanity check that the tightened
    AgentState/SwarmState schema remains compatible with the metadata store's
    JSON-based persistence contract.
    """

    cfg = build_default_config()

    agent = AgentState(
        agent_id="nav-1",
        display_name="Navigator 1",
        nate_oha_config=cfg,
        conversation_id="",
    )

    swarm = SwarmState(
        swarm_id="swarm-1",
        project_path="/tmp/project",
        agent_mail_project_id="mail-project-1",
        created_at=datetime(2026, 7, 3, 12, 0, 0),
        last_updated_at=datetime(2026, 7, 3, 12, 0, 0),
        agents={agent.agent_id: agent},
    )

    data = swarm.to_json()
    loaded = SwarmState.from_json(data)

    assert loaded.agents["nav-1"].nate_oha_config is not None
    assert loaded.agents["nav-1"].conversation_id == ""
