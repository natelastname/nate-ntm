# Tasks: Swarm Constructors

**Epic**: `012-swarm-constructors`  
**Input**: `spec.md` and `research.md` in this directory  
**Goal**: Add an ordered swarm-constructor pipeline to `nate-ntm swarm create`, with automatic Agent Mail setup as the first built-in constructor.

## Execution Rules

- Complete tasks in dependency order unless marked `[P]`.
- Keep one canonical constructor path in `src/nate_ntm/swarm_constructors.py`.
- Constructors transform the complete `SwarmState`; do not add draft/materialized duplicate models.
- Let constructor, validation, external-service, and persistence errors surface normally.
- Persist effective configuration directly; secret redaction and credential indirection are out of scope.
- Prefer a few macro-level tests over isolated tests of registry entries or trivial assignments.

## Phase 1: Resolve Agent Mail Configuration Shape

- [ ] **T001** Inspect the installed adjacent `nate-oha` package using the commands in `specs/012-swarm-constructors/research.md`; record the exact `NateOHAConfig` Agent Mail field paths, required values, identity naming constraints, and whether provisioning requires external calls in a concise implementation note appended to `specs/012-swarm-constructors/research.md`.

## Phase 2: Constructor Pipeline

- [ ] **T002** Create `src/nate_ntm/swarm_constructors.py` with the single canonical constructor type, built-in constructor registry, ordered lookup/application function, and direct rejection of unknown or duplicate non-repeatable constructor names. Preserve ordinary Python/Pydantic errors rather than introducing custom result or exception types. Depends on T001.

- [ ] **T003** Implement the built-in `agent-mail` constructor in `src/nate_ntm/swarm_constructors.py`: derive or provision one shared Agent Mail project, assign a unique identity to every agent, copy each `NateOHAConfig` before modification, update only the canonical Agent Mail fields inside each copied config, set `SwarmState.agent_mail_project_id`, and reject incompatible explicit Agent Mail configuration rather than silently overwriting it. Depends on T001 and T002.

- [ ] **T004** Persist the explicitly selected constructor order under `SwarmState.runtime_options["constructors"]` from the constructor pipeline in `src/nate_ntm/swarm_constructors.py`, without adding a second top-level schema or compatibility representation. Depends on T002.

## Phase 3: Swarm Creation Integration

- [ ] **T005** Add repeatable ordered `--constructor` options to `swarm_create()` in `src/nate_ntm/cli.py` and apply the constructor pipeline after the complete initial `SwarmState` is assembled but before the existing `--dry-run` branch and `MetadataStore.save_swarm_state()` call. Do not catch constructor failures merely to rewrap or redact them. Depends on T002–T004.

- [ ] **T006** Ensure the no-constructor path in `src/nate_ntm/cli.py` remains the existing direct creation path and that runtime create/resume code does not invoke constructors. Make only the smallest changes needed to preserve this one-time materialization boundary. Depends on T005.

## Phase 4: Macro-Level Verification

- [ ] **T007** Add a CLI-level dry-run test in `tests/test_swarm_constructors.py` using two real valid `NateOHAConfig` JSON files. Invoke `swarm create --dry-run --constructor agent-mail` and assert one shared non-empty project ID, distinct per-agent identities, valid complete embedded configs, and persisted constructor order in the emitted `SwarmState`. Depends on T003 and T005.

- [ ] **T008** [P] Add a persist-and-load round-trip test in `tests/test_swarm_constructors.py` that creates a constructed swarm, reloads it through `MetadataStore.load_swarm_state()`, and verifies semantic preservation of the generated Agent Mail project, identities, complete configs, and constructor metadata. Depends on T003 and T005.

- [ ] **T009** [P] Add an ordered-composition test in `tests/test_swarm_constructors.py` using two small test constructors that append markers under `runtime_options`; assert that the final state reflects exactly the CLI-supplied order. Test the full application path rather than registry dictionary internals. Depends on T002 and T005.

- [ ] **T010** [P] Add a failure-path test in `tests/test_swarm_constructors.py` using a constructor that raises a sentinel exception; assert that the same exception escapes and `.nate_ntm/swarm.json` is not created. Do not require rollback of external Agent Mail side effects. Depends on T002 and T005.

- [ ] **T011** Run `uv run pytest tests/test_swarm_constructors.py`, then run the complete default suite with `uv run pytest`. Fix only failures caused by this epic; do not configure the default pytest command to run a subset of tests. Depends on T007–T010.

## Phase 5: User-Facing Validation

- [ ] **T012** Update the relevant usage documentation in `README.md` with one minimal `nate-ntm swarm create ... --constructor agent-mail` example and explain that constructors run only during creation, appear in `--dry-run` output, and are not rerun on resume. Depends on T005 and T011.

- [ ] **T013** Perform one manual macro validation with two agent configurations: inspect `--dry-run` output, create the swarm for real, reload or resume it, and confirm that project and identity values remain unchanged. Record the exact commands and observed result in `specs/012-swarm-constructors/validation.md`. Depends on T011 and T012.

## Dependency Summary

```text
T001
  ├── T002 ──┬── T004
  │          └── T003
  └───────────────┘
          ↓
        T005
          ↓
        T006
          ↓
  T007 T008 T009 T010
          ↓
        T011
          ↓
        T012
          ↓
        T013
```

## Completion Criteria

The epic is complete when:

1. `swarm create` accepts ordered constructor selections;
2. `agent-mail` produces one shared project and unique valid per-agent identities inside complete persisted `NateOHAConfig` values;
3. dry-run shows the fully constructed state without writing metadata;
4. persisted state reloads unchanged and resume does not rerun construction;
5. failures surface and no valid `swarm.json` is written; and
6. `uv run pytest` passes.
