# Test Suite Redundancy Review

This document summarizes a review of the current test suite, focusing on REAL Nate OHA ACP + Agent Mail integration and the Epic 005 / T049 work.

The goal is to identify tests that are clearly non-redundant, tests with valuable but overlapping coverage, and the safest candidates to trim if you want to reduce duplication while keeping strong real-path invariants.

---

## 1. Scope of the Review

The review focused on tests that touch:

### REAL Nate OHA ACP + Launch Spec

- `tests/unit/runtime/test_nate_oha_launch.py`
- `tests/unit/runtime/test_adapters_real_acp_t102.py`
- `tests/integration/runtime_acp/test_nate_oha_acp_client_integration_002.py`
- `tests/integration/runtime_acp/test_runtime_daemon_acp_async_real_path_epic005.py`

### REAL Agent Mail

- `tests/unit/runtime/test_agent_mail_client.py`
- `tests/integration/runtime_mail/test_mcp_agent_mail_client_integration_t101.py`
- `tests/integration/runtime_mail/test_resume_error_paths_us2.py`

### RuntimeDaemon create/resume + identity/conversation semantics

- `tests/unit/runtime/test_daemon.py`
- `tests/integration/quickstart/test_resume_swarm_us2.py`
- `tests/integration/quickstart/test_nate_oha_agent_mail_integration_t242.py`
- `tests/e2e/test_real_runtime_nate_oha_agent_mail.py`

### ACP wiring and events

- `tests/unit/runtime/test_acp_connection.py`
- `tests/unit/runtime/test_acp_event_translation.py`
- `tests/unit/runtime/test_acp_protocol_client.py`
- The Epic 005 async integration tests

TUI, CLI, generic API tests (e.g. under `tests/tui`, `tests/integration/quickstart/test_runtime_cli_us1.py`, `tests/unit/api/`) are clearly orthogonal and treated as non-redundant.

---

## 2. Tests that are clearly non-redundant

These each have a distinct, narrow responsibility and are **not** made obsolete by the new real-path tests.

### 2.1 ACP / Nate OHA

#### `tests/unit/runtime/test_nate_oha_launch.py`

Focus: `NateOhaLaunchSpec` and `build_nate_oha_launch_spec`.

- Tests that Nate OHA launches are constructed from a base JSON configuration plus runtime-specific overrides.
- Asserts:
  - argv structure: `nate-oha acp --config <path>`, presence/absence of `--resume`.
  - Presence and ordering of `--set` overrides (determinism).
  - Mapping of Agent Mail fields into `features.agent_mail.*` arguments.
  - Conflict handling and allowed paths for `extra_overrides`.

No other test asserts on this level of structured argv detail; the E2E/integration tests only treat launch behavior as a black box.

#### `tests/unit/runtime/test_acp_connection.py`

Focus: `open_nate_oha_acp_client` orchestration.

- Stubs `acp.spawn_stdio_transport` and `acp.client.ClientSideConnection`.
- Verifies that:
  - The subprocess command/env/cwd are passed through correctly.
  - A `NateNtmAcpProtocolClient` instance is constructed for the given `agent_id`.
  - The returned connection and process objects are the stubbed instances.
  - Exiting the context closes the connection and triggers the stubbed subprocess teardown.

Unique coverage: how the runtime composes the ACP SDK helpers. No other test does this without relying on a real binary.

#### `tests/unit/runtime/test_acp_event_translation.py`

Focus: `translate_acp_update`.

- Uses real `acp.schema` models (`UserMessageChunk`, `ToolCallStart`, `UsageUpdate`).
- Verifies:
  - Event type mapping (`acp.user_message_chunk`, `acp.tool_call`, `acp.usage_update`).
  - Event IDs and sequence behavior.
  - Payload shape, including `session_id` and nested `update` fields.
  - That non-positive sequence numbers are rejected with `ValueError`.

Epic 005 real-path tests only assert that at least one `acp.*` event exists and that `session_id` payloads are consistent, not the detailed mapping.

#### `tests/unit/runtime/test_acp_protocol_client.py`

Focus: `NateNtmAcpProtocolClient` behavior.

- `session_update` emits a single `AgentEvent` with:
  - Correct agent ID, source (`AgentEventSource.ACP`), event ID, and `session_id` in payload.
- `request_permission` and `ext_method` raise `RequestError` with specific codes and structured `data`.
- `NATE_NTM_CLIENT_CAPABILITIES` is a concrete `ClientCapabilities` instance with expected defaults (filesystem and terminal disabled).

No other test checks these protocol-level details; they are not redundant.

#### `tests/integration/runtime_acp/test_nate_oha_acp_client_integration_002.py`

Focus: smoke tests for `NateOhaAcpClient` against a real Nate OHA installation.

- `test_ensure_conversation_is_idempotent`:
  - Calls `client.ensure_conversation("agent-1")` twice and once for `"agent-2"`.
  - Asserts:
    - Same agent → stable ID.
    - Different agent → different ID.

- `test_start_and_stop_agent_roundtrip`:
  - Uses bare `AgentMetadata` (no Agent Mail) and real `NateOhaAcpClient`.
  - Asserts:
    - `start_agent` leads to `state == "running"`.
    - `stop_agent` leads to `state in {"terminated", "failed"}`.
    - `_process_handles` no longer contains the agent.

These adapter-level tests are the only place where `ensure_conversation` and `start_agent`/`stop_agent` are validated directly against real Nate OHA, independent of `RuntimeDaemon`.

### 2.2 Agent Mail

#### `tests/integration/runtime_mail/test_mcp_agent_mail_client_integration_t101.py`

Focus: `McpAgentMailClient` against a running Agent Mail server.

- Gated on `NATE_NTM_AGENT_MAIL_URL` / `AGENT_MAIL_URL`.
- Asserts:
  - `ensure_project` returns a stable, non-empty project ID.
  - `ensure_agent_identity_with_credentials` returns identity + token and is idempotent with the same token.
  - `get_unread_mail_flags` returns `False` for a new agent and `False` for an unknown agent.

This file is the canonical adapter-level Agent Mail integration test and is not redundant.

#### `tests/unit/runtime/test_agent_mail_client.py`

Focus: configuration mapping to Agent Mail project key.

- Constructs a `McpAgentMailClient` via `load_runtime_config` with an explicit `agent_mail_project`.
- Asserts that `ensure_project` returns exactly the configured project key (or its canonical equivalent), not some derived path.

This nuance (project key coming from `RuntimeConfig.agent_mail_project`, not the project path) is not checked elsewhere. T101 uses env-based configuration and default behavior. This file is therefore non-redundant.

#### `tests/integration/runtime_mail/test_resume_error_paths_us2.py`

Focus: negative resume semantics (US2, T026).

- `test_resume_errors_when_swarm_metadata_missing`:
  - `RuntimeDaemon.resume` raises `MetadataMissingError` when `swarm.json` is absent.
- `test_resume_fails_on_agent_mail_identity_mismatch`:
  - Divergent Agent Mail identity between metadata and adapter → `RuntimeStartupError` with FR-009 wording.
- `test_resume_fails_on_conversation_id_mismatch`:
  - Divergent ACP conversation ID between metadata and adapter → `RuntimeStartupError`.
- `test_resume_allows_incomplete_legacy_metadata_with_empty_fields`:
  - Empty identity/conversation fields in metadata still allow resume; status is `RuntimeStatus.RUNNING`.

These negative/legacy cases are not exercised by Epic 005 or E2E tests and are unique.

### 2.3 RuntimeDaemon basics and non-ACP/Agent-Mail behavior

Within `tests/unit/runtime/test_daemon.py`, several tests focus on core daemon behavior independent of real adapters:

- Startup preconditions:
  - `test_check_startup_preconditions_create_fails_if_metadata_exists`.
  - `test_check_startup_preconditions_resume_fails_if_metadata_missing`.
- Constructing state from metadata:
  - `test_runtime_daemon_resume_constructs_state_from_metadata`.
- Basic lifecycle transitions:
  - `test_runtime_daemon_start_and_shutdown_transitions`.
  - `test_runtime_daemon_start_rejects_invalid_transition`.
- Aggregating and exposing state:
  - `test_runtime_daemon_get_runtime_status_aggregates_agent_counts`.
  - `test_runtime_daemon_get_swarm_overview_joins_metadata_and_runtime_state`.

These tests cover pure RuntimeDaemon semantics and are not made redundant by real-path adapter tests.

### 2.4 Quickstart API / CLI / WS tests

Files under `tests/integration/quickstart/` (other than T242) and the TUI/CLI tests are clearly distinct:

- `tests/integration/quickstart/test_start_and_status_us1.py`
- `tests/integration/quickstart/test_runtime_cli_us1.py`
- `tests/integration/quickstart/test_runtime_ws_control_api_us1.py`
- `tests/integration/quickstart/test_runtime_ws_events_us3.py`
- `tests/integration/quickstart/test_resume_swarm_us2.py`
- `tests/tui/integration/*.py` and `tests/tui/unit/*.py`

These test CLI wiring, HTTP/WS endpoints, and TUI flows. No ACP/Agent Mail integration test replaces them.

---

## 3. Areas with real overlap

The significant overlaps are centered on **REAL runtime + Nate OHA + Agent Mail** coverage.

### 3.1 E2E canonical test

`tests/e2e/test_real_runtime_nate_oha_agent_mail.py`

This is now the most comprehensive real-path check for **create → start → shutdown → resume** with REAL adapters.

- Uses REAL runtime + REAL `McpAgentMailClient` + REAL `NateOhaAcpClient`.
- Uses `create_runtime_adapters(config)` and points Nate OHA at `nate-oha-profiles/profile1.json`.
- Flow:
  1. Configure Agent Mail project key and URL via env.
  2. `RuntimeDaemon.create(config, agent_count=1, adapters=adapters)`.
  3. Assert:
     - `swarm.agent_mail_project_id` matches the configured project key.
     - `agent_meta.agent_mail_identity`, `agent_mail_credentials_ref`, and `conversation_id` are non-empty.
  4. `daemon.start()` and `daemon.acp_client.start_agent("agent-1", ...)`:
     - `get_status("agent-1").state == "running"`.
     - `get_agent_detail("agent-1")` returns at least one ACP-originated event.
  5. Stop agent and confirm `_process_handles` has no entry for `agent-1`.
  6. Construct **fresh** `RuntimeConfig` and adapters for the same project.
  7. `RuntimeDaemon.resume(config2, adapters=adapters2)`:
     - Asserts that Agent Mail project & agent metadata are reused.
  8. Start the resumed runtime, restart Nate OHA, and confirm that identity + conversation remain unchanged.

This test effectively becomes the canonical E2E validation of REAL adapter wiring and metadata continuity.

### 3.2 Quickstart-style REAL integration T242

`tests/integration/quickstart/test_nate_oha_agent_mail_integration_t242.py`

- Also uses REAL `McpAgentMailClient` + REAL `NateOhaAcpClient` via `create_runtime_adapters(config)`.
- Gated on `NATE_OHA_INTEGRATION`.
- Flow:
  1. Build REAL `RuntimeConfig` (`adapter_mode=AdapterKind.REAL`).
  2. `adapters = create_runtime_adapters(config)` and assert concrete types.
  3. `RuntimeDaemon.create(config, agent_count=1, adapters=adapters)`.
  4. Assert:
     - `swarm.agent_mail_project_id` matches project key.
     - `agent_meta.agent_mail_identity`, `agent_mail_credentials_ref`, `conversation_id` non-empty.
  5. `acp_client.start_agent("agent-1", ...)` + `stop_agent`:
     - `state == "running"` then `state in {"terminated", "failed"}`.
     - `_process_handles` cleanup.
  6. `mail_client.get_unread_mail_flags(["agent-1"])` returns a mapping containing `"agent-1"`.

#### Overlap with other tests

- **Creation + metadata invariants**:
  - Duplicated almost exactly by the E2E test (`test_real_runtime_nate_oha_agent_mail_create_start_resume`).

- **Process lifecycle (start/stop)**:
  - Duplicated by:
    - `tests/integration/runtime_acp/test_nate_oha_acp_client_integration_002.py::test_start_and_stop_agent_roundtrip` (adapter-level).
    - The E2E test.
    - `tests/unit/runtime/test_daemon.py::test_runtime_daemon_agent_detail_persists_running_status_from_nate_oha_acp` (status reflection + persistence).

- **Agent Mail `get_unread_mail_flags`**:
  - Duplicated and more strongly specified by:
    - `tests/integration/runtime_mail/test_mcp_agent_mail_client_integration_t101.py` (adapter-level behavior, including unknown agents).

#### What T242 uniquely asserts now

- That `get_unread_mail_flags` is invoked through the **runtime-owned** Agent Mail client (`daemon.agent_mail_client`), not a directly constructed `McpAgentMailClient`.

Given that:

- Adapter wiring for REAL Agent Mail is covered by `tests/unit/runtime/test_adapters_real_acp_t102.py` and the E2E test.
- Adapter-level Agent Mail functionality is covered by T101.
- REAL runtime + REAL adapter create/start/stop is covered by the E2E test.

The remaining uniqueness of T242 (one `get_unread_mail_flags` call via a runtime-owned client) is very thin.

**Conclusion for T242**

- This is the **most redundant test** in the current suite.
- Nearly all of its invariants are covered by:
  - The E2E real-runtime test.
  - `test_nate_oha_acp_client_integration_002`.
  - `test_mcp_agent_mail_client_integration_t101`.

If you want to slim down the suite while preserving strong real-path guarantees, this is the **first candidate to delete or heavily trim**.

If you keep it, it should be explicitly treated as an auxiliary, quickstart-style smoke test, not as the primary integration test for REAL adapters.

### 3.3 REAL-adapter tests in `tests/unit/runtime/test_daemon.py`

There are two tests in `tests/unit/runtime/test_daemon.py` that use REAL adapters.

#### `test_runtime_daemon_create_with_real_acp_persists_nate_oha_metadata`

- Sets `NATE_NTM_ADAPTER_MODE=real` and constructs a REAL `RuntimeConfig`.
- Calls `RuntimeDaemon.create(config, agent_count=1)`.
- Loads `AgentMetadata("agent-1")` from disk and asserts:
  - `agent_mail_identity` is non-empty and whitespace-trimmed.
  - `conversation_id` is non-empty.
  - `daemon.acp_client.ensure_conversation("agent-1") == meta.conversation_id`.

#### `test_runtime_daemon_create_and_resume_with_real_acp_and_agent_mail`

- Uses the same REAL configuration.
- Scenario:
  1. `RuntimeDaemon.create(config, agent_count=1)`.
  2. `meta_before = store.load_agent_metadata("agent-1")`.
  3. `RuntimeDaemon.resume(config)` with REAL adapters.
  4. `meta_after` matches `meta_before` for identity and conversation.
  5. `daemon_resume.acp_client.ensure_conversation("agent-1") == meta_after.conversation_id`.

#### Overlap with other tests

- Metadata creation and persistence with REAL adapters:
  - Covered by the E2E test (`test_real_runtime_nate_oha_agent_mail_create_start_resume`).

- Identity/conversation reuse across resume:
  - Covered by:
    - The E2E test (REAL adapters, full create → resume scenario).
    - `tests/integration/quickstart/test_resume_swarm_us2.py` (fake + REAL-ACP variants).

- Consistency between `ensure_conversation` and persisted metadata:
  - Covered for the Epic 005 async path in:
    - `tests/integration/runtime_acp/test_runtime_daemon_acp_async_real_path_epic005.py`.
      - Async start persists ACP `session_id` into `AgentMetadata.conversation_id`.
      - A fresh `NateOhaAcpClient.ensure_conversation` returns that same `session_id`.

#### What these two tests still add

- They exercise **synchronous** `RuntimeDaemon.create` / `resume` with REAL adapters, without async ACP or explicit `start_agent`.
- They act as a fast smoke test around `RuntimeDaemon` + REAL adapter wiring and metadata without depending on the full async ACP path.
- They encode small invariants like trimmed `agent_mail_identity`.

**Conclusion for these REAL-adapter daemon tests**

- They are **partially redundant** with the E2E + Epic 005 + quickstart US2 tests.
- However, they are short and directly target `RuntimeDaemon.create`/`resume`, making them useful defense-in-depth.

If you want to reduce repetition:

- Consider merging them into a **single** create+resume test.
- Or drop `test_runtime_daemon_create_with_real_acp_persists_nate_oha_metadata` and keep only the create+resume variant, since the E2E test thoroughly covers creation.

### 3.4 Status persistence from REAL ACP into agent detail

`tests/unit/runtime/test_daemon.py::test_runtime_daemon_agent_detail_persists_running_status_from_nate_oha_acp`

- Uses a real `NateOhaAcpClient` and real `nate-oha` binary.
- Now explicitly sets:
  - `NATE_NTM_NATE_OHA_CONFIG` to repo’s `nate-oha-profiles/profile1.json`.
  - `NATE_NTM_NATE_OHA_RUNTIME_MODE="echo"`.
- Flow:
  1. Seed `AgentMetadata` and `SwarmMetadata` for agent `"nav-1"` with `last_known_status="Idle"`.
  2. `client = NateOhaAcpClient(config=config, executable="nate-oha")`.
  3. `client.start_agent("nav-1", metadata=meta)`.
  4. `RuntimeDaemon.resume(config, adapters=RuntimeAdapters(agent_mail=FakeAgentMailClient, acp=client))`.
  5. Call `daemon.get_agent_detail("nav-1", max_events=10)`.
  6. Assert:
     - `detail["agent"]["status"] == AgentStatus.RUNNING.value`.
     - `MetadataStore` now persists `last_known_status == AgentStatus.RUNNING.value`.

No other test does this:

- E2E and Epic 005 tests care about conversation IDs, Agent Mail identity, and events, not about reflection of ACP **process status** into `get_agent_detail` and `AgentMetadata.last_known_status`.

This test is **not redundant**; it uniquely guards the “ACP running state → agent detail + persisted last known status” invariant.

---

## 4. Resume semantics tests

Several tests cover resume semantics from different angles; they are largely complementary.

### 4.1 Quickstart US2

`tests/integration/quickstart/test_resume_swarm_us2.py`

- `test_resume_swarm_us2_reuses_agent_identities_and_conversations`:
  - Uses **fake** adapters to exercise a simple create → shutdown → resume.
  - Asserts that Agent Mail identities and ACP conversation IDs are unchanged across resume.
  - Uses `RuntimeApiServer` to verify `runtime.get_status` and `swarm.get_overview`.

- `test_resume_swarm_us2_reuses_identities_and_conversations_with_real_acp`:
  - Uses REAL ACP + Fake Agent Mail.
  - Confirms that nate_OHA-backed conversation IDs are unchanged across resume.

### 4.2 Runtime Mail US2 (error paths)

`tests/integration/runtime_mail/test_resume_error_paths_us2.py`

- Negative FR-009 / SC-002 behavior: missing metadata, identity mismatch, conversation mismatch, and behavior with legacy empty fields.

### 4.3 Epic 005 async real-path tests

`tests/integration/runtime_acp/test_runtime_daemon_acp_async_real_path_epic005.py`

- Async ACP session persistence with REAL adapters, including:
  - `start_agent_async` with `session/new` → `AgentMetadata.conversation_id` persistence.
  - Reuse of ACP `session_id` via a fresh `NateOhaAcpClient.ensure_conversation`.
  - Event payloads’ `session_id` matching the persisted value.
  - `RuntimeDaemon.get_agent_detail` exposing the persisted `conversation_id` even without runtime state.
- A second test extends this with REAL Agent Mail (`McpAgentMailClient`) and fully agent-mail-enabled Nate OHA sessions.

These sets of tests cover:

- Fake vs REAL adapters.
- Sync vs async paths.
- Positive vs negative semantics.

They are **not** redundant with one another and should all be kept.

---

## 5. Summary of redundancy and recommendations

### 5.1 Strongest candidate for removal or consolidation

**`tests/integration/quickstart/test_nate_oha_agent_mail_integration_t242.py`**

- Nearly every invariant it checks is covered elsewhere:
  - Creation metadata and REAL adapter wiring: E2E test.
  - `NateOhaAcpClient.start_agent`/`stop_agent` behavior: adapter integration test + E2E + daemon status-persistence test.
  - Agent Mail unread flags: `test_mcp_agent_mail_client_integration_t101`.

- What it uniquely asserts is thin: that a runtime-owned `McpAgentMailClient` instance can make one `get_unread_mail_flags` call.

**Recommendation:**

- If you want to simplify the suite while maintaining strong real-path coverage, this is the **safest test to delete** or heavily shrink.
- If kept, it should be explicitly documented as a quickstart-style smoke, and you should accept its overlap with the E2E and adapter-level tests.

### 5.2 Mildly redundant but still useful

The two REAL-adapter tests in `tests/unit/runtime/test_daemon.py`:

- `test_runtime_daemon_create_with_real_acp_persists_nate_oha_metadata`.
- `test_runtime_daemon_create_and_resume_with_real_acp_and_agent_mail`.

They overlap with E2E + Epic 005 + quickstart US2, but provide:

- A direct, synchronous smoke test of `RuntimeDaemon.create` / `resume` with REAL adapters.
- An extra check that `ensure_conversation` matches persisted `conversation_id` without going through the async ACP path.

**Recommendations:**

- Keep them for now as fast, focused guards.
- If you later decide to reduce duplication further:
  - Merge them into a single create+resume test, **or**
  - Drop the simpler “create-only” test and retain the create+resume test.

### 5.3 Everything else

All other tests mentioned in this review play a unique role:

- Launch spec and adapter wiring tests:
  - `test_nate_oha_launch.py`.
  - `test_adapters_real_acp_t102.py`.
- ACP SDK orchestration and event translation:
  - `test_acp_connection.py`.
  - `test_acp_event_translation.py`.
  - `test_acp_protocol_client.py`.
- Agent Mail client behavior:
  - `test_agent_mail_client.py`.
  - `test_mcp_agent_mail_client_integration_t101.py`.
- Async Epic 005 / T049 real-path integration:
  - `test_runtime_daemon_acp_async_real_path_epic005.py`.
- Resume semantics and negative paths:
  - `test_resume_swarm_us2.py`.
  - `test_resume_error_paths_us2.py`.
- RuntimeDaemon lifecycle and aggregation:
  - Core unit tests in `test_daemon.py`.
- E2E real runtime + Nate OHA + Agent Mail:
  - `tests/e2e/test_real_runtime_nate_oha_agent_mail.py`.

These should all be kept as they contribute distinct, valuable coverage.
