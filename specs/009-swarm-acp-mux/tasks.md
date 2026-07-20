---
description: "Implementation tasks for Feature 009: SwarmACPMux"
---

# Tasks: SwarmACPMux (Epic 009)

**Input**: Design documents from `/specs/009-swarm-acp-mux/`

**Prerequisites**: `plan.md` (required), `spec.md` (normative), `research.md`, `data-model.md`, `contracts/swarm-acp-mux-session.md`, `quickstart.md`

**Tests**: This feature includes targeted unit and integration tests, as explicitly requested in `spec.md` 
§16 and `quickstart.md`.

**Organization**: Tasks are grouped by user-story-like phases so that attachment/forwarding,
reserved controls, and failure/integration behavior can each be implemented and tested
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which story phase this task belongs to (`US1`, `US2`, `US3`)
- All descriptions MUST include exact file paths.

## Path Conventions

- Single project layout: `src/`, `tests/` at repository root.
- SwarmACPMux implementation lives under `src/nate_ntm/runtime/`.
- Tests live under `tests/unit/runtime/` and `tests/integration/runtime_acp/` (baseline Epic 005)
  and `tests/integration/acp/` (new ACP-facing mux tests for this feature).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish module and test skeletons for SwarmACPMux and ACP-facing integration tests.

- [ ] T001 Create `src/nate_ntm/runtime/swarm_acp_mux.py` module with `SwarmACPMux` dataclass
  skeleton, `_Attachment` dataclass, and error type declarations from
  `specs/009-swarm-acp-mux/spec.md` and `data-model.md` (no behavior yet).
- [ ] T002 [P] Create unit test package stub `tests/unit/runtime/test_swarm_acp_mux.py` with
  empty test classes/fixtures referencing `SwarmACPMux` and `SwarmACPMuxError`.
- [ ] T003 [P] Create integration test package `tests/integration/acp/` with `__init__.py`,
  `tests/integration/acp/test_swarm_acp_mux_real_path.py`, and
  `tests/integration/acp/test_reserved_swarm_controls.py` files stubbed to follow the
  flows in `specs/009-swarm-acp-mux/quickstart.md` §3–§5.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core mux data structures and lifecycle wiring required before exercising any
scenario.

**⚠️ CRITICAL**: No scenario/user-story work should begin until this phase is complete.

- [ ] T004 Implement `_Attachment` dataclass and connection-local state fields on
  `SwarmACPMux` in `src/nate_ntm/runtime/swarm_acp_mux.py` to match
  `specs/009-swarm-acp-mux/data-model.md` §1.4 (including `attached_agent_id`,
  `_attachment`, `_lifecycle_lock`, `_failure`, `_closed`).
- [ ] T005 [P] Implement `SwarmACPMuxError` hierarchy in
  `src/nate_ntm/runtime/swarm_acp_mux.py` as specified in `specs/009-swarm-acp-mux/spec.md`
  §13 (`SwarmACPMuxClosedError`, `UnknownAgentError`, `NoAttachedAgentError`,
  `StaleAttachmentError`, `UnsupportedReservedUpdateError`).
- [ ] T006 [P] Implement `__post_init__` and `wait_failed()` plumbing in
  `SwarmACPMux` to initialize `_failure` and expose the failure waiter semantics from
  `specs/009-swarm-acp-mux/spec.md` §6, §8.10, and §14.
- [ ] T007 Wire `SwarmACPMux` into the runtime package by exporting it from
  `src/nate_ntm/runtime/__init__.py` and updating any internal imports or type hints that will
  use it in future adapter code.

---

## Phase 3: User Story 1 – Attachment & Forwarding Semantics (Priority: P1) 🎯 MVP

**Goal**: Allow a client to attach an external ACP session to a single agent and receive a
replay of retained typed ACP updates followed by live updates with correct ordering and
lifecycle semantics.

**Independent Test**: With a running runtime and ACP client layer from Epic 008, a single
external session can attach to an agent, observe `_attach` acknowledgment, then see
replay-then-live typed `SessionUpdate` values in order, and detach cleanly without stopping
the agent or affecting other subscribers (`specs/009-swarm-acp-mux/spec.md` §7–§12 and
§16.1–§16.3; `specs/009-swarm-acp-mux/quickstart.md` §3).

### Tests for User Story 1

- [ ] T008 [P] [US1] Implement attachment-establishment and ordering unit tests in
  `tests/unit/runtime/test_swarm_acp_mux.py` covering: successful `prepare_attach()` for an
  active session, `AgentSessionNotActive` propagation, no acknowledgment on failed
  preparation, and correct `PreparedAttachment.newly_prepared` behavior (spec §8.1, §16.1).
- [ ] T009 [P] [US1] Implement forwarding unit tests in
  `tests/unit/runtime/test_swarm_acp_mux.py` using fake `SwarmAgentClient` and
  `ExternalACPConnection` to verify replay-before-live, acknowledgment-before-forwarding,
  and that updates are forwarded unchanged as `SessionUpdate` instances (spec §7, §9,
  §16.2).
- [ ] T010 [P] [US1] Implement switching-attachment unit tests in
  `tests/unit/runtime/test_swarm_acp_mux.py` that simulate changing agents and assert no
  old-agent update after the new-agent acknowledgment, and that the old subscription is
  exited before the new one is acknowledged (spec §7, §9, §16.3).

### Implementation for User Story 1

- [ ] T011 [US1] Implement `prepare_attach()` in `src/nate_ntm/runtime/swarm_acp_mux.py`
  including: open/closed checks, durable swarm membership validation via `RuntimeDaemon`,
  lifecycle serialization via `_lifecycle_lock`, idempotent same-agent handling returning
  `PreparedAttachment(newly_prepared=False)`, and subscription establishment via
  `subscribe_acp_updates()` with token tracking (spec §6, §8.1; data-model §1.4).
- [ ] T012 [US1] Implement `activate_attachment()` in
  `src/nate_ntm/runtime/swarm_acp_mux.py` to validate the `PreparedAttachment` token, start
  or re-use the forwarding task, release the forwarding gate, and enforce idempotent
  activation semantics for reused attachments (spec §8.2).
- [ ] T013 [US1] Implement `abort_attachment(prepared)` internal helper or method in
  `src/nate_ntm/runtime/swarm_acp_mux.py` that performs token- and
  `newly_prepared`-aware rollback, ensuring failed acknowledgment never starts forwarding
  and never tears down a pre-existing healthy attachment (spec §8.2–§8.3 and
  `contracts/swarm-acp-mux-session.md` §3.3).
- [ ] T014 [US1] Implement `_run_forwarding()` and `_attachment_finished()` in
  `src/nate_ntm/runtime/swarm_acp_mux.py` so that forwarding waits for activation, streams
  retained+live updates through `ExternalACPConnection.session_update`, reports fatal
  failures via `_report_failure()`, and performs identity-safe cleanup (`spec.md` §9, §14).
- [ ] T015 [US1] Implement `detach()` in `src/nate_ntm/runtime/swarm_acp_mux.py` as an
  idempotent operation that cancels and awaits the forwarding task, exits the subscription
  context, and leaves the underlying agent and other subscribers running (`spec.md` §8.4,
  §9, §15).
- [ ] T016 [US1] Implement `close()` and async context-manager support (`__aenter__`,
  `__aexit__`) on `SwarmACPMux` in `src/nate_ntm/runtime/swarm_acp_mux.py` to perform
  structured shutdown and cancel `wait_failed()` callers without treating closure itself as
  a failure (`spec.md` §8.10, §10, §14; `contracts/swarm-acp-mux-session.md` §5).

---

## Phase 4: User Story 2 – Reserved Swarm Controls & Views (Priority: P2)

**Goal**: Expose swarm-level views and inspection capabilities via reserved ACP controls
`_swarm_status`, `_agent_detail`, and `_detach` backed by the existing runtime daemon APIs.

**Independent Test**: From an external ACP client, `_swarm_status` and `_agent_detail`
return shapes consistent with the runtime control API, including the current
`attached_agent_id` / `attached` flags, while `_detach` is idempotent and never stops the
underlying agent (`contracts/swarm-acp-mux-session.md` §3.1–§3.4;
`specs/009-swarm-acp-mux/quickstart.md` §4).

### Tests for User Story 2

- [ ] T017 [P] [US2] Add unit tests in `tests/unit/runtime/test_swarm_acp_mux.py` for
  `get_swarm_status()` and `get_agent_detail()` that use a fake `RuntimeDaemon` to assert
  response shapes and attachment-aware flags (`spec.md` §8.7–§8.8;
  `data-model.md` §2; contract §3.1–§3.2).
- [ ] T018 [P] [US2] Add reserved-control integration tests in
  `tests/integration/acp/test_reserved_swarm_controls.py` using a minimal Swarm ACP server
  adapter fixture to drive `_swarm_status`, `_agent_detail`, `_attach`, and `_detach` and
  assert logical payloads and error codes (contract §2–§3;
  `specs/009-swarm-acp-mux/quickstart.md` §4–§5).

### Implementation for User Story 2

- [ ] T019 [US2] Implement `get_swarm_status()` in `src/nate_ntm/runtime/swarm_acp_mux.py`
  to wrap `RuntimeDaemon.get_swarm_status()` with the `attached_agent_id` field exactly as
  described in `specs/009-swarm-acp-mux/spec.md` §8.7 and contract §3.1.
- [ ] T020 [US2] Implement `get_agent_detail()` in `src/nate_ntm/runtime/swarm_acp_mux.py`
  to wrap `RuntimeDaemon.get_agent_detail()` with `attached` flag and recent events,
  matching `specs/009-swarm-acp-mux/spec.md` §8.8,
  `specs/009-swarm-acp-mux/data-model.md` §2, and contract §3.2.
- [ ] T021 [US2] Implement a minimal in-process Swarm ACP server adapter helper (for
  example, `tests/integration/acp/_test_swarm_acp_adapter.py`) that creates a
  `SwarmACPMux` per session, dispatches reserved controls to mux/daemon methods, and maps
  domain errors to the logical error codes in `specs/009-swarm-acp-mux/contracts/swarm-acp-mux-session.md` §2.
- [ ] T022 [US2] Ensure reserved operations are not forwarded as agent-directed updates by
  tightening any adapter routing logic so underscore-prefixed client operations are
  handled at the mux boundary and never reach agent ACP sessions (`specs/009-swarm-acp-mux/spec.md` §12; contract §3; `quickstart.md` §4.3–§4.4).

---

## Phase 5: User Story 3 – Failure Propagation & Macro Integration (Priority: P3)

**Goal**: Ensure forwarding failures and shutdown conditions are observable and correctly
wired through the runtime and Swarm ACP server adapter, preserving structured concurrency
semantics.

**Independent Test**: A real-path integration test can start the runtime daemon, ACP client
layer, and Swarm ACP server adapter, run through attach → prompt/interrupt → detach flows,
and then shut everything down cleanly while confirming correct failure propagation and
lifecycle behavior (`specs/009-swarm-acp-mux/spec.md` §9–§12, §16.6–§16.9;
`specs/009-swarm-acp-mux/quickstart.md` §3–§5).

### Tests for User Story 3

- [ ] T023 [P] [US3] Extend `tests/unit/runtime/test_swarm_acp_mux.py` with
  failure-propagation tests that inject exceptions from the ACP subscription iterator and
  from `ExternalACPConnection.session_update` to ensure `_report_failure()` records the
  first fatal failure and `wait_failed()` surfaces it (`specs/009-swarm-acp-mux/spec.md`
  §9, §14, §16.7–§16.8).
- [ ] T024 [P] [US3] Implement real-path integration test
  `tests/integration/acp/test_swarm_acp_mux_real_path.py` that composes the runtime
  daemon, typed ACP streaming layer from Epic 008, Swarm ACP server adapter, and
  `SwarmACPMux` to exercise the scenario in `specs/009-swarm-acp-mux/quickstart.md` §3
  (attach, replay-then-live updates, prompt, detach).
- [ ] T025 [P] [US3] Implement integration tests in
  `tests/integration/acp/test_reserved_swarm_controls.py` verifying error handling
  behaviors from `specs/009-swarm-acp-mux/quickstart.md` §5 and
  `specs/009-swarm-acp-mux/contracts/swarm-acp-mux-session.md` §2
  (`MUX_NO_ATTACHED_AGENT`, `MUX_CLOSED`, `MUX_UNKNOWN_AGENT`,
  `MUX_AGENT_SESSION_NOT_ACTIVE`, `MUX_STALE_ATTACHMENT`, `MUX_INVALID_REQUEST`,
  `MUX_INTERNAL_ERROR`).

### Implementation for User Story 3

- [ ] T026 [US3] Implement `_report_failure()` and finalize `wait_failed()` semantics in
  `src/nate_ntm/runtime/swarm_acp_mux.py`, ensuring only the first fatal forwarding
  failure is recorded, normal subscription exhaustion and detach/close cancellations are
  not treated as failures, and structured-concurrency patterns in `specs/009-swarm-acp-mux/spec.md` §10 are supported.
- [ ] T027 [US3] Integrate `SwarmACPMux` into the Swarm ACP server adapter process (for
  example, `src/nate_ntm/runtime/acp_server_adapter.py` or an equivalent module), wiring
  structured concurrency for inbound request processing vs. `mux.wait_failed()` using the
  first-completion race described in `specs/009-swarm-acp-mux/spec.md` §10.
- [ ] T028 [US3] Ensure lifecycle serialization rules are enforced in adapter-level request
  handling so that `_attach`, `_detach`, and mux/connection shutdown follow the
  single-threaded per-session rules in `specs/009-swarm-acp-mux/spec.md` §11 and
  `specs/009-swarm-acp-mux/contracts/swarm-acp-mux-session.md` §1.2, including prevention
  of overlapping attachment transactions.
- [ ] T029 [US3] Align log messages and runtime diagnostics around mux failures and
  shutdown so that external errors corresponding to `MUX_INTERNAL_ERROR` are observable in
  test and production logs.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation alignment, checklist coverage, and final validation across design
and implementation artifacts.

- [ ] T030 [P] Update `specs/009-swarm-acp-mux/quickstart.md` to match the final test file
  paths and acceptance flows implemented in `tests/unit/runtime/test_swarm_acp_mux.py` and
  `tests/integration/acp/*.py`.
- [ ] T031 [P] Align `specs/009-swarm-acp-mux/data-model.md`, `spec.md`, and
  `contracts/swarm-acp-mux-session.md` with the actual `SwarmACPMux` implementation
  (especially `PreparedAttachment.newly_prepared`, `abort_attachment(prepared)`
  semantics, and error mapping), fixing any drift discovered during coding.
- [ ] T032 [P] Ensure `specs/009-swarm-acp-mux/checklists/acp-mux.md` is updated so that
  CHK006, CHK007, and related items accurately reflect the clarified three-stage
  attachment transaction, ack-failure behavior, and mux vs. adapter responsibilities.
- [ ] T033 [P] Add or update high-level documentation references (for example,
  `AGENTS_MK2.md` and any feature index docs) to point to the SwarmACPMux spec, plan,
  contracts, quickstart, and this tasks.md for future contributors.
- [ ] T034 Run the full SwarmACPMux quickstart validation from
  `specs/009-swarm-acp-mux/quickstart.md` (including unit tests and integration tests) and
  record any follow-up items or deviations in `specs/009-swarm-acp-mux/research.md` and a
  future `plan_feedback.md` (if added).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies – can start immediately.
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) completion – BLOCKS all
  user-story phases.
- **User Story 1 (Phase 3 – P1)**: Depends on Foundational (Phase 2); delivers the core
  attachment and forwarding MVP (`specs/009-swarm-acp-mux/spec.md` §7–§9).
- **User Story 2 (Phase 4 – P2)**: Depends on User Story 1 (Phase 3); adds reserved swarm
  controls and views on top of a working mux.
- **User Story 3 (Phase 5 – P3)**: Depends on User Story 1 (Phase 3); may proceed in
  parallel with User Story 2 once basic attach/forward is stable.
- **Polish (Phase 6)**: Depends on all desired user-story phases being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Baseline for all other phases (attachment lifecycle, forwarding,
  detach, close).
- **User Story 2 (P2)**: Builds on User Story 1’s mux implementation and runtime daemon
  views.
- **User Story 3 (P3)**: Builds on User Story 1 and adapter integration, focusing on
  robustness and real-path scenarios.

### Within Each User Story

- Write or extend tests before completing implementation tasks where practical, especially
  for error handling and concurrency-sensitive behaviors.
- Implement core mux behavior before adding integration/adapters.
- Validate each story’s independent test criteria from `specs/009-swarm-acp-mux/spec.md`
  §16 and `specs/009-swarm-acp-mux/quickstart.md` before moving to the next phase.

### Parallel Opportunities

- All tasks marked `[P]` can be worked on in parallel once their phase prerequisites are
  satisfied (for example, unit tests in parallel with adapter scaffolding).
- After Phase 3 (User Story 1) is stable, User Story 2 and User Story 3 tasks can proceed
  concurrently by different contributors.
- Polish/documentation tasks in Phase 6 can largely run in parallel once code and tests
  stabilize.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003).
2. Complete Phase 2: Foundational (T004–T007).
3. Complete Phase 3: User Story 1 (T008–T016).
4. **STOP and VALIDATE**: Run the attachment and forwarding unit tests and any early
   integration tests; confirm invariants from `specs/009-swarm-acp-mux/spec.md` §15 hold in
   practice.
5. Decide whether to proceed to User Story 2 and User Story 3 based on findings.

### Incremental Delivery

1. Setup + Foundational → `SwarmACPMux` skeleton wired into the runtime.
2. Add User Story 1 → Attachment and forwarding MVP.
3. Add User Story 2 → Reserved swarm controls and views wired to runtime APIs.
4. Add User Story 3 → Failure propagation and macro integration through the full ACP
   stack.
5. Finalize Polish phase → Docs, checklists, and quickstart kept in sync.

### Parallel Team Strategy

- One contributor focuses on mux internals and unit tests (Phase 2 + User Story 1 tasks in
  `src/nate_ntm/runtime/swarm_acp_mux.py` and `tests/unit/runtime/`).
- Another owns Swarm ACP server adapter and real-path integration tests (User Story 2+3
  tasks in `src/nate_ntm/runtime/*` and `tests/integration/acp/`).
- A third maintains documentation, contracts, and checklist alignment (Phase 6 tasks under
  `specs/009-swarm-acp-mux/`).

---

## Notes

- `[P]` tasks: independent files or concerns that can safely be implemented in parallel.
- `[US1]`, `[US2]`, `[US3]` labels: trace tasks back to the attachment/forwarding, reserved
  controls, and failure/integration phases described in spec and quickstart.
- Keep tasks small and verifiable; prefer more, narrower tasks over large, vague ones.
- Ensure tests for concurrency and failure handling are robust and deterministic, leaning
  on fake components for unit tests and real infrastructure for at least one macro
  integration test.
