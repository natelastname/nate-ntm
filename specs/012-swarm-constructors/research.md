# Research: Swarm Constructors

**Epic**: `012-swarm-constructors`  
**Date**: 2026-07-24  
**Status**: Complete for planning

## Scope

Resolve the architectural uncertainties required to add an ordered swarm-constructor pipeline to `nate-ntm`, with automatic Agent Mail configuration as the first built-in constructor.

## Executive Finding

The feature fits directly into the existing `nate-ntm swarm create` path.

`swarm_create()` already:

1. loads every complete `NateOHAConfig`;
2. builds every `AgentState`;
3. assembles one complete in-memory `SwarmState`;
4. optionally prints that state for `--dry-run`; and
5. performs one atomic persistence operation through `MetadataStore.save_swarm_state()`.

The constructor pipeline should therefore transform the complete `SwarmState` after its initial assembly and before either dry-run output or persistence. No runtime hook, second configuration representation, transaction framework, or compatibility path is needed.

## Evidence

### Observed facts

1. **Swarm creation has one clear materialization boundary.**

   `src/nate_ntm/cli.py:62-117` implements `swarm create`. It validates agent configuration files into `NateOHAConfig`, creates an `AgentState` for each agent, assembles one `SwarmState`, emits the complete state for `--dry-run`, and otherwise calls `store.save_swarm_state(swarm)` exactly once.

2. **The persisted object is already the complete effective configuration.**

   `src/nate_ntm/runtime/swarm_state.py:40-107` stores the complete per-agent `NateOHAConfig` inside each `AgentState`. The module explicitly states that Agent Mail configuration belongs inside `nate_oha_config`, not in parallel legacy fields.

3. **Swarm-wide Agent Mail state already has a canonical location.**

   `src/nate_ntm/runtime/swarm_state.py:118-153` defines `SwarmState.agent_mail_project_id` alongside the complete agent mapping and runtime options.

4. **Persistence is one atomic replacement of `swarm.json`.**

   `src/nate_ntm/runtime/metadata_store.py:58-93` writes a temporary JSON file, flushes and fsyncs it, and replaces the destination atomically. `save_swarm_state()` serializes the entire `SwarmState` object graph in one call at lines 257-263.

5. **Resume already consumes persisted effective state.**

   `MetadataStore.load_swarm_state()` parses and validates the persisted `SwarmState`; `AgentState.nate_oha_config` is described as the launch-time source of truth. Constructors therefore need only run during creation.

6. **The CLI already exposes ordered repeatable options naturally.**

   Typer uses `list[Path]` for repeated `--agent` options in `src/nate_ntm/cli.py:67-69`. A repeated `list[str]` constructor option can preserve command-line order without a new parser framework.

## Questions and Classification

| Question | Classification | Resolution |
|---|---|---|
| Where should constructors run? | Repository-answerable | In `swarm_create()`, after initial `SwarmState` assembly and before dry-run/persistence. |
| What object should a constructor transform? | Repository-answerable | The complete `SwarmState`; it already contains swarm-wide state and all complete `NateOHAConfig` objects. |
| Should constructors run at runtime startup or resume? | Product decision, already resolved | No. They run once during creation; persisted state is reused. |
| How should multiple constructors compose? | Product decision, already resolved | Sequentially in explicit CLI/configuration order. |
| How should failures be represented? | Product decision, already resolved | Let underlying constructor, validation, external-service, and persistence errors surface through existing CLI behavior. |
| Must credentials be hidden or externalized? | Product decision, already resolved | No special handling for now; explicit generated configuration may be persisted directly. |
| Is rollback of external Agent Mail side effects required? | Product decision, already resolved | No transaction or compensation framework in this epic. Failed swarm state is not saved, but external side effects may remain. |
| What exact fields must the Agent Mail constructor set in `NateOHAConfig`? | Requires experiment against installed adjacent dependency | Use model introspection and existing nate-oha defaults/examples before implementation. Research instrument below. |
| Does Agent Mail identity/project creation require external calls, or only config generation? | Requires repository/dependency experiment | Inspect nate-oha Agent Mail feature schema and integration functions. Keep constructor interface synchronous unless actual APIs require async. |

## Decisions

### D1. Constructors transform `SwarmState`

Use one canonical type:

```python
SwarmConstructor = Callable[[SwarmState], SwarmState]
```

The exact Python surface may be a protocol or function alias, but it should remain structurally this small. Do not introduce separate draft and materialized model classes; persistence status is determined by whether the object has been saved.

**Rationale**: `SwarmState` is already the complete durable object graph. A second model would duplicate schema and conversion logic.

### D2. Put the pipeline in a small dedicated module

Recommended location:

```text
src/nate_ntm/swarm_constructors.py
```

Recommended responsibilities:

- canonical name-to-constructor registry;
- ordered lookup and application;
- built-in Agent Mail constructor;
- duplicate and unknown-name rejection where needed.

The CLI should parse constructor selections and call one function. It should not contain Agent Mail mutation details.

### D3. Preserve explicit order with repeated CLI flags

Recommended initial CLI:

```bash
nate-ntm swarm create \
  --project /path/to/project \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail
```

Typer should receive:

```python
constructor: list[str] = typer.Option([], "--constructor")
```

Apply entries exactly in list order. Do not add a constructor configuration language until a constructor actually needs parameters.

### D4. Constructor declarations live in `SwarmState.runtime_options`

Store the ordered constructor names using the existing open-ended durable field rather than expanding the top-level schema prematurely:

```json
{
  "runtime_options": {
    "constructors": ["agent-mail"]
  }
}
```

**Tradeoff**: a dedicated typed field would provide stronger validation, but only one consumer currently needs this metadata. `runtime_options` avoids schema growth while preserving inspectability. Promote it to a typed field only when another feature requires structured constructor metadata.

### D5. Agent Mail constructor updates both canonical locations

The built-in constructor should:

1. establish one shared Agent Mail project identifier and assign it to `SwarmState.agent_mail_project_id`;
2. derive a unique identity for every agent;
3. copy each `NateOHAConfig` before modification rather than mutating shared input accidentally;
4. populate the Agent Mail feature/configuration fields inside each copied `NateOHAConfig`;
5. replace each affected `AgentState.nate_oha_config`;
6. reject conflicts rather than silently overwrite explicit incompatible Agent Mail values.

The constructor should not add parallel Agent Mail fields to `AgentState`.

### D6. Errors remain ordinary errors

Do not create:

- a constructor exception hierarchy;
- error redaction;
- cleanup orchestration;
- rollback journals;
- generic result wrappers.

Registry lookup may naturally raise `KeyError` or a direct `ValueError`; Pydantic validation should remain a `ValidationError`; external integration errors should remain their original errors. The CLI may continue using Typer's existing presentation behavior.

### D7. Dry-run shows constructed output

Apply constructors before the existing `dry_run` branch. This makes `--dry-run` the primary inspection and macro-test surface for constructor behavior while preserving the guarantee that no `swarm.json` is written.

## Recommended Runtime Flow

```text
read --agent files
        ↓
validate NateOHAConfig objects
        ↓
assemble complete SwarmState
        ↓
apply selected constructors in order
        ↓
validate complete SwarmState
        ↓
--dry-run: print JSON
or
persist swarm.json atomically
```

The runtime start/resume paths remain unchanged.

## Agent Mail Schema Research Instrument

The exact nate-oha Agent Mail configuration fields are supplied by the adjacent `nate-oha` dependency, not defined by `nate-ntm`. Before implementation, run this from the project environment:

```bash
uv run python - <<'PY'
from nate_oha.config import NateOHAConfig

print(NateOHAConfig.model_json_schema())

cfg = NateOHAConfig()
print(cfg.model_dump_json(indent=2))
PY
```

Then locate the Agent Mail model and integration helpers:

```bash
uv run python - <<'PY'
import inspect
import nate_oha.config as config

for name, value in vars(config).items():
    if "mail" in name.lower():
        print(name, value)
        try:
            print(inspect.getsource(value))
        except (OSError, TypeError):
            pass
PY
```

Capture only the model paths and required fields needed to implement the constructor. Do not create an adapter abstraction unless the constructor must actually call an external API.

## Validation Strategy

Prefer a few macro-level tests.

### 1. CLI dry-run construction

Invoke `swarm create --dry-run --constructor agent-mail` with two real valid nate-oha config files and assert that the emitted `SwarmState` contains:

- one non-empty shared Agent Mail project ID;
- two distinct Agent Mail identities;
- complete valid `NateOHAConfig` objects;
- ordered constructor metadata.

### 2. Persist-and-load round trip

Create a constructed swarm, load it through `MetadataStore.load_swarm_state()`, and assert semantic equality of the generated Agent Mail values.

### 3. Error prevents persistence

Use a constructor that raises a sentinel exception. Assert that the same exception escapes and `.nate_ntm/swarm.json` does not exist.

### 4. Ordered composition

Use two small test constructors that append markers under `runtime_options`; assert the final order is exactly the CLI order.

Avoid micro-testing registry dictionary operations or individual trivial assignments.

## Alternatives Rejected

### Separate `DraftSwarmConfig` and `MaterializedSwarmConfig`

Rejected because both would mirror `SwarmState`. The only meaningful transition is the atomic save.

### Runtime constructor hooks

Rejected because construction is a one-time configuration transformation. Runtime hooks would risk identity regeneration and introduce two ways to configure agents.

### Per-agent constructor invocation

Rejected because Agent Mail setup coordinates swarm-wide project state and uniqueness across all agents.

### Constructor classes with lifecycle methods

Rejected for now. `prepare/apply/commit/rollback` would create unnecessary protocol and compensation machinery. One transformation function is sufficient.

### Secret references and credential vaulting

Rejected as out of scope by product decision. Persist the effective configuration directly.

## Remaining Unknowns

The following do not block planning but must be resolved early in implementation:

1. the exact nested `NateOHAConfig` path for Agent Mail settings;
2. the valid Agent Mail identity naming rules;
3. whether Agent Mail project/identity provisioning is configuration-only or calls an external service;
4. whether a stable identity can be derived directly from `swarm_id` and `agent_id`, or should use the existing Agent Mail naming helper.

The implementation plan should make schema introspection and one focused Agent Mail constructor spike the first foundational task, before broader pipeline work depends on guessed fields.
