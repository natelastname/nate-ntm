# Design: Swarm Identity, Storage, and CLI Cleanup

## Problem

`nate-ntm` currently conflates several independent concepts:

- a local source-code project directory;
- a logical swarm identifier;
- the location of durable swarm metadata;
- a logical Agent Mail project identifier; and
- Agent Mail constructor inputs supplied through ambient environment variables.

Swarm metadata is stored under `<project>/.nate_ntm/`, so the project path acts implicitly as the lookup key even though `SwarmState` already has a separate `swarm_id`. New swarms also default to the generic identifier `default`, preventing multiple independently addressable swarms from naturally sharing one project.

Agent Mail configuration has a parallel ambiguity: the constructor reads several environment-variable aliases, runtime configuration carries overlapping fields, persisted state stores an Agent Mail project ID as a string, and `nate-oha` models the same logical value as a `Path` despite no filesystem behavior being intended.

These overlaps leave no single authoritative answer to basic questions such as “which swarm should resume?”, “where is its state?”, and “is this project value a directory or an external namespace?”

## Motivation

A swarm should be a durable object with its own stable identity, independent of the repository it operates on. The swarm ID should be the one canonical storage and lookup key, mirroring the way OpenHands organizes conversations by conversation ID.

Creation should operate on a local project directory because agents need a workspace, but the common case should not require spelling out the current directory. After creation, commands should locate the swarm by ID and recover its project directory and complete effective configuration from centralized persisted state.

Agent Mail construction should likewise be explicit and inspectable from the creation command and materialized configuration. Its default project ID should be derived from the swarm ID so the two systems share one obvious namespace without introducing another generated identifier.

This epic intentionally makes a clean break. No compatibility path is required for project-local storage, project-based resume, removed environment variables, or the old generated `default` swarm ID.

## Required Behavior

1. Every swarm MUST have one durable logical `swarm_id`.
2. When `--swarm-id` is omitted during creation, nate-ntm MUST generate `uuid.uuid4().hex`: 32 lowercase hexadecimal characters with no dashes.
3. An explicitly supplied `--swarm-id` MUST override automatic generation and be preserved exactly after validation.
4. Swarm metadata MUST be stored in one centralized per-user root, organized by swarm ID rather than project path.
5. The default metadata location MUST follow this logical layout:

   ```text
   <nate-ntm state root>/swarms/<swarm-id>/swarm.json
   ```

6. The default nate-ntm state root MUST follow the platform-appropriate user state directory convention rather than living inside the source project.
7. The swarm ID MUST be the sole key used to locate an existing swarm.
8. Runtime resume MUST require `--swarm-id` and MUST NOT accept `--project` as an alternate lookup mechanism.
9. On resume, nate-ntm MUST load the persisted project path and complete materialized configuration from centralized swarm state.
10. The local project path MUST remain persisted as execution context, but MUST NOT determine storage location or swarm identity.
11. Multiple swarms MUST be allowed to reference the same local project directory without overwriting one another.
12. `nate-ntm swarm create --project` MUST be optional and MUST default to the process working directory.
13. The effective project directory MUST be resolved and validated before the swarm is materialized.
14. Creation MUST fail if the chosen or generated swarm ID already has persisted state, unless an explicitly documented destructive replacement option is used.
15. Project-local `.nate_ntm/` state MUST no longer be read or written by the canonical implementation.
16. No migration, fallback lookup, deprecated alias, or dual storage path is required.
17. `nate-ntm swarm create` MUST expose explicit CLI options for Agent Mail constructor inputs that may vary between creations.
18. The Agent Mail constructor MUST receive those values through explicit construction input rather than environment variables or other ambient process state.
19. Agent Mail project values MUST be defined and represented as logical string identifiers, never filesystem paths.
20. The CLI and persisted state MUST clearly distinguish:
    - the local project directory;
    - the swarm ID; and
    - the Agent Mail project ID.
21. The following Agent Mail environment-variable interfaces MUST be removed:
    - `NATE_NTM_AGENT_MAIL_PROJECT`
    - `AGENT_MAIL_PROJECT`
    - `NATE_NTM_AGENT_MAIL_URL`
    - `AGENT_MAIL_UPSTREAM_URL`
    - `AGENT_MAIL_URL`
22. When the Agent Mail project ID is omitted, it MUST default to the effective swarm ID exactly, without an additional suffix or independently generated value.
23. An explicitly supplied Agent Mail project ID MUST override that default.
24. Agent Mail constructor options MUST otherwise have stable defaults so the common creation command needs only `--constructor agent-mail`.
25. Supplying Agent Mail-only options without selecting the `agent-mail` constructor MUST fail.
26. Effective Agent Mail project ID and upstream URL values MUST be materialized into each resulting `NateOHAConfig` and visible in dry-run output.
27. Starting or resuming a swarm MUST use persisted effective configuration and MUST NOT require the original constructor arguments.
28. Configuration fields used only by removed environment-variable or project-local-storage paths MUST be deleted when they have no remaining consumer.
29. CLI help and documentation MUST use one canonical term and one canonical option for each concept.

## Scenarios and Examples

### Create from the working directory

```bash
cd /work/my-repository
nate-ntm swarm create \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail
```

The command uses `/work/my-repository` as the project directory, generates a swarm ID such as:

```text
f47ac10b58cc4372a5670e02b2c3d479
```

The default Agent Mail project ID is the same value:

```text
f47ac10b58cc4372a5670e02b2c3d479
```

State is stored under:

```text
<nate-ntm state root>/swarms/f47ac10b58cc4372a5670e02b2c3d479/swarm.json
```

The command reports the generated swarm ID so it can be used by subsequent commands.

### Create for another project directory

```bash
nate-ntm swarm create \
  --project /work/other-repository \
  --agent planner.json \
  --constructor agent-mail
```

The explicit directory overrides the working-directory default.

### Create with explicit identifiers

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --swarm-id planning-swarm \
  --agent planner.json \
  --constructor agent-mail \
  --agent-mail-project-id planning-mail \
  --agent-mail-url http://127.0.0.1:8765
```

`/work/my-repository` is a filesystem directory. `planning-swarm` is the nate-ntm swarm ID and centralized storage key. `planning-mail` is the external Agent Mail project ID.

If `--agent-mail-project-id` were omitted, its effective value would be `planning-swarm`.

### Resume by swarm ID

```bash
nate-ntm runtime start --swarm-id planning-swarm --mode resume
```

The runtime locates centralized state using `planning-swarm`, reads `/work/my-repository` from that state, and resumes without a `--project` argument or Agent Mail constructor inputs.

### Invalid project-based resume

```bash
nate-ntm runtime start --project /work/my-repository --mode resume
```

The command fails because an existing swarm is addressed only by `--swarm-id`.

### Multiple swarms for one project

Two creation commands may use the same effective project directory with different generated or explicit swarm IDs. Each swarm receives its own centralized directory and complete independent state.

### Invalid unused constructor option

```bash
nate-ntm swarm create \
  --agent planner.json \
  --agent-mail-project-id planning-mail
```

The command fails because `agent-mail` was not selected.

## Constraints

- The effective creation project defaults to the current working directory but must resolve to a valid local directory.
- The local project directory remains represented as a `Path` in memory and persisted state.
- The swarm ID and Agent Mail project ID remain strings.
- The default Agent Mail project ID is exactly the effective swarm ID.
- The project path is not required to be unique across swarms.
- The centralized store remains file-based and uses one authoritative `swarm.json` object graph per swarm.
- Writes must preserve the existing atomic replacement guarantee.
- Constructors remain one-time creation transformations and never run during resume.
- Agent Mail upstream endpoints remain validated URL strings.
- A coordinated `nate-oha` change may be required to model its Agent Mail project field as `str` rather than `Path`.
- Effective credentials may continue to be stored directly.
- Ordinary validation, constructor, and persistence errors should surface without a new error framework.

## Success Criteria

1. Two creations omitting `--swarm-id` receive distinct valid UUID4-hex IDs.
2. Running `swarm create` without `--project` persists the resolved current working directory.
3. An explicit `--project` overrides the working-directory default.
4. Two swarms associated with the same project directory persist and load independently.
5. No canonical runtime code reads or writes `<project>/.nate_ntm/`.
6. An existing swarm can be resumed using only its swarm ID plus runtime-specific options.
7. Resume does not accept the project path as a swarm lookup key.
8. The persisted project path is recovered unchanged from centralized state.
9. A collision on an existing swarm ID fails without damaging existing state.
10. A repository-wide search finds no runtime use of the removed Agent Mail environment-variable names.
11. `swarm create --help` presents unambiguous swarm, project, and Agent Mail options.
12. Agent Mail project IDs remain strings throughout nate-ntm and effective nate-oha configuration.
13. With no explicit Agent Mail project ID, the materialized Agent Mail project ID equals the effective swarm ID.
14. An explicit Agent Mail project ID is preserved exactly.
15. Agent Mail-only options without `--constructor agent-mail` fail clearly.
16. Resume requires no Agent Mail constructor arguments or construction environment variables.
17. The complete default test suite passes without tests preserving project-local storage, project-based resume, environment aliases, or the `default` swarm ID.

## Scope

- Generated and explicit swarm identity.
- Centralized per-user swarm persistence keyed by swarm ID.
- Create, load, start, and resume CLI semantics affected by swarm lookup.
- Working-directory defaulting for swarm creation.
- Allowing multiple swarms to share one project path.
- Removal of project-local `.nate_ntm/` persistence.
- Agent Mail constructor CLI inputs.
- Deriving the default Agent Mail project ID from the swarm ID.
- Naming and typing of Agent Mail project IDs.
- Removal of unused Agent Mail environment variables and overlapping configuration fields.
- Required coordinated `nate-oha` Agent Mail model changes.
- Documentation, help text, and macro-level tests for the new canonical flow.

## Non-Goals

- Migrating existing project-local `.nate_ntm/` state.
- Falling back from swarm ID lookup to project-directory discovery.
- Maintaining compatibility with the old storage layout or removed environment variables.
- A global database or daemon-managed registry beyond the centralized file hierarchy.
- Searching for swarms by project path, display name, recent usage, or fuzzy matching.
- A general constructor configuration-file language.
- Secret vaulting, credential indirection, or redaction.
- Changing the Agent Mail service protocol or provisioning behavior.
- Refactoring unrelated runtime control API options.

## Terminology

- **State root**: The platform-appropriate centralized per-user directory containing nate-ntm durable state.
- **Swarm ID**: The durable logical identifier and sole lookup/storage key for a swarm. Its generated form is `uuid.uuid4().hex`.
- **Swarm directory**: `<state root>/swarms/<swarm-id>/`.
- **Local project directory**: The persisted filesystem workspace associated with a swarm. During creation it defaults to the current working directory; it does not identify or locate the swarm.
- **Agent Mail project ID**: A logical string identifying an Agent Mail namespace. By default it equals the effective swarm ID. It is not a filesystem path.
- **Agent Mail upstream URL**: The URL of the Agent Mail service used to configure agents.
- **Construction input**: Explicit values supplied during `swarm create` before persistence.
- **Materialized configuration**: The complete persisted swarm and per-agent configuration consumed by startup and resume.

## Open Questions

1. Which platform-state-directory library or standard helper should define the default state root?
2. Should an environment variable or global CLI option allow overriding the state root for testing and unusual deployments, or should only an explicit programmatic configuration hook exist?
3. Should the canonical Agent Mail option be `--agent-mail-project-id` or `--agent-mail-project`?
4. Should the default Agent Mail upstream URL remain `http://127.0.0.1:8765` or be required explicitly?
5. Should constructor inputs use one typed construction-context object immediately?
6. Which existing `RuntimeConfig` fields become unnecessary once swarm lookup and Agent Mail construction inputs are separated?
