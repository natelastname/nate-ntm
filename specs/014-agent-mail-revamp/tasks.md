# Tasks: Agent Mail Ownership Revamp

## Format

`- [ ] T### [P?] [US#?] Action with exact file path`

- `[P]` means the task can run in parallel with adjacent incomplete tasks.
- `[US#]` identifies the user story served by the task.
- Setup and genuinely shared foundational tasks omit the story marker.

## Setup

- [ ] T001 Review `specs/001-swarm-runtime-orchestrator/spec.md`, `specs/001-swarm-runtime-orchestrator/data-model.md`, `specs/001-swarm-runtime-orchestrator/tasks.md`, and `specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md`; record every statement that makes nate-ntm an Agent Mail client or equates one repository with one Agent Mail project in `specs/014-agent-mail-revamp/research.md`.
- [ ] T002 Document the required upstream virtual-project contract and the current nate-oha launch/configuration contract in `specs/014-agent-mail-revamp/contracts.md`, including exact public inputs and an explicit prohibition on returning Agent Mail secrets to nate-ntm.

## Foundational Work

- [ ] T003 Add `swarm_instance_id` and `agent_mail_project_key` to `SwarmMetadata`, add optional `requested_agent_mail_identity` to `AgentMetadata`, and remove runtime-owned Agent Mail credential and unread-mail fields in `src/nate_ntm/runtime/metadata_store.py`.
- [ ] T004 Add validation in `src/nate_ntm/runtime/metadata_store.py` requiring a non-empty unique swarm instance ID, a matching virtual project key, and a stable requested identity for every Agent Mail-enabled agent.
- [ ] T005 Extend the managed-agent launch configuration in `src/nate_ntm/runtime/agents.py` to carry the virtual Agent Mail project key and requested identity into nate-oha configuration without reading or storing transport or registration secrets.
- [ ] T006 Remove `src/nate_ntm/runtime/agent_mail_client.py` and remove all `BaseAgentMailClient` and `FakeAgentMailClient` imports, fields, constructors, unread-mail helpers, and polling paths from `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, and the test suite.
- [ ] T007 [P] Remove fake Agent Mail runtime state and API shaping from `src/nate_ntm/runtime/state.py`, `src/nate_ntm/runtime/events.py`, `src/nate_ntm/runtime/daemon.py`, and `src/nate_ntm/api/server.py` where those fields exist only to support the deleted runtime-owned integration.

## User Story 1 — Create an isolated swarm coordination namespace

**Independent checkpoint**:

Creating two swarms from the same project directory yields different swarm instance IDs, virtual Agent Mail project keys, and per-agent launch configurations without contacting Agent Mail.

### Tests

- [ ] T008 [US1] Add a macro create-twice test in `tests/integration/agent_mail_revamp/test_isolated_swarm_creation.py` that creates two swarms for one repository and verifies distinct `swarm_instance_id` and `agent_mail_project_key` values.
- [ ] T009 [P] [US1] Add metadata assertions in `tests/integration/agent_mail_revamp/test_isolated_swarm_creation.py` that reject Agent Mail bearer tokens, registration tokens, unread-mail state, fake identities, and legacy credential fields.
- [ ] T010 [P] [US1] Add an Agent Mail-disabled case in `tests/integration/agent_mail_revamp/test_isolated_swarm_creation.py` proving that agents can be created without synthetic Agent Mail metadata.

### Implementation

- [ ] T011 [US1] Generate a new durable `swarm_instance_id` during create mode and derive `agent_mail_project_key = "nate-ntm:<swarm_instance_id>"` in `src/nate_ntm/runtime/daemon.py`.
- [ ] T012 [US1] Generate and persist stable requested Agent Mail identities for Agent Mail-enabled agents in `src/nate_ntm/runtime/daemon.py` without registering them or synthesizing fake Agent Mail identities.
- [ ] T013 [US1] Pass the swarm project key and requested identity into each constructed nate-oha launch configuration in `src/nate_ntm/runtime/agents.py` and `src/nate_ntm/runtime/daemon.py`.

## User Story 2 — Resume the same swarm identity

**Independent checkpoint**:

A resumed swarm recreates the same public nate-oha launch inputs for every agent and does not require nate-ntm to call Agent Mail or recover Agent Mail secrets.

### Tests

- [ ] T014 [US2] Add a macro create-stop-resume test in `tests/integration/agent_mail_revamp/test_swarm_resume_identity.py` that verifies reuse of swarm instance ID, virtual project key, requested identities, workspaces, branches when present, and conversation IDs.
- [ ] T015 [P] [US2] Add corrupted-metadata cases in `tests/integration/agent_mail_revamp/test_swarm_resume_identity.py` for missing or mismatched virtual project keys, duplicate requested identities, unread-mail state, and legacy credential-bearing metadata.

### Implementation

- [ ] T016 [US2] Update resume-mode validation and reconstruction in `src/nate_ntm/runtime/daemon.py` to reuse persisted public identity inputs and reject incomplete or credential-bearing Agent Mail metadata.
- [ ] T017 [US2] Ensure resumed nate-oha launch configuration is reconstructed exclusively from swarm metadata and ordinary nate-oha configuration references in `src/nate_ntm/runtime/agents.py`.

## User Story 3 — Launch nate-oha as the sole Agent Mail owner

**Independent checkpoint**:

A managed nate-oha process receives the virtual project key and requested identity while all Agent Mail registration, credentials, inbox access, and facade behavior remain inside nate-oha.

### Tests

- [ ] T018 [US3] Add a macro launch-boundary test in `tests/integration/agent_mail_revamp/test_nate_oha_launch_contract.py` using the real nate-oha configuration builder or subprocess fixture to verify virtual project and requested identity propagation.
- [ ] T019 [US3] Extend `tests/integration/agent_mail_revamp/test_nate_oha_launch_contract.py` to verify that registration tokens and transport bearer tokens never appear in nate-ntm state, API responses, logs, or persisted metadata.
- [ ] T020 [P] [US3] Add a repository-level assertion in `tests/integration/agent_mail_revamp/test_no_runtime_agent_mail_client.py` that nate-ntm has no runtime import or invocation path for `mcp_agent_mail` and no fake replacement adapter.

### Implementation

- [ ] T021 [US3] Implement the agreed nate-oha launch mapping in `src/nate_ntm/runtime/agents.py`, using nate-oha’s existing Agent Mail feature configuration rather than introducing a nate-ntm-specific facade or client.
- [ ] T022 [US3] Add clear startup failure reporting in `src/nate_ntm/runtime/agents.py` and `src/nate_ntm/runtime/daemon.py` when nate-oha cannot initialize its configured Agent Mail integration, without fallback registration in nate-ntm.

## Final Integration

- [ ] T023 Update Feature 001 requirements, data model, tasks, quickstart, and runtime API language in `specs/001-swarm-runtime-orchestrator/` so they no longer state that nate-ntm creates projects, registers identities, stores Agent Mail credentials, polls inboxes, or currently performs mailbox-driven scheduling.
- [ ] T024 [P] Update `README.md` and relevant architecture notes to distinguish repository identity, workspace identity, swarm name, swarm instance ID, virtual Agent Mail project key, and requested identity.
- [ ] T025 Run `uv run pytest` and the focused macro scenarios under `tests/integration/agent_mail_revamp/`; fix only failures caused by this epic and record any blocked upstream dependency in `specs/014-agent-mail-revamp/research.md`.
- [ ] T026 Verify the final diff contains no compatibility adapter, duplicate Agent Mail implementation, secret persistence, unread-mail simulation, path-derived swarm project identity, mailbox watcher, control-channel mail event, or scheduler work outside the MVP.

## Deferred Follow-Up

The architecture in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md` belongs to a later scheduler epic. That future work may introduce an embedded nate-oha mailbox monitor, public state-change notifications, deduplication, runtime mailbox state, and event-driven wake scheduling.

No task in this epic implements that path.

## Dependencies and Execution Order

1. T001–T002 establish the corrected contracts.
2. T003–T007 replace the foundational data and ownership model and block all user stories.
3. US1 must complete before US2 because resume depends on the new persisted identity model.
4. US3 depends on the launch metadata from US1 and may proceed in parallel with US2 once T005 is complete.
5. T023–T026 run after all user stories are complete.
6. The upstream virtual-project capability may block final end-to-end launch validation, but it must not justify restoring runtime-owned Agent Mail behavior.