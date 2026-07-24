from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from nate_oha.config import NateOHAConfig

from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_ntm.swarm_constructors import agent_mail_constructor, apply_constructors


def _config(*, agent_mail: dict[str, object] | None = None) -> NateOHAConfig:
    return NateOHAConfig.model_validate(
        {
            "runtime": {"mode": "agent"},
            "llm": {"model": "openai/test"},
            "openhands": {"confirmation_mode": "llm-approve"},
            "prompt": {},
            "features": {"agent_mail": agent_mail},
        }
    )


def _swarm() -> SwarmState:
    now = datetime.now(timezone.utc)
    return SwarmState(
        swarm_id="demo",
        project_path=Path.cwd(),
        created_at=now,
        last_updated_at=now,
        agents={
            "Planner": AgentState(
                agent_id="Planner",
                display_name="Planner",
                nate_oha_config=_config(),
            ),
            "code_reviewer": AgentState(
                agent_id="code_reviewer",
                display_name="Code Reviewer",
                nate_oha_config=_config(),
            ),
        },
    )


def test_agent_mail_constructor_materializes_complete_swarm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NATE_NTM_AGENT_MAIL_UPSTREAM_URL", "http://mail.test")
    source = _swarm()

    result = apply_constructors(source, ["agent-mail"])

    assert result.agent_mail_project_id == "demo-agent-mail"
    assert result.runtime_options["constructors"] == ["agent-mail"]
    assert source.agent_mail_project_id == ""
    assert source.agents["Planner"].nate_oha_config.features.agent_mail is None

    planner = result.agents["Planner"].nate_oha_config.features.agent_mail
    reviewer = result.agents["code_reviewer"].nate_oha_config.features.agent_mail
    assert planner is not None and reviewer is not None
    assert planner.enabled and reviewer.enabled
    assert planner.project == reviewer.project == Path("demo-agent-mail")
    assert planner.agent_identity == "planner"
    assert reviewer.agent_identity == "code-reviewer"
    assert planner.credentials_ref != reviewer.credentials_ref
    assert planner.upstream_url == reviewer.upstream_url == "http://mail.test"


def test_constructors_run_in_requested_order() -> None:
    def append(name: str):
        def constructor(swarm: SwarmState) -> SwarmState:
            result = swarm.model_copy(deep=True)
            result.runtime_options.setdefault("order", []).append(name)
            return result

        return constructor

    result = apply_constructors(
        _swarm(),
        ["first", "second"],
        registry={"first": append("first"), "second": append("second")},
    )

    assert result.runtime_options["order"] == ["first", "second"]
    assert result.runtime_options["constructors"] == ["first", "second"]


def test_duplicate_constructor_is_rejected() -> None:
    with pytest.raises(ValueError, match="more than once"):
        apply_constructors(_swarm(), ["agent-mail", "agent-mail"])


def test_conflicting_explicit_agent_mail_identity_is_rejected() -> None:
    swarm = _swarm()
    swarm.agents["Planner"].nate_oha_config = _config(
        agent_mail={
            "enabled": True,
            "project": "demo-agent-mail",
            "agent_identity": "someone-else",
            "credentials_ref": "secret",
            "upstream_url": "http://mail.test",
        }
    )

    with pytest.raises(ValueError, match="conflicting Agent Mail identity"):
        agent_mail_constructor(swarm)
