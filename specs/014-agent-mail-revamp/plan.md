# Implementation Plan: Agent Mail Ownership Revamp

## Summary

Refactor nate-ntm so it no longer acts as an Agent Mail client. nate-oha becomes the sole owner of Agent Mail transport authentication, virtual-project creation, agent registration, inbox access, and the model-facing facade. nate-ntm owns only swarm-scoped coordination identifiers, launch configuration, process supervision, ACP/control connections, workspace construction, and public runtime state reported by nate-oha.

The change deliberately removes the old Agent Mail adapter abstraction instead of adapting it. The resulting design establishes the identity model needed by future swarm constructors, especially a Git-remote constructor where every agent has an isolated clone but all agents share one virtual swarm mailbox namespace.

## User Stories

### US1 — Create an isolated swarm coordination namespace

**Priority**: P1

An operator can create a new swarm for a repository without reusing or discovering an existing Agent Mail project associated with that repository.

**Independent checkpoint**:

Creating two swarms for the same project path produces different `swarm_instance_id` and `agent_mail_project_key` values, and every agent launch in each swarm receives that swarm’s project key.

### US2 — Resume the same swarm identity

**Priority**: P1

An operator can resume an existing swarm and recreate each nate-oha process with the same virtual Agent Mail project key, requested identity, workspace, and conversation identifier.

**Independent checkpoint**:

Create a swarm, persist metadata, rebuild the runtime in resume mode, and verify that all public launch inputs are identical while no Agent Mail secret is present in nate-ntm metadata.

### US3 — Observe mailbox state without direct Agent Mail access

**Priority**: P1

The runtime can display an agent’s resolved Agent Mail name and mailbox state and can wake an idle agent when nate-oha reports new mail, without nate-ntm connecting to mcp_agent_mail.

**Independent checkpoint**:

Feed resolved-identity and mailbox-wake events through the control-channel adapter and verify runtime state, event streams, status APIs, and scheduler behavior with no Agent Mail client in the runtime.

### US4 — Launch nate-oha with one explicit Agent Mail owner

**Priority**: P2

Each managed nate-oha process receives enough configuration to ensure the virtual project and register or restore its own identity, while nate-ntm never receives the resulting registration token.

**Independent checkpoint**:

A macro launch test verifies the generated nate-oha configuration, the reported public identity, and the absence of direct mcp_agent_mail calls or stored secrets in nate-ntm.

## Technical Context

- Python package under `src/nate_ntm/` with Typer CLI, runtime daemon, scheduler, metadata store, ACP adapter, and WebSocket control API.
- Existing Agent Mail assumptions are concentrated in `src/nate_ntm/runtime/agent_mail_client.py`, `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, runtime metadata models, and tests under `tests/integration/runtime_mail/`.
- nate-oha already owns a curated Agent Mail facade and can ensure a project, register an agent, retain the registration token, and expose only safe tools to the model.
- mcp_agent_mail currently derives projects from filesystem or Git identities; this epic requires an upstream virtual-project contract.
- The implementation should use the existing ACP/control connection for agent-originated public integration events where practical.

## Architecture and Approach

### Ownership boundary

nate-ntm owns:

- swarm instance creation and resume;
- virtual Agent Mail project-key generation and persistence;
- requested per-agent identity generation and persistence;
- nate-oha launch configuration;
- workspace and Git topology;
- process supervision and control connections;
- public Agent Mail status reported by nate-oha;
- scheduler decisions based on reported events.

nate-oha owns:

- Agent Mail server authentication;
- virtual project ensure/create;
- agent registration or restoration;
- registration-token storage and use;
- inbox reads and all Agent Mail tool calls;
- model-facing facade policy;
- emission of resolved-identity and mailbox-status events.

### Identity model

Add a unique `swarm_instance_id` distinct from the reusable human-facing `swarm_id`. Generate the virtual project key from the unique instance:

```text
agent_mail_project_key = "nate-ntm:" + swarm_instance_id
```

Per-agent metadata carries a stable `requested_agent_mail_identity`. A resolved public Agent Mail name is runtime-observed state and may be persisted only if resume or UI requirements justify it; registration tokens are never persisted by nate-ntm.

### Control events

Introduce a narrow agent-originated integration event contract with at least:

- `AgentMailIdentityResolved`
- `AgentMailMailboxChanged`
- `AgentMailIntegrationFailed`
- `AgentMailIntegrationRecovered`

These events update `AgentRuntimeState`, append to the existing per-agent `AgentEventStream`, and may enqueue scheduler work. The contract must contain no transport bearer token or registration token.

### Scheduler

Remove runtime inbox polling. The scheduler reacts to mailbox events already attributed to an agent. It deduplicates wake events using an event or message cursor reported by nate-oha and starts a turn only when the agent is eligible.

### Upstream contract

Document and target one explicit virtual-project API in mcp_agent_mail. Preferred shape:

```text
ensure_project_by_key(project_key)
```

A `virtual` identity mode is acceptable if upstream strongly prefers one project tool, but nate-ntm must pass a non-filesystem swarm key and must not locally emulate project creation.

## Repository Changes

- Remove `src/nate_ntm/runtime/agent_mail_client.py`.
- Remove all `BaseAgentMailClient` and `FakeAgentMailClient` construction from `src/nate_ntm/runtime/daemon.py`, `src/nate_ntm/runtime/scheduler.py`, and tests.
- Extend `src/nate_ntm/runtime/metadata_store.py` with `swarm_instance_id`, `agent_mail_project_key`, and per-agent requested identity fields; remove runtime-owned Agent Mail credential fields.
- Extend `src/nate_ntm/runtime/state.py` with public Agent Mail runtime status only.
- Add or extend launch configuration code so each nate-oha process receives virtual project and requested identity values.
- Extend the ACP/control adapter and event translation in `src/nate_ntm/runtime/acp_client.py`, `src/nate_ntm/runtime/events.py`, and `src/nate_ntm/runtime/scheduler.py`.
- Update `src/nate_ntm/runtime/daemon.py` create/resume paths.
- Update `src/nate_ntm/api/server.py` response shaping for public Agent Mail state.
- Replace `tests/integration/runtime_mail/` tests with control-event and launch-boundary tests that do not instantiate mcp_agent_mail.
- Update Feature 001 documents where they still state that nate-ntm creates, polls, or owns Agent Mail identities.

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
    requested_agent_mail_identity: str
    conversation_id: str
    launch_config: object
```

The model may retain a resolved public Agent Mail name if needed, but must not contain server bearer tokens or registration tokens.

### Runtime state

```python
@dataclass
class AgentMailRuntimeStatus:
    resolved_name: str | None
    has_unread_mail: bool
    integration_status: str
    last_mail_cursor: str | None
    last_error: str | None
```

This is transient state populated from nate-oha events.

## Interfaces and Contracts

### nate-oha launch inputs

The launch adapter must be able to supply:

```text
Agent Mail enabled
Agent Mail upstream URL or credentials reference already understood by nate-oha
virtual project key
requested agent identity
model/program metadata
```

nate-ntm may carry opaque references needed to construct nate-oha configuration, but it must not read or persist resolved Agent Mail secrets.

### Agent-originated events

Every event includes:

```text
agent_id
event type
timestamp
public payload
```

Mailbox-change payloads should include enough information for deduplication and scheduling, preferably a cursor or latest message identifier, but not message bodies unless explicitly required by a future UI feature.

### Runtime API

`swarm.get_overview` and `agent.get_detail` may expose:

- resolved Agent Mail name;
- integration status;
- `has_unread_mail`;
- last public Agent Mail error summary.

They must not expose credentials.

## Validation Strategy

Use a small number of macro tests:

1. Create two swarms for one repository and verify distinct virtual project keys and launch configurations.
2. Resume one swarm and verify exact reuse of its project key, requested identities, workspaces, and conversations.
3. Feed nate-oha identity and mailbox events into a running runtime and verify API state, event streaming, deduplication, and scheduler wake behavior.
4. Inspect persisted metadata recursively and verify that no Agent Mail bearer token or registration token is present.
5. Verify that the nate-ntm package has no runtime import or invocation path for mcp_agent_mail.

Unit tests are appropriate only for deterministic key generation, metadata validation, and event translation where macro tests would obscure failures.

## Risks and Tradeoffs

- Mail-triggered scheduling depends on nate-oha emitting timely events. This is intentional; duplicating inbox polling in nate-ntm would violate the ownership boundary.
- A virtual-project API may not yet exist upstream. The epic should define the required contract and may temporarily block final integration on the upstream change.
- Registration restoration semantics must be finalized in nate-oha. Re-registration by stable requested name may be preferable to sharing registration tokens with nate-ntm.
- Extending ACP with custom events creates a nate-oha-specific surface. Keep the envelope generic and the payload narrow.
- Removing fake Agent Mail behavior will require rewriting some Feature 001 tests and language, but retaining it would preserve the wrong architecture.

## Explicit Non-Goals

- Git-remote clone construction.
- Runtime-side Agent Mail polling or message proxying.
- A generic secrets manager.
- Backward compatibility with persisted pre-revamp fake Agent Mail metadata.
- Automatic migration of abandoned development metadata.
- Direct UI access to mcp_agent_mail.
