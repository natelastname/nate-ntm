# Tasks: Swarm Identity, Storage, and CLI Cleanup

## Format

`- [ ] T### [P?] [US#?] Action with exact file path`

- `[P]` means the task can run in parallel with adjacent incomplete tasks.
- `[US#]` identifies the user story served by the task.
- Setup and genuinely shared foundational tasks omit the story marker.

## Setup

- [ ] T001 Inspect the current `013-cli-refactor` branch and adjacent editable `../nate-oha` checkout, then confirm the exact existing tests that cover `src/nate_ntm/runtime/metadata_store.py`, `src/nate_ntm/cli.py`, `src/nate_ntm/runtime/daemon.py`, and `../nate-oha/src/nate_oha/config.py`; update task file paths only if the checked-out repository differs from this plan.

## Foundational Work

- [ ] T002 Change `AgentMailFeatureConfig.project` from `Path | None` to `str | None` in `../nate-oha/src/nate_oha/config.py`, remove path-oriented wording and imports made unused by the change, and add string validation/JSON round-trip coverage in `../nate-oha/tests/test_agent_mail_config.py` without accepting both types.
- [ ] T003 Refactor `src/nate_ntm/runtime/metadata_store.py` so `MetadataStore` binds directly to a validated `swarm_id`, derives `~/.nate-ntm/swarms/<swarm-id>/swarm.json`, retains the existing atomic writer, and validates the embedded swarm ID without requiring an external project path.
- [ ] T004 Add one canonical swarm-ID validation function in `src/nate_ntm/runtime/metadata_store.py` or `src/nate_ntm/runtime/swarm_state.py` that preserves valid explicit IDs exactly and rejects empty IDs, separators, `.`/`..`, and path escape attempts; reuse it from every create/load entry point.
- [ ] T005 Simplify `RuntimeConfig` and `load_runtime_config()` in `src/nate_ntm/config/runtime_config.py` by removing `metadata_dir`, generated/default swarm-ID behavior, Agent Mail construction fields, and their obsolete environment loading while retaining only settings needed to run an already materialized swarm.
- [ ] T006 Update `src/nate_ntm/runtime/swarm_state.py` invariants so centrally loaded state treats persisted `project_path` as authoritative and validates any shared Agent Mail project/URL assumptions needed by resume.

## User Story 1 — Create and persist an independently addressable swarm

**Independent checkpoint**: Creating two swarms for one project produces two independently loadable files under `~/.nate-ntm/swarms/`, and no project-local `.nate_ntm/` directory.

### Tests

- [ ] T007 [US1] Replace project-local persistence expectations in `tests/unit/runtime/test_metadata_store.py` with real-store tests that generate a UUID4-hex ID, operate only on `~/.nate-ntm/swarms/<owned-id>/`, verify atomic round-trip and collision safety, and remove only that exact directory in fixture teardown.
- [ ] T008 [US1] Add a CLI macro test in `tests/integration/quickstart/test_swarm_create.py` that changes into a temporary project, omits `--project` and `--swarm-id`, captures the generated ID, loads the resulting centralized state, verifies the resolved working directory, and asserts `<project>/.nate_ntm` was not created.
- [ ] T009 [P] [US1] Add a second CLI macro test in `tests/integration/quickstart/test_swarm_create.py` that creates two swarms for the same explicit project and verifies distinct IDs, distinct storage directories, and independent persisted state.

### Implementation

- [ ] T010 [US1] Refactor `swarm_create()` in `src/nate_ntm/cli.py` so `--project` is optional with a working-directory default, `--swarm-id` defaults to one generated `uuid4().hex`, IDs are validated once, dry-run does not create storage, and successful creation reports the effective swarm ID and canonical metadata path.
- [ ] T011 [US1] Rewire all creation persistence in `src/nate_ntm/cli.py` and callers to use `MetadataStore(swarm_id)` and remove reads or writes of project-local `.nate_ntm/` metadata.
- [ ] T012 [US1] Preserve exact-ID collision behavior and constrain `--force` to replacement of only `~/.nate-ntm/swarms/<validated-id>/swarm.json` in `src/nate_ntm/cli.py` and `src/nate_ntm/runtime/metadata_store.py`.

## User Story 2 — Materialize explicit Agent Mail configuration

**Independent checkpoint**: Agent Mail dry-run and persisted output use string project IDs, default exactly to the swarm ID, honor explicit project/URL overrides, and reject unused Agent Mail options.

### Tests

- [ ] T013 [US2] Update `tests/test_swarm_constructors.py` to assert string Agent Mail project IDs, default equality with `swarm_id`, explicit `--agent-mail-project-id` and `--agent-mail-url` overrides, ordered constructor metadata, and absence of source-object mutation.
- [ ] T014 [US2] Add CLI validation cases in `tests/integration/quickstart/test_swarm_create.py` proving `--agent-mail-project-id` and `--agent-mail-url` fail without `--constructor agent-mail` and that no swarm directory is created on failure.

### Implementation

- [ ] T015 [US2] Introduce immutable `ConstructionContext` and update the canonical constructor callable/application path in `src/nate_ntm/swarm_constructors.py` so every constructor receives `(SwarmState, ConstructionContext)`.
- [ ] T016 [US2] Refactor `agent_mail_constructor()` in `src/nate_ntm/swarm_constructors.py` to use `context.agent_mail_project_id or swarm.swarm_id`, use the explicit context URL, assign/compare plain strings, and remove every Agent Mail construction environment lookup and `Path` normalization.
- [ ] T017 [US2] Add `--agent-mail-project-id` and `--agent-mail-url` to `swarm_create()` in `src/nate_ntm/cli.py`, validate that they are used only with the `agent-mail` constructor, and pass one `ConstructionContext` into `apply_constructors()`.
- [ ] T018 [P] [US2] Remove the five obsolete Agent Mail construction aliases from `src/nate_ntm/config/runtime_config.py`, `src/nate_ntm/runtime/agent_mail_client.py`, tests, and documentation: `NATE_NTM_AGENT_MAIL_PROJECT`, `AGENT_MAIL_PROJECT`, `NATE_NTM_AGENT_MAIL_URL`, `AGENT_MAIL_UPSTREAM_URL`, and `AGENT_MAIL_URL`.

## User Story 3 — Start an existing swarm by ID only

**Independent checkpoint**: `runtime start --swarm-id <id>` loads centralized state, recovers the stored project path and materialized Agent Mail values, and delegates to the long-lived runtime with no creation mode or project lookup.

### Tests

- [ ] T019 [US3] Rewrite `tests/unit/cli/test_cli_runtime_start.py` around the resume-only CLI: persist a uniquely named real swarm, invoke `runtime start --swarm-id`, mock only the long-lived runner, assert recovered project/runtime configuration, and assert `--project`, `--mode`, and `--agents` are no longer accepted.
- [ ] T020 [US3] Update `tests/integration/quickstart/test_resume_swarm_us2.py` to create through `swarm create`, resume by swarm ID only, verify the persisted project path and agent configurations are reused unchanged, and clean the exact swarm directory.
- [ ] T021 [P] [US3] Update `tests/unit/runtime/test_agent_mail_client.py` to construct `McpAgentMailClient` from explicit persisted project ID/URL inputs and verify there is no project-path or removed-environment fallback.

### Implementation

- [ ] T022 [US3] Remove `RuntimeDaemon.create()` and create-mode precondition logic from `src/nate_ntm/runtime/daemon.py`; keep one resume constructor that receives centrally loaded `SwarmState` and runtime-only configuration/adapters.
- [ ] T023 [US3] Remove `StartupMode.CREATE`, the create branch, and `agent_count` plumbing from `src/nate_ntm/runtime/runner.py`, `src/nate_ntm/runtime/daemon.py`, and their callers so the runner starts only existing materialized swarms.
- [ ] T024 [US3] Refactor `runtime_start()` in `src/nate_ntm/cli.py` to require `--swarm-id`, load `SwarmState` before runtime configuration assembly, recover `project_path` from persisted state, and delete `--project`, `--mode`, and `--agents` from this command.
- [ ] T025 [US3] Refactor adapter assembly in `src/nate_ntm/runtime/adapters.py` and `src/nate_ntm/runtime/agent_mail_client.py` so Agent Mail receives explicit persisted project ID and URL values and never derives a project from the local path or removed construction environment aliases.
- [ ] T026 [US3] Update `src/nate_ntm/runtime/nate_oha_launch.py` and runtime launch callers to consume complete persisted per-agent `NateOHAConfig` values rather than rebuilding Agent Mail construction fields during resume.

## Final Integration

- [ ] T027 Update `README.md` with the single canonical lifecycle: create from the working directory, central storage under `~/.nate-ntm/swarms/<swarm-id>/`, Agent Mail defaults/overrides, and `runtime start --swarm-id` resume.
- [ ] T028 Update `specs/013-cli-refactor/quickstart.md` only if implementation details changed from the acceptance procedure, keeping it executable and free of obsolete compatibility commands.
- [ ] T029 Run the focused nate-ntm tests for creation, constructors, metadata, runtime start, resume, and Agent Mail, then run the complete default suite with `uv run pytest`; do not gate or exclude tests from the default command.
- [ ] T030 Run the adjacent nate-oha tests covering `AgentMailFeatureConfig` and its complete default suite from `../nate-oha`, fixing only failures caused by the coordinated string-model change.
- [ ] T031 Perform the manual flow in `specs/013-cli-refactor/quickstart.md`, record the generated test swarm IDs, verify their exact central files and resume behavior, and remove only those exact test swarm directories afterward.

## Dependencies and Execution Order

```text
T001
 ├─ T002
 ├─ T003 ─ T004
 ├─ T005
 └─ T006

US1: T003–T006 → T007–T012
US2: T002, T004, T010 → T013–T018
US3: T003, T005–T006, T016–T018 → T019–T026

T027–T031 follow all three user stories.
```

- T002 may proceed in parallel with nate-ntm foundational work.
- T009, T018, and T021 are marked parallel because they touch distinct files after their stated prerequisites.
- Runtime creation removal must not begin before the canonical `swarm create` and centralized store path are viable.
- Final validation is complete only when both nate-ntm and the coordinated nate-oha test suites pass.
