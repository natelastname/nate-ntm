# Research: Swarm Identity, Storage, and CLI Cleanup

## Established Context

Epic 013 makes a clean break from project-local swarm metadata and ambient Agent Mail construction configuration.

The approved behavioral contract is:

- every swarm has one durable `swarm_id`;
- omitted swarm IDs are generated with `uuid.uuid4().hex`;
- swarm state lives at `~/.nate-ntm/swarms/<swarm-id>/swarm.json`;
- `swarm_id` is the only lookup key for an existing swarm;
- `swarm create --project` is optional and defaults to the resolved working directory;
- runtime resume uses `--swarm-id`, not `--project`;
- the default Agent Mail project ID is exactly the effective swarm ID;
- Agent Mail constructor inputs are CLI values, not environment variables;
- Agent Mail project IDs are logical strings, not filesystem paths;
- tests use the real canonical store with unique IDs and delete only the directories they created;
- no migration or compatibility implementation is required.

## Questions Investigated

1. Where are storage location, project path, and swarm ID currently coupled?
2. How should the centralized store API be shaped?
3. Does the repository have more than one swarm-creation path?
4. Which `RuntimeConfig` fields become obsolete?
5. How can runtime resume recover its project and Agent Mail settings from persisted state?
6. What exact Agent Mail CLI vocabulary and defaults should be used?
7. Does `nate-oha` require a coordinated model change?
8. How should tests safely exercise the real `~/.nate-ntm/swarms/` hierarchy?

All questions were answerable from the repositories and the approved product decisions. No experiment or further user evidence is required before planning.

## Repository Findings

### Storage is currently configuration-bound and project-local

`src/nate_ntm/config/runtime_config.py` currently resolves:

- `project_path`, defaulting to the working directory;
- `metadata_dir`, defaulting to `<project>/.nate_ntm`;
- `swarm_id`, defaulting to the literal string `default`.

It also permits `NATE_NTM_PROJECT_DIR`, `NATE_NTM_METADATA_DIR`, and `NATE_NTM_SWARM_ID` to influence these values.

`src/nate_ntm/runtime/metadata_store.py` is constructed from a complete `RuntimeConfig`. Its swarm path is `config.metadata_dir / "swarm.json"`, and loading validates both the configured project path and configured swarm ID against the persisted object.

This shape prevents lookup by swarm ID alone because the caller must already know the project path and metadata directory before it can read the state that contains the project path.

### The existing atomic writer can be retained

`_atomic_write_json()` already performs the correct file-level sequence:

1. create a temporary file in the target directory;
2. serialize, flush, and `fsync`;
3. `os.replace()` into place;
4. remove an abandoned temporary file on failure.

The centralized-store change only needs to replace path resolution and store binding. It does not require a new persistence format or transaction framework.

### There are currently two independent swarm-creation implementations

`nate-ntm swarm create`:

- reads complete per-agent `NateOHAConfig` files;
- builds a complete `SwarmState`;
- applies constructors;
- dry-runs or saves it.

`RuntimeDaemon.create()` independently:

- provisions Agent Mail through runtime adapters;
- synthesizes `agent-1`, `agent-2`, etc.;
- builds effective nate-oha configurations;
- creates and saves another `SwarmState`.

`runtime start --mode=create --agents N` reaches the second path through `create_runtime_control_context()`.

This is the largest duplication exposed by the epic. Keeping both paths would preserve two definitions of swarm creation, two Agent Mail provisioning paths, and two sources of persisted state. It would also make the new CLI semantics unclear because `runtime start` would still need project and construction inputs.

### Runtime resume currently constructs adapters too early

`RuntimeDaemon.resume()` currently receives a fully populated `RuntimeConfig`, creates adapters from it, and then loads swarm state from `MetadataStore(config)`.

`McpAgentMailClient` currently obtains its endpoint from constructor arguments or environment variables and derives its project key from `RuntimeConfig.agent_mail_project`, falling back to `RuntimeConfig.project_path`.

Under the approved model, the persisted swarm is authoritative for:

- `project_path`;
- `swarm_id`;
- `agent_mail_project_id`;
- each agent's complete `NateOHAConfig`, including Agent Mail endpoint, identity, and credentials.

Therefore resume must load the swarm before constructing integrations that depend on those values. Runtime adapters should receive explicit materialized values rather than reconstructing construction-time configuration from environment variables.

### Agent Mail configuration is duplicated across three layers

Current values overlap across:

1. `RuntimeConfig.agent_mail_project` and `agent_mail_upstream_url`;
2. `SwarmState.agent_mail_project_id`;
3. each `NateOHAConfig.features.agent_mail` object.

The per-agent nate-oha configuration is required because each launched agent needs its identity, credentials, project, and URL. `SwarmState.agent_mail_project_id` remains useful as the swarm-level canonical project key. The `RuntimeConfig` Agent Mail project and URL fields are construction/runtime reconstruction inputs and become redundant once creation materializes them and resume reads persisted state.

`RuntimeConfig.agent_mail_enabled` is likewise redundant for a materialized swarm: Agent Mail participation can be determined from persisted swarm/agent configuration. It should be removed unless planning uncovers an unrelated consumer.

### The runtime Agent Mail adapter still reads removed URL aliases

`McpAgentMailClient.__post_init__()` currently reads:

- `NATE_NTM_AGENT_MAIL_URL`;
- `AGENT_MAIL_URL`.

Its project lookup also preserves a backwards-compatible fallback from an explicit project key to the local project path.

Both behaviors conflict with epic 013. The adapter should receive an explicit base URL and Agent Mail project ID. It should not derive either from environment variables or the local filesystem path.

Agent Mail authentication token variables are a separate runtime authentication concern and are not among the five construction aliases removed by the spec. They need not be changed in this epic unless the implementation naturally replaces them with persisted per-agent credentials.

### `nate-oha` models a logical identifier as `Path`

The adjacent `nate-oha` dependency is editable from `../nate-oha` according to `pyproject.toml`.

Its `AgentMailFeatureConfig.project` field is currently `Path | None`, although its documentation says "path or logical name." Enabling Agent Mail requires `project`, `agent_identity`, `credentials_ref`, and `upstream_url`.

Because epic 013 explicitly defines the project as a logical service identifier, `nate-oha` must change this field to `str | None`. Nate-ntm should then stop wrapping values in `Path` or comparing them through `Path` normalization.

No compatibility validator accepting both representations is needed. JSON persisted by the old model already contains a string, so the wire representation remains straightforward even though the Python type changes.

## Decisions

### D1. Use one creation path

`nate-ntm swarm create` is the sole swarm materialization command.

Remove runtime creation semantics:

- remove `runtime start --mode=create`;
- remove `runtime start --agents`;
- remove `RuntimeDaemon.create()` and the create branch in the runner;
- runtime start always loads an existing swarm by `--swarm-id`.

This follows the project's one-way/no-duplication principles and makes constructor execution unambiguously creation-only.

### D2. Bind `MetadataStore` directly to `swarm_id`

The store should not require `RuntimeConfig` or `project_path` to locate state.

Recommended canonical shape:

```python
MetadataStore(swarm_id: str)
```

with:

```python
swarm_dir = Path.home() / ".nate-ntm" / "swarms" / swarm_id
swarm_path = swarm_dir / "swarm.json"
```

The store loads and validates that the embedded `state.swarm_id` equals its bound ID. It does not compare against an externally supplied project path because the persisted project path is authoritative during lookup.

Keep the existing atomic JSON writer.

### D3. Validate swarm IDs as safe single path components

Explicit swarm IDs must be non-empty and must not contain path separators, `.` or `..` path traversal forms, or values whose normalized path escapes `~/.nate-ntm/swarms/`.

Generated IDs are `uuid4().hex` and naturally satisfy this rule.

Do not introduce slug rewriting. Preserve a valid explicit ID exactly; reject an invalid one.

### D4. Generate the ID once at the CLI materialization boundary

`swarm create` resolves:

```python
swarm_id = explicit_swarm_id or uuid4().hex
project_path = (explicit_project or Path.cwd()).expanduser().resolve()
```

The same `swarm_id` is used for:

- `SwarmState.swarm_id`;
- centralized directory lookup;
- the default Agent Mail project ID;
- CLI output.

Dry-run still materializes and displays a generated ID but does not create the swarm directory or write state.

### D5. Use `--agent-mail-project-id`

The canonical option is `--agent-mail-project-id`.

It is longer than `--agent-mail-project` but removes the exact ambiguity this epic exists to fix. The internal and persisted swarm-level field should also use `agent_mail_project_id` consistently.

Effective value:

```python
agent_mail_project_id = explicit_value or swarm_id
```

Supplying it without `--constructor agent-mail` is an error.

### D6. Keep a stable explicit Agent Mail URL default

Use `--agent-mail-url` with default:

```text
http://127.0.0.1:8765
```

This matches the nate-oha feature configuration's base-URL meaning and the constructor behavior introduced in epic 012. Transport-specific `/api` path handling belongs inside the Agent Mail client rather than in the user-facing project configuration.

Supplying `--agent-mail-url` without `--constructor agent-mail` is an error.

Remove the five construction environment aliases listed in the spec from both configuration loading and runtime adapter resolution.

### D7. Use one typed construction context

Constructors now have non-swarm inputs, so introduce one immutable typed context rather than adding constructor-specific positional arguments.

Recommended shape:

```python
@dataclass(frozen=True, slots=True)
class ConstructionContext:
    agent_mail_project_id: str | None = None
    agent_mail_url: str = "http://127.0.0.1:8765"
```

Constructor signature:

```python
Callable[[SwarmState, ConstructionContext], SwarmState]
```

The Agent Mail constructor computes `context.agent_mail_project_id or swarm.swarm_id`.

### D8. Split creation inputs from resumed runtime configuration

`RuntimeConfig` should represent only settings needed to run an already materialized swarm, such as control/ACP endpoints and executable/runtime overrides.

Remove at least:

- `metadata_dir`;
- default/project-derived `swarm_id` behavior;
- `agent_mail_project`;
- `agent_mail_upstream_url`;
- `agent_mail_enabled`;
- their associated environment loading and path restrictions.

For resume, the CLI first loads `SwarmState` by swarm ID, then creates the runtime configuration using `state.project_path` and `state.swarm_id` plus runtime-only CLI/environment settings.

The persisted state, not `.env` or the working directory, supplies the project path and materialized Agent Mail values.

### D9. Build runtime Agent Mail integration from persisted state

The runtime Agent Mail client should accept explicit values, principally:

- `project_id = swarm.agent_mail_project_id`;
- URL from the materialized agent configuration;
- persisted credentials/identities from agent configurations.

It must not call `ensure_project()` using a local path fallback during resume. Any necessary idempotent service validation should use the persisted project ID.

Where all agents are required to share one URL, validate that invariant when loading/materializing the swarm rather than arbitrarily selecting conflicting values.

### D10. Change `nate-oha` Agent Mail project type to `str`

Update the adjacent nate-oha model and its tests/documentation in the same implementation effort. Nate-ntm should consume the new string type directly.

No compatibility branch for `Path` is required.

### D11. Test the real canonical store

Tests that exercise persistence should create real directories under:

```text
~/.nate-ntm/swarms/<test-swarm-id>/
```

Rules:

- generate a fresh UUID4-hex ID per test;
- record the exact directory owned by the test;
- clean that exact directory in `finally`/fixture teardown, even after assertion failure;
- never enumerate, clear, or recursively remove `~/.nate-ntm/swarms/` itself;
- never reuse a human production swarm ID;
- keep pure validation tests filesystem-free when persistence is not part of the behavior under test.

No alternate root, environment override, dependency injection seam, or second storage implementation is needed.

### D12. Preserve macro-level verification

The most valuable tests cover complete flows:

1. create from the working directory, persist centrally, and load by generated ID;
2. create two swarms for the same project and verify independent state;
3. explicit swarm ID collision leaves existing state unchanged;
4. Agent Mail defaults to the swarm ID and explicit override wins;
5. runtime start loads by swarm ID only and recovers the persisted project path;
6. constructor options without the constructor fail;
7. no project-local `.nate_ntm/` directory is created;
8. nate-oha round-trip validation preserves Agent Mail project IDs as strings.

Avoid micro-tests of path concatenation, registry dictionary contents, or UUID library behavior.

## Tradeoffs

### Real-home test storage

Using `~/.nate-ntm/swarms/` gives maximum fidelity and enforces one implementation. The cost is that a killed test process can leave an isolated UUID-named directory behind. This is acceptable because collisions are negligible and cleanup targets are exact. A later maintenance command may remove abandoned test swarms, but that is not required for epic 013.

### Removing runtime create mode

This is a larger surface change than retaining `--mode=create`, but preserving it would retain the central architectural duplication. A clean removal reduces code, options, tests, and ambiguity.

### Fixed home-directory layout

The fixed path is intentionally less portable/configurable than an XDG or injected root. It matches the approved product behavior and OpenHands-inspired organization. Alternate roots are not needed.

## Evidence Requested from the User

None.

## Experiments and Captured Results

No runtime experiment is required. Repository inspection was sufficient to identify the existing path computation, atomic write behavior, duplicate creation paths, configuration consumers, and adjacent nate-oha type mismatch.

Implementation validation should run:

```bash
uv run pytest
```

and should include a manual smoke flow that creates a uniquely identified swarm, confirms its exact central path, resumes it by ID, and removes only that smoke-test swarm directory afterward.

## Remaining Unknowns

None that block planning.

The implementation agent may choose exact internal function names and module boundaries, but must preserve the decisions above: one creation path, one centralized store, one lookup key, explicit constructor context, persisted runtime inputs, and no compatibility implementations.
