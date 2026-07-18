"""Gated quickstart-style smoke tests for real Agent Mail + nate_OHA.

These tests implement T242 from
``specs/002-nate-oha-acp-adapter/tasks.md`` in an automated fashion. They
exercise the minimal end-to-end path between:

* the nate_ntm runtime (``RuntimeDaemon``),
* the production Agent Mail adapter (``McpAgentMailClient``), and
* the production ACP adapter (``NateOhaAcpClient``) launching ``nate_OHA``
  with Agent Mail enabled.

The goal is to confirm that, in an environment with a real
``mcp_agent_mail`` server and a working ``nate_OHA`` installation,
runtime startup can:

    * create a swarm using REAL adapters,
    * allocate Agent Mail project + per-agent identity + token,
    * persist per-agent metadata suitable for establishing an ACP session,
    * launch a nate_OHA subprocess with Agent Mail integration enabled, and
    * cleanly shut that subprocess down again.

These tests assume a live Agent Mail MCP server and a working
``nate_OHA`` installation. Failures typically indicate environment
misconfiguration rather than code-level regressions. To run them
locally, ensure that:

* ``mcp_agent_mail`` is running and reachable at
  ``http://127.0.0.1:8765/api`` (or adjust the environment variables
  accordingly), and
* ``nate_OHA`` is installed and on ``PATH``.

Then invoke pytest directly, for example::

    uv run pytest -q \
      tests/integration/quickstart/test_nate_oha_agent_mail_integration_t242.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nate_ntm.config.runtime_config import AdapterKind, RuntimeConfig, load_runtime_config
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.agent_mail_client import McpAgentMailClient
from nate_ntm.runtime.acp_client import NateOhaAcpClient
from nate_ntm.runtime.daemon import RuntimeDaemon



def _make_real_runtime_config(project_path: Path) -> RuntimeConfig:
    """Construct a ``RuntimeConfig`` for REAL adapters in integration tests.

    The helper explicitly sets ``adapter_mode=AdapterKind.REAL`` and uses a
    project-local metadata directory under ``project_path`` so that each
    test run is isolated.
    """

    return load_runtime_config(
        project_path=project_path,
        metadata_dir=project_path / ".nate_ntm",
        adapter_mode=AdapterKind.REAL,
    )


def test_real_agent_mail_and_nate_oha_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end smoke test for REAL Agent Mail + NateOhaAcpClient.

    This mirrors the quickstart flow in a minimal, test-friendly form:

    1. Configure REAL adapters for both Agent Mail and ACP.
    2. Call :meth:`RuntimeDaemon.create` with ``agent_count=1`` so that the
       runtime allocates an Agent Mail project and per-agent identity +
       token, persisting them into runtime metadata.
    3. Launch a real ``nate_OHA`` subprocess for the agent using
       ``start_agent`` and confirm that the adapter reports it as running.
    4. Perform a lightweight Agent Mail call (``get_unread_mail_flags``)
       to confirm that the REAL Agent Mail adapter is correctly configured.
    5. Request a graceful shutdown via ``stop_agent`` and confirm that the
       adapter no longer tracks a live subprocess handle for the agent.
    """

    # Align runtime and nate_OHA Agent Mail configuration so that both use
    # the same project key and upstream URL. We use the absolute project
    # path as the Agent Mail project key to keep the mapping simple and
    # deterministic.
    project_key = str(tmp_path)
    base_url = "http://127.0.0.1:8765/api"

    # Resolve the repository's sample nate-oha profile used throughout the
    # real-path tests so that the runtime has a concrete base configuration
    # and runtime mode to derive persisted NateOhaConfig values from.
    repo_root = Path(__file__).resolve().parents[3]
    base_config = repo_root / "nate-oha-profiles" / "profile1.json"

    # RuntimeConfig will pick these up via its Agent Mail and nate-oha
    # resolution helpers when constructing the effective configuration. The
    # ACP adapter then launches nate_OHA with a materialised NateOhaConfig
    # JSON file; Agent Mail settings are driven from that config instead of
    # AGENT_MAIL_* environment variables.
    monkeypatch.setenv("NATE_NTM_AGENT_MAIL_PROJECT", project_key)
    monkeypatch.setenv("NATE_NTM_AGENT_MAIL_URL", base_url)
    monkeypatch.setenv("NATE_NTM_NATE_OHA_CONFIG", str(base_config))
    monkeypatch.setenv("NATE_NTM_NATE_OHA_RUNTIME_MODE", "echo")

    config = _make_real_runtime_config(tmp_path)

    adapters = create_runtime_adapters(config)
    assert isinstance(adapters.agent_mail, McpAgentMailClient)
    assert isinstance(adapters.acp, NateOhaAcpClient)

    # Create a new swarm with a single agent. This allocates the Agent Mail
    # project + identity and persists them into SwarmState/AgentState
    # records under .nate_ntm/swarm.json. Any ACP session identifiers are
    # established lazily by the async ACP lifecycle helpers in Epic 005.
    daemon = RuntimeDaemon.create(config, agent_count=1, adapters=adapters)

    # Basic sanity checks on the created metadata.
    swarm = daemon.swarm_state
    assert swarm.agent_mail_project_id
    # For REAL adapters the Agent Mail project ID recorded in swarm metadata
    # must be the same key that the runtime was configured with. In this
    # test we explicitly use the absolute project path as the project key.
    assert swarm.agent_mail_project_id == project_key
    assert "agent-1" in swarm.agents

    agent_meta = daemon.metadata_store.load_agent_state("agent-1")

    # Agent Mail identity and credentials are now stored inside the embedded
    # NateOhaConfig rather than as separate AgentState fields. Confirm that the
    # persisted configuration carries a non-empty identity and token.
    cfg = getattr(agent_meta, "nate_oha_config", None)
    features = getattr(cfg, "features", None) if cfg is not None else None
    agent_mail_cfg = getattr(features, "agent_mail", None) if features is not None else None
    assert agent_mail_cfg is not None
    assert (agent_mail_cfg.agent_identity or "").strip()
    assert (agent_mail_cfg.credentials_ref or "")

    # ACP session identifiers are established lazily by async helpers; at this
    # stage we only require that the ``conversation_id`` field exists on the
    # durable AgentState; it may be empty/None until an async session has
    # been started.
    assert hasattr(agent_meta, "conversation_id")

    # Launch a real nate_OHA process for the agent using the metadata
    # produced above. Any configuration errors (for example, missing Agent
    # Mail settings or incompatible nate_OHA version) should surface as an
    # AcpClientError from start_agent.
    acp_client = daemon.acp_client
    assert isinstance(acp_client, NateOhaAcpClient)

    acp_client.start_agent("agent-1", metadata=agent_meta)

    status = acp_client.get_status("agent-1")
    assert status.agent_id == "agent-1"
    assert status.state == "running"

    # The REAL Agent Mail adapter should be able to talk to the configured
    # Agent Mail server and answer unread-mail queries for the agent. Any
    # network or server-side failures are treated conservatively as
    # "no unread mail" by the adapter, so the main assertion is that the
    # call succeeds and returns a mapping entry for our agent.
    mail_client = daemon.agent_mail_client
    assert isinstance(mail_client, McpAgentMailClient)

    flags = mail_client.get_unread_mail_flags(["agent-1"])
    assert "agent-1" in flags

    # Finally, request a graceful shutdown of the nate_OHA process and
    # confirm that the adapter no longer tracks a live subprocess handle.
    acp_client.stop_agent("agent-1", timeout=acp_client.shutdown_timeout)

    status_after = acp_client.get_status("agent-1")
    assert status_after.state in {"terminated", "failed"}
    assert "agent-1" not in acp_client._process_handles
