# Implementation Plan: Swarm Identity, Storage, and CLI Cleanup

## Summary

Replace project-local swarm state and duplicated runtime creation with one canonical lifecycle:

1. `nate-ntm swarm create` materializes a complete swarm, generates or accepts its ID, applies constructors, and atomically persists it at `~/.nate-ntm/swarms/<swarm-id>/swarm.json`.
2. `nate-ntm runtime start --swarm-id <id>` loads that materialized state, recovers its project path and Agent Mail configuration, and starts the runtime.
3. Agent Mail construction inputs are explicit CLI values, project IDs are logical strings, and the default Agent Mail project ID is the swarm ID.

The implementation removes project-local metadata, environment aliases for Agent Mail construction, `runtime start --mode=create`, and the second swarm-creation implementation in `RuntimeDaemon.create()`.

## User Stories

### US1 — Create and persist an independently addressable swarm

**Priority**: P1

A user can run `swarm create` from the working directory or with `--project`, receive a generated UUID4-hex swarm ID unless one is supplied, and find the complete state under the canonical central store.

**Independent checkpoint**: A CLI test creates two swarms for one project, loads each by ID, verifies independent state, and confirms no project-local `.nate_ntm/` directory exists.

### US2 — Materialize explicit Agent Mail configuration

**Priority**: P1

A user selecting `--constructor agent-mail` gets one logical Agent Mail project ID shared by all agents, defaulting exactly to the swarm ID, with an explicit CLI override and URL override when needed.

**Independent checkpoint**: Dry-run and persisted output show string project IDs, complete per-agent configurations, the default derived value, and explicit override behavior; constructor-only options fail when the constructor is absent.

### US3 — Start an existing swarm by ID only

**Priority**: P1

A user starts a previously materialized swarm with `runtime start --swarm-id <id>`. The runtime loads the stored project and effective Agent Mail configuration without a project lookup argument or creation mode.

**Independent checkpoint**: A runtime-start CLI test loads a real centrally persisted swarm by ID, recovers its project path, and delegates to the long-lived runner with no creation branch.

## Technical Context

- Python 3.13, Typer, Pydantic v2, pytest.
- Canonical persisted model: `src/nate_ntm/runtime/swarm_state.py`.
- Existing atomic writer: `src/nate_ntm/runtime/metadata_store.py`.
- CLI entry points: `src/nate_ntm/cli.py`.
- Runtime lifecycle: `src/nate_ntm/runtime/daemon.py` and `src/nate_ntm/runtime/runner.py`.
- Agent Mail runtime adapter: `src/nate_ntm/runtime/agent_mail_client.py`.
- Constructor pipeline: `src/nate_ntm/swarm_constructors.py`.
- Adjacent editable dependency: `../nate-oha/src/nate_oha/config.py`.

Tests that touch persistence use unique UUID4-hex IDs under the real `~/.nate-ntm/swarms/` hierarchy and remove only the exact directories they own.

## Architecture and Approach

### One storage adapter

Refactor `MetadataStore` to bind directly to a validated `swarm_id`:

```python
MetadataStore(swarm_id: str)
```

It computes:

```text
~/.nate-ntm/swarms/<swarm-id>/swarm.json
```

The store validates only that the embedded `SwarmState.swarm_id` matches its bound ID. The persisted `project_path` is authoritative and is not supplied externally during load.

Keep `_atomic_write_json()` unchanged except for any naming/documentation cleanup required by the new location.

### One creation path

`swarm create` owns all materialization:

- resolve `project` from the explicit option or `Path.cwd()`;
- resolve `swarm_id` from the explicit option or `uuid4().hex`;
- validate the ID as one safe path component;
- read complete agent configurations;
- apply constructors with an immutable `ConstructionContext`;
- dry-run without creating storage, or atomically persist through `MetadataStore`.

Delete runtime creation semantics rather than adapting them:

- remove `RuntimeDaemon.create()`;
- remove `StartupMode.CREATE` if it has no remaining consumer;
- remove the create branch and `agent_count` plumbing in `runtime/runner.py`;
- remove `runtime start --mode=create` and `--agents`.

### Explicit constructor context

Use one context object in `src/nate_ntm/swarm_constructors.py`:

```python
@dataclass(frozen=True, slots=True)
class ConstructionContext:
    agent_mail_project_id: str | None = None
    agent_mail_url: str = "http://127.0.0.1:8765"
```

All constructors receive `(swarm, context)`. The Agent Mail constructor uses `context.agent_mail_project_id or swarm.swarm_id`, never environment variables.

### Load before runtime assembly

`runtime start` first loads `SwarmState` through `MetadataStore(swarm_id)`. It then creates runtime-only configuration from the persisted `project_path` and `swarm_id`, plus runtime endpoint/executable overrides.

Runtime adapters are assembled from materialized state. The Agent Mail adapter receives an explicit project ID and URL derived from persisted swarm/agent configuration; it does not fall back to environment aliases or the local project path.

### String Agent Mail project IDs

Change `AgentMailFeatureConfig.project` in `../nate-oha/src/nate_oha/config.py` from `Path | None` to `str | None`. Nate-ntm then assigns and compares project IDs directly as strings. No dual-type validator is added.

## Repository Changes

### nate-ntm

- `src/nate_ntm/runtime/metadata_store.py`: central path derivation, swarm-ID binding, atomic load/save.
- `src/nate_ntm/config/runtime_config.py`: remove metadata and construction-only fields; retain runtime-only settings.
- `src/nate_ntm/runtime/swarm_state.py`: strengthen persisted invariants only where needed for centralized loading and shared Agent Mail values.
- `src/nate_ntm/swarm_constructors.py`: typed context, CLI-driven Agent Mail values, string project IDs.
- `src/nate_ntm/cli.py`: optional creation project, generated IDs, Agent Mail options, resume-by-ID-only interface.
- `src/nate_ntm/runtime/daemon.py`: resume-only daemon construction; remove duplicated materialization.
- `src/nate_ntm/runtime/runner.py`: remove create/agent-count branch and accept already resolved resume configuration/state.
- `src/nate_ntm/runtime/adapters.py`: construct runtime integrations from explicit materialized values.
- `src/nate_ntm/runtime/agent_mail_client.py`: remove construction URL aliases and project-path fallback.
- `src/nate_ntm/runtime/nate_oha_launch.py`: consume complete persisted per-agent configuration without rebuilding construction values.
- `tests/`: replace project-local and runtime-create expectations with macro-level central-store/create/resume flows.
- `README.md`: document the canonical create and start commands and central storage path.

### nate-oha

- `../nate-oha/src/nate_oha/config.py`: change Agent Mail project type and wording to logical string ID.
- `../nate-oha/tests/test_agent_mail_config.py`: add focused validation/round-trip coverage for the string project field.

## Data Model

`SwarmState` remains the single persisted object graph. Its important fields are:

- `swarm_id: str` — storage and lookup key;
- `project_path: Path` — persisted execution workspace;
- `agent_mail_project_id: str` — shared logical Agent Mail namespace when configured;
- `agents: dict[str, AgentState]` — complete materialized per-agent configurations;
- `runtime_options["constructors"]` — ordered constructor declarations already applied.

No registry database, project index, migration record, compatibility envelope, or second persisted model is introduced.

## Interfaces and Contracts

### Create

```text
nate-ntm swarm create
  [--project PATH]
  [--swarm-id ID]
  --agent FILE...
  [--constructor NAME]...
  [--agent-mail-project-id ID]
  [--agent-mail-url URL]
  [--dry-run]
  [--force]
```

- `--project` defaults to the resolved working directory.
- `--swarm-id` defaults to `uuid4().hex`.
- Agent Mail-only options require `--constructor agent-mail`.
- Dry-run produces a complete materialized object but no directory.

### Start

```text
nate-ntm runtime start --swarm-id ID [runtime-only options]
```

There is no project-based lookup, mode selector, or agent-count creation option.

### Storage

```text
~/.nate-ntm/swarms/<swarm-id>/swarm.json
```

Explicit IDs are preserved exactly after validation and rejected if unsafe as a single path component.

## Validation Strategy

Use a few complete-flow tests:

1. Create from the working directory, persist centrally, load by generated ID, and clean the exact created directory.
2. Create two swarms for the same project and verify independent state.
3. Verify explicit ID collision failure leaves existing JSON unchanged.
4. Verify Agent Mail defaults to the swarm ID and explicit project/URL overrides win.
5. Verify constructor-only options fail without `agent-mail`.
6. Start by swarm ID, recover the persisted project, and ensure no create path remains.
7. Verify no project-local `.nate_ntm/` directory is created.
8. Validate nate-oha string project round trips.
9. Run `uv run pytest` in nate-ntm and the adjacent nate-oha suite affected by the model change.

Persistence fixtures must generate UUID4-hex IDs and remove only `~/.nate-ntm/swarms/<owned-id>/` during teardown.

## Risks and Tradeoffs

- Removing runtime create mode is intentionally breaking, but eliminates the largest duplication and establishes one materialization path.
- Real-home tests can leave isolated UUID directories if the process is killed; exact teardown and negligible collision risk make this acceptable.
- Runtime Agent Mail initialization must choose its URL from persisted agent configuration consistently. Conflicting URLs should fail validation rather than select arbitrarily.
- Coordinated nate-oha changes must land with nate-ntm because the editable dependency is part of the effective workspace.
- `--force` must never overwrite an unrelated swarm accidentally; it applies only to the exact validated ID selected by the user.

## Explicit Non-Goals

- Migrating or reading existing project-local `.nate_ntm/` state.
- Looking up swarms by project path, display name, recency, or fuzzy search.
- Supporting alternate state roots or test-only stores.
- Maintaining runtime create mode or Agent Mail environment aliases.
- Introducing a database, registry daemon, compatibility layer, or constructor configuration language.
- Changing Agent Mail protocol semantics, credentials storage, or unrelated runtime endpoint options.
