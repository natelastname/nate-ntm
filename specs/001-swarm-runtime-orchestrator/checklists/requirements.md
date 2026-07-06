# Requirements & Coverage Checklist: nate_ntm Swarm Runtime Orchestrator

**Purpose**: Track how the feature specification (FR-001–FR-014, SC-001–SC-005)
from `specs/001-swarm-runtime-orchestrator/spec.md` is reflected in code,
contracts, tests, and quickstart flows on the `001-swarm-runtime-orchestrator`
branch.

**Feature**: `specs/001-swarm-runtime-orchestrator/spec.md`

---

## 1. Specification Quality (authoring stage)

These items validate the *spec text itself*, independent of implementation.
They were completed before planning and remain true for the finalized spec.

- [x] No implementation details (languages, frameworks, specific APIs or libraries)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders while preserving necessary domain concepts
- [x] All mandatory sections completed (User Scenarios, Requirements, Success Criteria, Assumptions)

### Requirement Completeness

- [x] No `[NEEDS CLARIFICATION]` markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation-specific details)
- [x] All acceptance scenarios for primary user stories are defined
- [x] Edge cases are identified for critical failure and boundary conditions
- [x] Scope boundaries between runtime supervision, conversation durability, and coordination durability are clearly stated
- [x] Dependencies and assumptions on external services (OpenHands, Agent Mail, UI clients) are identified

### Feature Readiness (spec-level)

- [x] All functional requirements have clear behavioral expectations suitable for later acceptance criteria
- [x] User scenarios cover primary flows of starting, resuming, and inspecting swarms and agents
- [x] Feature meets measurable outcomes defined in Success Criteria section (at the spec level)
- [x] No implementation details leak into the specification beyond essential domain terminology

---

## 2. Functional Requirements Coverage (FR-001–FR-014)

For each requirement below, check off once there is clear coverage in code,
contracts, and/or tests. Use the notes to capture any deliberate gaps or
future-work items.

- [x] **FR-001** – Swarm creation and Agent Mail coordination
  - Coverage: `RuntimeDaemon.create` plus `FakeAgentMailClient` allocate a
    coordination project and per-agent identities when creating a swarm.
    Exercised by US1 CLI and quickstart tests under
    `tests/integration/quickstart/`.

- [x] **FR-002** – Swarm metadata persistence
  - Coverage: `MetadataStore` and `RuntimeDaemon.create` persist swarm and
    per-agent metadata under `.nate_ntm/` with atomic writes. Covered by
    `tests/unit/runtime/test_metadata_store.py` and quickstart/resume tests.

- [x] **FR-003** – Runtime owns ACP/control-protocol connections
  - Coverage: ACP clients (`FakeAcpClient`, `OpenHandsAcpClient`) are used only
    via runtime-owned adapters (`RuntimeAdapters`) and `RuntimeDaemon`. UI
    clients talk exclusively to the runtime control API (`RuntimeApiServer`
    and WebSocket layer), not to agents directly.

- [ ] **FR-004** – Real agent subprocess launch and lifecycle supervision
  - Status: **Partially implemented (dev-mode only)**. `AgentSupervisor` and
    `RuntimeScheduler.launch_all_agents` create in-memory
    `AgentRuntimeState` entries and placeholder subprocess handles and update
    lifecycle status to `Idle`, but they do **not** yet manage real
    subprocesses or restart policies. Full production-grade coverage is
    deferred to future phases beyond this orchestrator MVP.

- [ ] **FR-005** – Event-driven scheduler for ACP/mailbox/runtime events
  - Status: **Skeleton only**. `RuntimeScheduler` wires configured agents
    into `RuntimeState` and performs a one-time Agent Mail poll on startup
    (for US2 resume behavior) but does not yet implement a full event loop
    or ACP turn lifecycle. A fuller scheduler remains future work.

- [x] **FR-006** – Bounded in-memory Agent Event Stream per agent
  - Coverage: `AgentEvent` and `AgentEventStream` in
    `src/nate_ntm/runtime/events.py` provide a bounded, in-memory stream with
    JSON-serializable events. Covered by unit and integration tests for
    agent inspection and event streaming (US3).

- [x] **FR-007** – Local bidirectional control API for inspection and actions
  - Coverage: `RuntimeApiServer` implements the in-process contract in
    `contracts/runtime-api.md` for `runtime.get_status`, `swarm.get_overview`,
    `agent.get_detail`, `events.subscribe`, and `events.notify`. The unified
    FastAPI/uvicorn control API (`POST /jsonrpc` plus `/events` WebSocket)
    exposes this surface over the network. CLI support is provided via
    `nate_ntm.cli` (`api call` subcommand). Exercised by quickstart
    integration tests under `tests/integration/quickstart/`.

- [ ] **FR-008** – Graceful shutdown and forced termination
  - Status: **Partially implemented**. `RuntimeDaemon.request_shutdown` and
    `mark_stopped` mirror the high-level `runtime.shutdown` semantics and
    coordinate with the FastAPI/uvicorn control API in `runtime.runner`, but
    real subprocess cancellation and forced termination behavior are not yet
    implemented.

- [x] **FR-009** – Resume existing swarm with identity and conversation reuse
  - Coverage: `RuntimeDaemon.resume` validates Agent Mail project IDs,
    per-agent identities, and ACP conversation IDs against persisted
    metadata, raising `RuntimeStartupError` on mismatch. US2 quickstart tests
    (`tests/integration/quickstart/test_resume_swarm_us2.py`) exercise the
    resume path.

- [x] **FR-010** – Surface scheduler/agent/mailbox events via control API
  - Coverage: `AgentSupervisor` publishes `AgentEvent` instances into
    per-agent streams and, via the callback installed by
    `RuntimeControlContext` in `runtime.runner`, forwards them to the
    FastAPI app's `/events` WebSocket publisher (``app.state.publish_event``)
    for `events.notify` notifications. US3 tests under
    `tests/integration/quickstart/test_runtime_ws_events_us3.py` validate
    this behavior.

- [x] **FR-011** – Single-swarm-per-runtime process
  - Coverage: `RuntimeConfig` represents exactly one project and swarm per
    runtime instance. `RuntimeDaemon` and the CLI (`nate-ntm runtime start`)
    always operate on a single project directory; running multiple swarms
    requires multiple `nate-ntm` processes.

- [ ] **FR-012** – Architecture remains valid for larger swarms
  - Status: **Design-level coverage only**. Data structures and APIs are
    designed to be swarm-size agnostic, and tests exercise small multi-agent
    scenarios, but no dedicated load/performance testing at 10–20+ agents has
    been performed yet. See SC-005 below.

- [x] **FR-013** – Runtime control API binds to loopback by default
  - Coverage: `RuntimeConfig.control_api_host` defaults to `127.0.0.1` and is
    used by the FastAPI/uvicorn control API in `runtime.runner`. Quickstart
    and tests assume a localhost-only control API.

- [x] **FR-014** – Project-local metadata as primary source of truth
  - Coverage: `RuntimeConfig` defaults `metadata_dir` to `.nate_ntm/` under
    the project directory; `MetadataStore` and `RuntimeDaemon` persist swarm
    and agent metadata there, and resume flows treat it as the authoritative
    source for reconstructing the swarm.

---

## 3. Success Criteria Coverage (SC-001–SC-005)

These items map the measurable outcomes in the spec to concrete validation
steps in quickstart flows and tests.

- [ ] **SC-001** – Startup & status within ~10 seconds
  - Coverage: US1 quickstart scenarios and tests
    (`test_start_and_status_us1.py`, `test_runtime_ws_control_api_us1.py`)
    exercise startup and `runtime.get_status`. Formal timing validation
    (ensuring the 10-second threshold across environments) remains a manual
    quickstart check.

- [x] **SC-002** – Resume behavior preserves identities and unread mail
  - Coverage: US2 quickstart test (`test_resume_swarm_us2.py`) confirms that
    resume reuses Agent Mail identities and conversation IDs and continues
    from unread mailbox state in dev-mode. Metadata persistence is covered by
    unit tests.

- [ ] **SC-003** – Agent failure handling and restart policies
  - Status: **Partially implemented**. `AgentSupervisor.mark_agent_failed`
    and `restart_agent` provide dev-mode building blocks, and scheduler-level
    hooks exist, but there is no end-to-end wiring from real subprocess
    failures through restart policies yet.

- [ ] **SC-004** – Agent inspection and event streaming latency
  - Coverage: US3 tests (`test_runtime_ws_events_us3.py`) and API handlers
    (`agent.get_detail`, `events.subscribe`, `events.notify`) confirm that
    recent events are replayable and streamed to clients. Formal measurement
    of the "under 1 second for 95% of events" latency target is not yet
    automated; this remains a manual quickstart validation.

- [ ] **SC-005** – Behavior with 15–20 active agents
  - Status: **Not yet validated**. The architecture is intended to scale to
    10–20 agents and beyond, but no dedicated load tests or quickstart runs
    at that scale have been recorded yet.

---

## 4. Notes

- This checklist now aligns the written spec (FR/SC sections) with the
  implementation (runtime config, daemon, scheduler, adapters, API surface,
  and tests) for the `001-swarm-runtime-orchestrator` branch.
- Items left unchecked deliberately represent known future work or manual
  validation steps rather than oversights in the specification.
