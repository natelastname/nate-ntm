"""Unit tests for REAL Agent Mail adapter wiring (T101).

These tests ensure that requesting ``AdapterKind.REAL`` for Agent Mail
selects :class:`McpAgentMailClient` without performing any external
network I/O. The actual HTTP/MCP behavior is covered by gated
integration tests.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient, McpAgentMailClient
from nate_ntm.runtime.acp_client import FakeAcpClient


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_real_adapter_mode_uses_mcp_agent_mail_client(tmp_path: Path) -> None:
    """AdapterKind.REAL selects :class:`McpAgentMailClient` for Agent Mail.

    This test only exercises adapter construction; it does not perform any
    network I/O and therefore remains safe to run in offline CI.
    """

    project = _make_project(tmp_path)

    # Build a config that enables REAL only for Agent Mail, keeping the
    # global adapter mode (and thus ACP) in FAKE mode.
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_AGENT_MAIL_ADAPTER": AdapterKind.REAL.value,
        # Leave NATE_NTM_ADAPTER_MODE at its default ("fake") so ACP
        # continues to use the in-memory adapter.
    }
    config = load_runtime_config(env=env)

    adapters = create_runtime_adapters(config)

    assert isinstance(adapters.agent_mail, McpAgentMailClient)
    # With the global adapter mode left at its default (FAKE), ACP
    # continues to use the in-memory adapter even though Agent Mail is
    # configured as REAL.
    assert isinstance(adapters.acp, FakeAcpClient)


def test_fake_adapter_mode_still_uses_fake_agent_mail_client(tmp_path: Path) -> None:
    """AdapterKind.FAKE continues to select the in-memory fake adapter."""

    project = _make_project(tmp_path)
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_ADAPTER_MODE": AdapterKind.FAKE.value,
    }
    config = load_runtime_config(env=env)

    adapters = create_runtime_adapters(config)

    assert isinstance(adapters.agent_mail, FakeAgentMailClient)
