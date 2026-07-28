# Tasks: Agent Mail Ownership Revamp

## Format

`- [ ] T### [P?] [US#?] Action with exact file path`

- `[P]` means the task can run in parallel with adjacent incomplete tasks.
- `[US#]` identifies the user story served by the task.
- Setup and genuinely shared foundational tasks omit the story marker.

## Setup

- [ ] T001 Review `specs/001-swarm-runtime-orchestrator/spec.md`, `specs/001-swarm-runtime-orchestrator/data-model.md`, `specs/001-swarm-runtime-orchestrator/tasks.md`, and `specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md`; record every statement that makes nate-ntm an Agent Mail client or equates one repository with one Agent Mail project in `specs/014-agent-mail-revamp/research.md`.
- [ ] T002 Document the required upstream virtual-project contract and the current nate-oha launch/configuration contract in `specs/014-agent-mail-revamp/contracts.md`, including the exact public inputs and outputs and an explicit prohibition on returning Agent Mail secrets to nate-ntm.

## Foundational Work

- [ ] T003 Add `swarm_instance_id` and `agent_mail_project_key` to `SwarmMetadata`, add `requested_agent_mail_identity` to `AgentMetadata`, and remove runtime-owned Agent Mail credential fields in `src/nate_ntm/runtime/metadata_store.py`.
- [ ] T004 Add validation in `src/nate_ntm/runtime/metadata_store.py` requiring a unique non-empty swarm instance ID, a virtual project key derived from that instance, and a stable requested Agent Mail identity for every Agent Mail-enabled agent.
- [ ] T005 [P] Add public transient Agent Mail status fields to `AgentRuntimeState` in `src/nate_ntm/runtime/state.py`: resolved name, integration status, unread state, mailbox cursor, and last public error.
- [ ] T006 [P] Define nate-oha-originated integration event types and safe payload schemas in `src/nate_ntm/runtime/events.py` for identity resolution, mailbox changes, integration failure, and recovery.
- [ ] T007 Extend the managed-agent launch configuration in `src/nate_ntm/runtime/agents.py` to carry the virtual Agent Mail project key and requested identity into nate-oha configuration without reading or storing transport or registration secrets.
- [ ] T008 Remove `src/nate_ntm/runtime/agent_mail_client.py` and remove all `BaseAgentMailClient` and `FakeAgentMailClient` imports, fields, constructors, and helpers from `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, and the test suite.

## User Story 1 — Create an isolated swarm coordination namespace

**Independent checkpoint**:

Creating two swarms from the same project directory yields different swarm instance IDs, virtual Agent Mail project keys, and per-agent launch configurations without contacting Agent Mail.

### Tests

- [ ] T009 [US1] Add a macro create-twice test in `tests/integration/agent_mail_revamp/test_isolated_swarm_creation.py` that creates two swarms for one repository and verifies distinct `swarm_instance_id` and `agent_mail_project_key` values.
- [ ] T010 [P] [US1] Add a metadata secrecy assertion in `tests/integration/agent_mail_revamp/test_isolated_swarm_creation.py` that recursively inspects persisted files and rejects Agent Mail bearer tokens, registration tokens, and legacy credential fields.

### Implementation

- [ ] T011 [US1] Generate a new durable `swarm_instance_id` during create mode and derive `agent_mail_project_key = "nate-ntm:<swarm_instance_id>"` in `src/nate_ntm/runtime/daemon.py`.
- [ ] T012 [US1] Generate and persist stable requested Agent Mail identities for new agents in `src/nate_ntm/runtime/daemon.py` without registering them or synthesizing fake Agent Mail identities.
- [ ] T013 [US1] Pass the swarm project key and requested identity into each constructed nate-oha launch configuration in `src/nate_ntm/runtime/agents.py` and `src/nate_ntm/runtime/daemon.py`.

## User Story 2 — Resume the same swarm identity

**Independent checkpoint**:

A resumed swarm recreates the same public nate-oha launch inputs for every agent and does not require nate-ntm to call Agent Mail or recover Agent Mail secrets.

### Tests

- [ ] T014 [US2] Add a macro create-stop-resume test in `tests/integration/agent_mail_revamp/test_swarm_resume_identity.py` that verifies reuse of swarm instance ID, virtual project key, requested identities, workspaces, branches when present, and conversation IDs.
- [ ] T015 [P] [US2] Add corrupted-metadata cases in `tests/integration/agent_mail_revamp/test_swarm_resume_identity.py` for missing virtual project key, duplicate requested identities, and legacy credential-bearing metadata.

### Implementation

- [ ] T016 [US2] Update resume-mode validation and reconstruction in `src/nate_ntm/runtime/daemon.py` to reuse persisted public identity inputs and reject incomplete or credential-bearing Agent Mail metadata.
- [ ] T017 [US2] Ensure resumed nate-oha launch configuration is reconstructed exclusively from swarm metadata and normal nate-oha configuration references in `src/nate_ntm/runtime/agents.py`.

## User Story 3 — Observe mailbox state without direct Agent Mail access

**Independent checkpoint**:

Agent-originated identity and mailbox events update runtime state, APIs, event streams, and scheduler decisions without any mcp_agent_mail client in nate-ntm.

### Tests

- [ ] T018 [US3] Add a macro event-flow test in `tests/integration/agent_mail_revamp/test_nate_oha_mail_events.py` that feeds identity-resolved, mailbox-changed, failure, and recovery events through the control adapter and verifies `swarm.get_overview`, `agent.get_detail`, and live event publication.
- [ ] T019 [US3] Add a scheduler test in `tests/integration/agent_mail_revamp/test_mailbox_wake_scheduling.py` that verifies a new mailbox cursor wakes an eligible idle agent exactly once and duplicate cursors do not create duplicate turns.
- [ ] T020 [P] [US3] Add a repository-level assertion in `tests/integration/agent_mail_revamp/test_no_runtime_agent_mail_client.py` that nate-ntm has no runtime import or invocation path for mcp_agent_mail and no replacement fake Agent Mail adapter.

### Implementation

- [ ] T021 [US3] Extend the ACP/control adapter in `src/nate_ntm/runtime/acp_client.py` to translate nate-oha public integration notifications into typed `AgentEvent` values.
- [ ] T022 [US3] Apply Agent Mail identity, mailbox, failure, and recovery events to `AgentRuntimeState` and per-agent event streams in `src/nate_ntm/runtime/scheduler.py`.
- [ ] T023 [US3] Replace inbox polling with mailbox-event deduplication and eligibility checks in `src/nate_ntm/runtime/scheduler.py`.
- [ ] T024 [US3] Update `swarm.get_overview` and `agent.get_detail` response shaping in `src/nate_ntm/api/server.py` and `src/nate_ntm/runtime/daemon.py` to expose only public Agent Mail state.

## User Story 4 — Launch nate-oha with one explicit Agent Mail owner

**Independent checkpoint**:

A managed nate-oha process receives the virtual project key and requested identity, reports its resolved public identity, and retains all Agent Mail credentials outside nate-ntm.

### Tests

- [ ] T025 [US4] Add a macro launch-boundary test in `tests/integration/agent_mail_revamp/test_nate_oha_launch_contract.py` using a real nate-oha configuration builder or subprocess fixture to verify virtual project and requested identity propagation.
- [ ] T026 [US4] Extend `tests/integration/agent_mail_revamp/test_nate_oha_launch_contract.py` to verify that registration tokens and transport bearer tokens never appear in nate-ntm state, events, API responses, logs, or persisted metadata.

### Implementation

- [ ] T027 [US4] Implement the agreed nate-oha launch mapping in `src/nate_ntm/runtime/agents.py`, using nate-oha’s existing Agent Mail feature configuration rather than introducing a nate-ntm-specific facade or client.
- [ ] T028 [US4] Implement the agreed public identity and mailbox event subscription in `src/nate_ntm/runtime/acp_client.py` and route it through the existing runtime event pipeline.
- [ ] T029 [US4] Add clear startup failure reporting in `src/nate_ntm/runtime/agents.py` and `src/nate_ntm/runtime/scheduler.py` when nate-oha reports that its Agent Mail integration could not initialize, without attempting fallback registration in nate-ntm.

## Final Integration

- [ ] T030 Update Feature 001 requirements, data model, tasks, quickstart, and runtime API language in `specs/001-swarm-runtime-orchestrator/` so they no longer state that nate-ntm creates projects, registers identities, stores Agent Mail credentials, or polls inboxes.
- [ ] T031 [P] Update `README.md` and relevant architecture notes to distinguish repository identity, workspace identity, swarm name, swarm instance ID, virtual Agent Mail project key, requested identity, and resolved Agent Mail name.
- [ ] T032 Run `uv run pytest` and the focused macro scenarios under `tests/integration/agent_mail_revamp/`; fix only failures caused by this epic and record any blocked upstream dependency in `specs/014-agent-mail-revamp/research.md`.
- [ ] T033 Verify the final diff contains no compatibility adapter, duplicate Agent Mail implementation, secret persistence, or path-derived swarm project identity.

## Dependencies and Execution Order

1. T001–T002 establish the corrected contracts.
2. T003–T008 replace the foundational data and ownership model and block all user stories.
3. US1 must complete before US2 because resume depends on the new persisted identity model.
4. US3 may proceed after T005–T008 and can run in parallel with US2.
5. US4 depends on the external nate-oha/control-channel contract captured by T002 and on the launch metadata from US1.
6. T030–T033 run after all selected user stories are complete.
7. The upstream virtual-project capability may block T025–T029 final integration, but it must not justify restoring runtime-owned Agent Mail behavior.
