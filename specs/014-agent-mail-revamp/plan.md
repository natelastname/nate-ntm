# Implementation Plan: Agent Mail Ownership Revamp

## Summary

Refactor nate-ntm so it no longer acts as an Agent Mail client. nate-oha becomes the sole owner of Agent Mail transport authentication, virtual-project creation, agent registration, inbox access, credentials, and the model-facing facade.

nate-ntm will own only swarm-scoped coordination identifiers, launch configuration, process supervision, control connections, workspace construction, and persisted orchestration metadata.

This MVP deliberately does not implement mailbox watching, unsolicited control notifications, mailbox state in runtime APIs, or event-driven wake scheduling. The accepted future architecture is an embedded Agent Mail monitor inside nate-oha, documented in `agent-mail-monitoring-decision.md`.

## User Stories

### US1 — Create an isolated swarm coordination namespace

**Priority**: P1

An operator can create a new swarm for a repository without reusing or discovering an Agent Mail project associated with that repository.

**Independent checkpoint**:

Creating two swarms for the same project path produces different `swarm_instance_id` and `agent_mail_project_key` values, and every Agent Mail-enabled nate-oha launch in each swarm receives that swarm’s project key.

### US2 — Resume the same swarm identity

**Priority**: P1

An operator can resume an existing swarm and recreate each nate-oha process with the same virtual Agent Mail project key, requested identity, workspace, and conversation identifier.

**Independent checkpoint**:

Create a swarm, persist metadata, rebuild the runtime in resume mode, and verify that all public launch inputs are identical while no Agent Mail secret is present in nate-ntm metadata.

### US3 — Launch nate-oha as the sole Agent Mail owner

**Priority**: P1

Each managed nate-oha process receives enough public configuration to ensure the virtual project and register or restore its own identity, while nate-ntm never receives the resulting registration token.

**Independent checkpoint**:

A macro launch test verifies the generated nate-oha configuration and proves that nate-ntm neither invokes `mcp_agent_mail` nor stores Agent Mail secrets.

## Technical Context

- Python package under `src/nate_ntm/` with Typer CLI, runtime daemon, scheduler, metadata store, ACP adapter, and WebSocket control API.
- Existing Agent Mail assumptions are concentrated in `src/nate_ntm/runtime/agent_mail_client.py`, `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, runtime metadata models, and tests under `tests/integration/runtime_mail/`.
- nate-oha already owns a curated Agent Mail facade and the Agent Mail registration lifecycle.
- `mcp_agent_mail` currently derives projects from filesystem or Git identities; this epic requires an upstream virtual-project contract.
- No scheduler or control-channel extension is required to complete this MVP.

## Architecture and Approach

### Ownership boundary

nate-ntm owns:

- swarm instance creation and resume;
- virtual Agent Mail project-key generation and persistence;
- requested per-agent identity generation and persistence;
- nate-oha launch configuration;
- workspace and Git topology;
- process supervision and control connections.

nate-oha owns:

- Agent Mail server authentication;
- virtual project ensure/create;
- agent registration or restoration;
- registration-token storage and use;
- inbox reads and all Agent Mail tool calls;
- model-facing facade policy.

### Identity model

Add a unique `swarm_instance_id` distinct from the reusable human-facing `swarm_id`:

```text
agent_mail_project_key = "nate-ntm:" + swarm_instance_id
```

Each Agent Mail-enabled agent stores a stable `requested_agent_mail_identity`. nate-ntm does not need the resolved Agent Mail name for this MVP and never stores registration tokens.

### Upstream contract

Document and target one explicit virtual-project API in `mcp_agent_mail`. Preferred shape:

```text
ensure_project_by_key(project_key)
```

A `virtual` identity mode is acceptable if upstream strongly prefers one project tool, but nate-ntm must pass a non-filesystem swarm key and must not emulate project creation locally.

### Deferred monitoring architecture

Mailbox monitoring belongs inside nate-oha as an embedded async task sharing the same Agent Mail integration as the facade. A later epic may add public state-change notifications over the existing control connection and allow nate-ntm to schedule turns from them.

No part of that monitoring path is required or implemented here.

## Repository Changes

- Remove `src/nate_ntm/runtime/agent_mail_client.py`.
- Remove all `BaseAgentMailClient` and `FakeAgentMailClient` construction from `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, and tests.
- Remove fake unread-mail state and runtime-side Agent Mail polling paths.
- Extend `src/nate_ntm/runtime/metadata_store.py` with `swarm_instance_id`, `agent_mail_project_key`, and per-agent requested identity fields; remove runtime-owned Agent Mail credential fields.
- Extend launch configuration so each nate-oha process receives the virtual project key and requested identity.
- Update `src/nate_ntm/runtime/daemon.py` create and resume paths.
- Replace Agent Mail integration tests with ownership, metadata, and launch-boundary tests that do not instantiate `mcp_agent_mail`.
- Update Feature 001 documents where they still state that nate-ntm creates, polls, or owns Agent Mail identities.

The scheduler, ACP adapter, runtime event model, and runtime API require only cleanup necessary to remove old fake Agent Mail behavior. They do not gain a new mailbox event contract in this epic.

## Data Model

### Swarm metadata

```python
@dataclass
class SwarmMetadata:
    swarm_id: str
    swarm_instance_id: str
    project_path: Path
    agent_mail_project_key: str
    agents: dict[str, AgentMetadata]
```

### Agent metadata

```python
@dataclass
class AgentMetadata:
    agent_id: str
    requested_agent_mail_identity: str | None
    conversation_id: str
    launch_config: object
```

`requested_agent_mail_identity` is `None` when Agent Mail is disabled for that agent type.

Neither model may contain server bearer tokens, registration tokens, fake Agent Mail identities, or unread-mail state.

## Interfaces and Contracts

### nate-oha launch inputs

The launch adapter must be able to supply:

```text
Agent Mail enabled/disabled
normal nate-oha Agent Mail server configuration reference
virtual project key
requested agent identity
model/program metadata
```

nate-ntm may carry opaque configuration references already required to launch nate-oha, but it must not read, derive, or persist resolved Agent Mail secrets.

### mcp_agent_mail virtual project

The upstream contract must distinguish an explicit virtual project key from a filesystem or Git path. Repeated ensure calls for the same key must resolve the same project; different keys must remain isolated even when agents work in the same repository.

## Validation Strategy

Use a small number of macro tests:

1. Create two swarms for one repository and verify distinct virtual project keys and launch configurations.
2. Resume one swarm and verify exact reuse of its project key, requested identities, workspaces, and conversations.
3. Build or launch nate-oha configuration and verify project-key and requested-identity propagation.
4. Inspect persisted metadata recursively and verify that no Agent Mail bearer token, registration token, unread-mail state, or legacy credential field is present.
5. Verify that nate-ntm has no runtime import or invocation path for `mcp_agent_mail` and no fake replacement adapter.
6. Verify Agent Mail-disabled agents remain launchable without synthetic Agent Mail metadata.

Unit tests are appropriate only for deterministic key generation and metadata validation where macro tests would obscure failures.

## Risks and Tradeoffs

- A virtual-project API may not yet exist upstream. The epic should define the required contract and may temporarily block complete end-to-end launch validation on that upstream change.
- Registration restoration semantics must be finalized in nate-oha. Re-registration by stable requested identity may be preferable to sharing registration tokens with nate-ntm.
- Removing fake Agent Mail behavior requires rewriting some Feature 001 tests and language, but retaining it would preserve the wrong architecture.
- The MVP will not wake idle agents when mail arrives. That limitation is explicit and acceptable until the later scheduler epic implements the embedded-monitor event path.

## Explicit Non-Goals

- Mailbox monitoring or polling in nate-oha.
- Agent-originated mailbox notifications over ACP or another control channel.
- Mailbox-driven or event-driven scheduling.
- Public mailbox state in nate-ntm runtime APIs.
- Git-remote clone construction.
- Runtime-side Agent Mail polling or message proxying.
- A generic secrets manager.
- Backward compatibility or migration for pre-revamp fake Agent Mail metadata.
- Direct UI access to `mcp_agent_mail`.