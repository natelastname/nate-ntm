"""Unit tests for REAL ACP adapter wiring (T102).

These tests ensure that requesting ``AdapterKind.REAL`` for ACP selects
:class:`OpenHandsAcpClient` without performing any external network I/O.
The actual HTTP behavior is exercised by gated integration tests.
"""

from __future__ import annotations

from pathlib import Path

from nate_ntm.config.runtime_config import AdapterKind, load_runtime_config
from nate_ntm.runtime.adapters import create_runtime_adapters
from nate_ntm.runtime.agent_mail_client import FakeAgentMailClient, McpAgentMailClient
from nate_ntm.runtime.acp_client import FakeAcpClient, OpenHandsAcpClient


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_real_adapter_mode_uses_openhands_acp_client(tmp_path: Path) -> None:
    """AdapterKind.REAL selects :class:`OpenHandsAcpClient` for ACP.

    This test only exercises adapter construction; it does not perform any
    network I/O and therefore remains safe to run in offline CI.
    """

    project = _make_project(tmp_path)

    # Build a config that enables REAL only for ACP, keeping the global
    # adapter mode (and thus Agent Mail) in FAKE mode.
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_ACP_ADAPTER": AdapterKind.REAL.value,
        # Leave NATE_NTM_ADAPTER_MODE at its default ("fake") so Agent
        # Mail continues to use the in-memory adapter.
    }
    config = load_runtime_config(env=env)

    adapters = create_runtime_adapters(config)

    assert isinstance(adapters.acp, OpenHandsAcpClient)
    assert isinstance(adapters.agent_mail, FakeAgentMailClient)


def test_global_real_adapter_mode_uses_real_for_both(tmp_path: Path) -> None:
    """Global REAL mode selects real adapters for both integrations."""

    project = _make_project(tmp_path)
    env = {
        "NATE_NTM_PROJECT_DIR": str(project),
        "NATE_NTM_ADAPTER_MODE": AdapterKind.REAL.value,
    }
    config = load_runtime_config(env=env)

    adapters = create_runtime_adapters(config)

    assert isinstance(adapters.agent_mail, McpAgentMailClient)
    assert isinstance(adapters.acp, OpenHandsAcpClient)
