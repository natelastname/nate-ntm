# Design: CLI and Agent Mail Configuration Cleanup

## Problem

`nate-ntm` currently has several overlapping and ambiguous ways to supply Agent Mail construction values:

- the Agent Mail constructor reads process environment variables directly;
- `RuntimeConfig` also contains Agent Mail settings used by runtime startup;
- the persisted swarm stores a string `agent_mail_project_id`;
- `nate-oha` models the corresponding Agent Mail `project` value as a `Path`, despite also describing it as a logical name;
- the constructor converts a logical identifier such as `demo-agent-mail` into `Path("demo-agent-mail")` even though no filesystem behavior is intended.

As a result, users and developers cannot tell whether an Agent Mail project value is a filesystem location, a server-side project identifier, runtime configuration, or swarm-construction input. Constructor behavior also depends on hidden global environment state rather than the explicit `swarm create` command.

## Motivation

Swarm creation should be understandable from the command that created the swarm and from the materialized `swarm.json`. A user should not need to know which environment variable alias happens to be consulted, nor should a logical Agent Mail identifier be represented as a filesystem path.

This cleanup is intentionally willing to remove unused environment-variable interfaces and obsolete compatibility paths. There should be one clear way to provide each value.

## Required Behavior

1. `nate-ntm swarm create` MUST expose explicit CLI options for Agent Mail constructor inputs that may vary between creations.
2. The Agent Mail constructor MUST receive those values through explicit construction input rather than reading environment variables or other ambient process state.
3. All Agent Mail project values in `nate-ntm` MUST be defined and documented as logical Agent Mail project identifiers, not filesystem paths.
4. The CLI and persisted state MUST use terminology that clearly distinguishes:
   - the local source-code project directory managed by `nate-ntm`; and
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
12. No compatibility layer, deprecated alias, or dual input path is required.

## Scenarios and Examples

### Default Agent Mail construction

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail
```

The command uses stable defaults for the Agent Mail project identifier and upstream URL. The generated values are explicit in dry-run or persisted output.

### Explicit Agent Mail construction values

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --agent planner.json \
  --constructor agent-mail \
  --agent-mail-project-id planning-swarm \
  --agent-mail-url http://127.0.0.1:8765
```

`/work/my-repository` is a filesystem path. `planning-swarm` is a logical Agent Mail project identifier. These values are not interchangeable and are represented by different types and names.

### Invalid unused constructor option

```bash
nate-ntm swarm create \
  --project /work/my-repository \
  --agent planner.json \
  --agent-mail-project-id planning-swarm
```

The command fails because `agent-mail` was not selected.

### Resume

```bash
nate-ntm runtime start --project /work/my-repository --mode resume
```

No Agent Mail constructor arguments or environment variables are needed. The runtime consumes the materialized configuration.

## Constraints

- The cleanup MUST preserve one-time constructor semantics: constructors run during `swarm create`, never during runtime startup or resume.
- The local nate-ntm project directory remains a `Path`.
- Agent Mail upstream endpoints remain validated URLs represented as strings.
- Agent Mail project identifiers remain strings even when they happen to resemble relative filesystem paths.
- The change may require a coordinated `nate-oha` model update so that its Agent Mail project field is a string rather than a `Path`.
- Effective credentials may continue to be stored directly; secret-management work is outside this epic.
- Ordinary validation and constructor errors should continue to surface without a new error framework.

## Success Criteria

1. A repository-wide search finds no runtime use of the removed Agent Mail environment-variable names.
2. `nate-ntm swarm create --help` presents explicit, unambiguous Agent Mail constructor options.
3. The default and explicit CLI scenarios both produce valid materialized swarms.
4. The materialized Agent Mail project identifier is represented as a string throughout nate-ntm and its effective nate-oha configuration.
5. Passing Agent Mail-only options without `--constructor agent-mail` fails with a clear CLI validation error.
6. Resume succeeds without constructor arguments or Agent Mail construction environment variables.
7. The default test suite passes without tests that preserve the removed aliases.

## Scope

- Agent Mail-related options on `nate-ntm swarm create`.
- The explicit data passed from the CLI into swarm constructors.
- Naming and typing of Agent Mail project identifiers.
- Removal of unused Agent Mail construction environment variables and configuration fields.
- Required coordinated changes to the adjacent `nate-oha` Agent Mail configuration model.
- CLI help, examples, and tests for the cleaned-up interface.

## Non-Goals

- A general configuration-file format for constructors.
- Environment-variable support for constructor inputs.
- Backward compatibility for the removed environment-variable names.
- Secret vaulting, credential references, or redaction.
- Changing the persisted one-time construction model.
- Changing the Agent Mail service protocol or provisioning behavior.
- Refactoring unrelated runtime-start CLI options.

## Terminology

- **Local project directory**: The filesystem directory supplied through `--project` and managed by nate-ntm.
- **Agent Mail project identifier**: A logical string identifying a project or namespace in Agent Mail. It is not a filesystem path.
- **Agent Mail upstream URL**: The URL of the Agent Mail service used to configure agents.
- **Construction input**: Explicit values supplied to constructors during `swarm create` before the swarm is persisted.
- **Materialized configuration**: The complete persisted swarm and per-agent configuration used by runtime startup and resume.

## Open Questions

1. Should the canonical option be `--agent-mail-project-id` or the shorter `--agent-mail-project`? The former is less ambiguous; the latter matches existing field names.
2. Should the default Agent Mail project identifier remain `<swarm-id>-agent-mail`, or should it be exactly the swarm ID?
3. Should the default Agent Mail upstream URL remain `http://127.0.0.1:8765`, or should it be required explicitly?
4. Should the constructor-specific inputs be represented by one small typed construction-context object immediately, or passed as explicit parameters until a second constructor needs options?
5. Is `RuntimeConfig.agent_mail_project` still consumed by runtime startup after materialization, or can it be deleted entirely as part of this epic?
