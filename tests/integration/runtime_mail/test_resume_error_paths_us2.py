"""US2: resume error-path integration tests for metadata and rebinding.

These tests correspond to T026 in ``tasks.md`` and exercise targeted
edge cases for the runtime's resume semantics under the ConfigOverhaul
MS2 model, focusing on FR-009 and SC-002:

1. Missing swarm state when starting in resume mode.
2. Mismatched per-agent Agent Mail identity against embedded
   :class:`nate_oha.config.NateOHAConfig`.
3. Pre-populated ACP conversation identifiers that do not block
   resume.

They complement the happy-path resume test in
``tests/integration/quickstart/test_resume_swarm_us2.py`` by locking
in failure behavior while the resume logic is small and easy to reason
about. All fixtures construct agents with a valid embedded
:class:`nate_oha.config.NateOHAConfig` and do not rely on incomplete
legacy metadata.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from nate_oha.config import AgentMailFeatureConfig, FeaturesConfig, build_default_config

from nate_ntm.config.runtime_config import RuntimeConfig, load_runtime_config
from nate_ntm.runtime.daemon import (
    MetadataMissingError,
    RuntimeDaemon,
    RuntimeStartupError,
)
from nate_ntm.runtime.metadata_store import MetadataStore
from nate_ntm.runtime.swarm_state import AgentState, SwarmState
from nate_ntm.runtime.state import RuntimeStatus
from ..quickstart.test_resume_swarm_us2 import _install_stub_adapters


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def _base_swarm(config: RuntimeConfig) -> SwarmState:
    """Construct a minimal SwarmState instance for tests.

    By default this uses a simple placeholder Agent Mail project ID
    (``"mail-project-1"``) so that existing US1-style metadata remains
    valid. Tests that need strict fake-client rebinding semantics
    override ``agent_mail_project_id`` explicitly.
    """

    now = datetime(2026, 7, 3, 12, 0, 0)
    return SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
        agents={},
    )


def test_resume_errors_when_swarm_state_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T026.1: mode=resume fails fast when swarm state is missing.

    Expectation: :class:`MetadataMissingError` is raised before any
    attempt to construct a :class:`RuntimeDaemon` when ``swarm.json``
    does not exist for the project.
    """

    project = _make_project(tmp_path)
    config: RuntimeConfig = load_runtime_config(project_path=project)

    # Use in-memory stub adapters so these error-path tests remain hermetic.
    _install_stub_adapters(monkeypatch)

    with pytest.raises(MetadataMissingError):
        RuntimeDaemon.resume(config)


def test_resume_fails_on_agent_mail_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T026.3: Agent Mail identity mismatch for an agent fails resume.

    The runtime treats divergence between the adapter-derived
    ``agent_mail_identity`` and the value stored in the persisted
    NateOhaConfig (``features.agent_mail.agent_identity``) as a startup
    error to protect FR-009.
    """

    project = _make_project(tmp_path)
    config: RuntimeConfig = load_runtime_config(project_path=project)
    store = MetadataStore(config=config)

    # Use in-memory stub adapters so these error-path tests remain hermetic.
    _install_stub_adapters(monkeypatch)

    now = datetime(2026, 7, 3, 12, 0, 0)

    base_cfg = build_default_config()
    agent_mail_cfg = AgentMailFeatureConfig(
        enabled=True,
        project="mail-project-1",
        agent_identity="some-other-identity",
        credentials_ref="token-123",
        upstream_url="https://agent-mail.invalid/mcp",
    )
    features_cfg = FeaturesConfig(agent_mail=agent_mail_cfg)
    nate_oha_config = base_cfg.model_copy(update={"features": features_cfg})

    agent = AgentState(
        agent_id="nav-1",
        display_name="Navigator 1",
        nate_oha_config=nate_oha_config,
        conversation_id="",  # not relevant for this test
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
        agents={agent.agent_id: agent},
    )

    store.save_swarm_state(swarm)

    with pytest.raises(RuntimeStartupError) as excinfo:
        RuntimeDaemon.resume(config)

    assert "Agent Mail identity mismatch on resume" in str(excinfo.value)



def test_resume_fails_when_agent_mail_identity_missing_in_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T026.5: Enabled Agent Mail with empty identity fails resume.

    Under the ConfigOverhaul MS2 model an enabled Agent Mail feature must
    carry a non-empty ``agent_identity`` in the embedded
    :class:`nate_oha.config.NateOHAConfig`. Treating an empty string as
    "no binding present" would allow partially configured agents to slip
    through FR-009 resume checks, so the runtime surfaces this as a
    hard startup error.
    """

    project = _make_project(tmp_path)
    config: RuntimeConfig = load_runtime_config(project_path=project)

    # Use in-memory stub adapters so these error-path tests remain hermetic.
    _install_stub_adapters(monkeypatch)

    # Construct a minimal fake swarm/agent tree that bypasses NateOHAConfig's
    # own validation and simulates corrupted or hand-crafted metadata where
    # Agent Mail is enabled but ``agent_identity`` is empty. The runtime's
    # resume path should reject this before attempting to rebind identities
    # via the Agent Mail adapter.

    class _FakeAgentMailConfig:
        def __init__(self) -> None:
            self.enabled = True
            self.project = "mail-project-1"
            self.agent_identity = ""  # intentionally empty/invalid
            self.credentials_ref = "token-123"
            self.upstream_url = "https://agent-mail.invalid/mcp"

    class _FakeFeatures:
        def __init__(self) -> None:
            self.agent_mail = _FakeAgentMailConfig()

    class _FakeNateOhaConfig:
        def __init__(self) -> None:
            self.features = _FakeFeatures()

    class _FakeAgentState:
        def __init__(self, agent_id: str, display_name: str) -> None:
            self.agent_id = agent_id
            self.display_name = display_name
            self.nate_oha_config = _FakeNateOhaConfig()
            self.conversation_id = ""

    class _FakeSwarmState:
        def __init__(self) -> None:
            self.swarm_id = config.swarm_id
            self.project_path = config.project_path
            self.agent_mail_project_id = "mail-project-1"
            self.created_at = datetime(2026, 7, 3, 12, 0, 0)
            self.last_updated_at = self.created_at
            self.agents = {"nav-1": _FakeAgentState("nav-1", "Navigator 1")}

    fake_swarm = _FakeSwarmState()

    # Ensure the swarm state file exists so that `check_startup_preconditions`
    # passes. The actual contents are ignored because we monkeypatch the
    # metadata store's loader below.
    swarm_path = config.metadata_dir / "swarm.json"
    swarm_path.parent.mkdir(parents=True, exist_ok=True)
    swarm_path.write_text("{}", encoding="utf-8")

    # Monkeypatch the MetadataStore used by RuntimeDaemon to return our
    # in-memory fake swarm state instead of loading from disk.
    from nate_ntm.runtime import metadata_store as metadata_store_mod

    def _fake_load_swarm_state(self: metadata_store_mod.MetadataStore) -> _FakeSwarmState:  # type: ignore[override]
        return fake_swarm

    monkeypatch.setattr(metadata_store_mod.MetadataStore, "load_swarm_state", _fake_load_swarm_state)  # type: ignore[arg-type]

    with pytest.raises(RuntimeStartupError) as excinfo:
        RuntimeDaemon.resume(config)

    msg = str(excinfo.value)
    assert "Agent Mail identity is missing or empty in NateOhaConfig" in msg
    assert "nav-1" in msg


def test_resume_allows_conversation_id_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T026.4: Pre-populated ACP conversation IDs do not block resume.

    At this stage the runtime treats the persisted ``conversation_id`` as an
    opaque ACP session identifier. Resume does not attempt to validate it
    eagerly against the ACP adapter; more detailed mismatch detection is
    covered by dedicated runtime_acp integration tests.
    """

    project = _make_project(tmp_path)
    config: RuntimeConfig = load_runtime_config(project_path=project)
    store = MetadataStore(config=config)

    # Use in-memory stub adapters so these error-path tests remain hermetic.
    _install_stub_adapters(monkeypatch)

    now = datetime(2026, 7, 3, 12, 0, 0)

    agent = AgentState(
        agent_id="nav-1",
        display_name="Navigator 1",
        nate_oha_config=build_default_config(),
        conversation_id="some-other-conversation",
    )

    swarm = SwarmState(
        swarm_id=config.swarm_id,
        project_path=config.project_path,
        agent_mail_project_id="mail-project-1",
        created_at=now,
        last_updated_at=now,
        agents={agent.agent_id: agent},
    )

    store.save_swarm_state(swarm)

    daemon = RuntimeDaemon.resume(config)
    daemon.start()

    assert daemon.state.status is RuntimeStatus.RUNNING
    assert daemon.swarm_state.agents["nav-1"].conversation_id == "some-other-conversation"


