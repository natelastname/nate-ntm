# Design: CLI and Agent Mail Configuration Cleanup

## Problem

`nate-ntm` currently has several overlapping and ambiguous ways to supply Agent Mail construction values:

- the Agent Mail constructor reads process environment variables directly;
- `RuntimeConfig` also contains Agent Mail settings used by runtime startup;
- the persisted swarm stores a string `agent_mail_project_id`;
- `nate-oha` models the corresponding Agent Mail `project` value as a `Path`, despite also describing it as a logical name;
- the constructor converts a logical identifier such as `demo-agent-mail` into `Path("demo-agent-mail")` even though no filesystem behavior is intended;
- new swarms default to the generic logical identifier `default`, even though each persisted swarm is a distinct durable object.

As a result, users and developers cannot tell whether an Agent Mail project value is a filesystem location, a server-side project identifier, runtime configuration, or swarm-construction input. Constructor behavior also depends on hidden global environment state rather than the explicit `swarm create` command. The generic default swarm identifier also makes persisted state harder to correlate with external systems such as OpenHands conversations.

## Motivation

Swarm creation should be understandable from the command that created the swarm and from the materialized `swarm.json`. A user should not need to know which environment variable alias happens to be consulted, nor should a logical Agent Mail identifier be represented as a filesystem path.

Every newly created swarm should also receive a durable, globally distinctive logical identifier by default. Using the same compact UUID shape as OpenHands conversation identifiers makes swarm IDs easy to correlate with adjacent tooling and avoids the misleading implication that every unnamed swarm is literally named `default`.

This cleanup is intentionally willing to remove unused environment-variable interfaces and obsolete compatibility paths. There should be one clear way to provide each value.

## Required Behavior

1. `nate-ntm swarm create` MUST expose explicit CLI options for Agent Mail constructor inputs that may vary between creations.
2. The Agent Mail constructor MUST receive those values through explicit construction input rather than reading environment variables or other ambient process state.
3. All Agent Mail project values in `nate-ntm` MUST be defined and documented as logical Agent Mail project identifiers, not filesystem paths.
4. The CLI and persisted state MUST use terminology that clearly distinguishes:
   - the local source-code project directory managed by `nate-ntm`;
   - the logical swarm identifier; and
   - the logical Agent Mail project identifier used by the Agent Mail service.
5. The following environment-variable interfaces MUST be removed rather than retained as aliases:
   - `NATE_NTM_AGENT_MAIL_PROJECT`
   - `AGENT_MAIL_PROJECT`
   - `NATE_NTM_AGENT_MAIL_URL`
   - `AGENT_MAIL_UPSTREAM_URL`
   - `AGENT_MAIL_URL`
6. Agent Mail constructor options MUST have stable defaults so the common command needs only `--constructor agent-mail`.
7. Supplying Agent Mail constructor-specific options without selecting the `agent-mail` constructor MUST fail rather than silently doing nothing.
8. The selected effective Agent Mail project identifier and upstream URL MUST be materialized into the resulting per-agent `NateOHAConfig` values and visible in `--dry-run` output.
9. Starting or resuming an existing swarm MUST continue to use persisted effective configuration and MUST NOT require the original constructor CLI arguments.
10. Existing configuration fields whose only purpose was to support the removed environment-variable paths MUST be removed when they have no remaining runtime consumer.
11. Documentation and CLI help MUST use one canonical name for each concept and MUST NOT describe a logical Agent Mail project identifier as a path.
12. When `--swarm-id` is omitted during creation, nate-ntm MUST generate a UUID version 4 and use its 32 lowercase hexadecimal digits with all dashes removed, equivalent to `uuid.uuid4().hex`.
13. An explicitly supplied `--swarm-id` MUST continue to override automatic generation.
14. The generated or explicit swarm ID MUST be persisted and reused unchanged by later load, start, and resume operations.
15. No compatibility layer, deprecated alias, or dual input path is required.

## Scenarios and Examples

### Default Agent Mail construction

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail
```

The command generates a swarm ID such as `f47ac10b58cc4372a5670e02b2c3d479` and uses stable defaults for the Agent Mail project identifier and upstream URL. The generated and effective values are explicit in dry-run or persisted output.

### Explicit swarm and Agent Mail identifiers

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --swarm-id planning-swarm \
  --agent planner.json \
  --constructor agent-mail \
  --agent-mail-project-id planning-mail \
  --agent-mail-url http://127.0.0.1:8765
```

`/work/my-repository` is a filesystem path. `planning-swarm` is the logical swarm identifier. `planning-mail` is the logical Agent Mail project identifier. These values are not interchangeable and are represented by different names and types.

### Invalid unused constructor option

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --agent planner.json \
  --agent-mail-project-id planning-mail
```

The command fails because `agent-mail` was not selected.

### Resume

```bash
nate-ntm runtime start --project /work/my-repository --mode resume
```

No Agent Mail constructor arguments or environment variables are needed. The runtime consumes the materialized configuration and reuses the persisted swarm ID.

## Constraints

- The cleanup MUST preserve one-time constructor semantics: constructors run during `swarm create`, never during runtime startup or resume.
- The local nate-ntm project directory remains a `Path`.
- The logical swarm identifier remains a string.
- Agent Mail upstream endpoints remain validated URLs represented as strings.
- Agent Mail project identifiers remain strings even when they happen to resemble relative filesystem paths.
- The change may require a coordinated `nate-oha` model update so that its Agent Mail project field is a string rather than a `Path`.
- Effective credentials may continue to be stored directly; secret-management work is outside this epic.
- Ordinary validation and constructor errors should continue to surface without a new error framework.
- Swarm metadata remains under the project-local `.nate_ntm/` directory in this epic.

## Success Criteria

1. A repository-wide search finds no runtime use of the removed Agent Mail environment-variable names.
2. `nate-ntm swarm create --help` presents explicit, unambiguous Agent Mail constructor options.
3. The default and explicit CLI scenarios both produce valid materialized swarms.
4. The materialized Agent Mail project identifier is represented as a string throughout nate-ntm and its effective nate-oha configuration.
5. Passing Agent Mail-only options without `--constructor agent-mail` fails with a clear CLI validation error.
6. Resume succeeds without constructor arguments or Agent Mail construction environment variables.
7. Two swarm creations that omit `--swarm-id` receive distinct 32-character lowercase hexadecimal UUID4 identifiers.
8. A generated swarm ID remains unchanged after persistence and resume.
9. An explicit `--swarm-id` is preserved exactly.
10. The default test suite passes without tests that preserve the removed aliases or the old `default` swarm identifier.

## Scope

- Agent Mail-related options on `nate-ntm swarm create`.
- The explicit data passed from the CLI into swarm constructors.
- Naming and typing of Agent Mail project identifiers.
- Generation and persistence of default swarm identifiers.
- Removal of unused Agent Mail construction environment variables and configuration fields.
- Required coordinated changes to the adjacent `nate-oha` Agent Mail configuration model.
- CLI help, examples, and tests for the cleaned-up interface.

## Non-Goals

- Moving `.nate_ntm/` out of the project directory or introducing a centralized swarm store.
- Migrating existing project-local swarm metadata into a future centralized layout.
- A general configuration-file format for constructors.
- Environment-variable support for constructor inputs.
- Backward compatibility for the removed environment-variable names or the old generated `default` swarm ID.
- Secret vaulting, credential references, or redaction.
- Changing the persisted one-time construction model.
- Changing the Agent Mail service protocol or provisioning behavior.
- Refactoring unrelated runtime-start CLI options.

## Future Direction

A later epic may move swarm metadata from `<project>/.nate_ntm/` to a centralized per-user store organized by swarm ID, similar to how OpenHands stores conversations by conversation ID. That design will need to define project-to-swarm discovery, support for multiple swarms associated with one project path, migration of existing metadata, and whether the project path remains an invariant or becomes ordinary persisted metadata.

## Terminology

- **Local project directory**: The filesystem directory supplied through `--project` and currently containing project-local nate-ntm metadata.
- **Swarm ID**: The durable logical identifier for a swarm. When omitted by the user, it is generated as `uuid.uuid4().hex`.
- **Agent Mail project identifier**: A logical string identifying a project or namespace in Agent Mail. It is not a filesystem path.
- **Agent Mail upstream URL**: The URL of the Agent Mail service used to configure agents.
- **Construction input**: Explicit values supplied to constructors during `swarm create` before the swarm is persisted.
- **Materialized configuration**: The complete persisted swarm and per-agent configuration used by runtime startup and resume.

## Open Questions

1. Should the canonical option be `--agent-mail-project-id` or the shorter `--agent-mail-project`? The former is less ambiguous; the latter matches existing field names.
2. Should the default Agent Mail project identifier be derived from the generated swarm ID, or generated independently?
3. Should the default Agent Mail upstream URL remain `http://127.0.0.1:8765`, or should it be required explicitly?
4. Should the constructor-specific inputs be represented by one small typed construction-context object immediately, or passed as explicit parameters until a second constructor needs options?
5. Is `RuntimeConfig.agent_mail_project` still consumed by runtime startup after materialization, or can it be deleted entirely as part of this epic?
