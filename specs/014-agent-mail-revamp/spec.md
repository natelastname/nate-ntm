# Design: Agent Mail Ownership Revamp

## Problem

nate-ntm currently models Agent Mail as a runtime-owned integration. It creates or restores projects, allocates identities, simulates unread mail, and persists Agent Mail-oriented metadata.

That duplicates responsibility already owned by nate-oha. nate-oha authenticates to `mcp_agent_mail`, ensures the project, registers the agent, retains the registration token, and exposes the curated Agent Mail facade to the model.

The current model also treats an Agent Mail project as a filesystem- or Git-derived identity corresponding one-to-one with a repository. That prevents clean creation of multiple independent swarms for the same repository and makes “discard this swarm and start over” ambiguous.

## Motivation

A swarm is an orchestration instance, not a repository. The system must support:

- multiple independent swarms using the same repository or remote;
- abandoning a swarm and creating a clean replacement without inheriting its mail;
- explicitly resuming one existing swarm with the same coordination namespace;
- one Agent Mail lifecycle owner per managed agent;
- future constructors that assign isolated workspaces or clones while preserving one swarm-scoped communication namespace.

Removing Agent Mail access from nate-ntm keeps the runtime focused on orchestration: constructing workspaces, launching agents, supervising control connections, persisting swarm metadata, and exposing runtime state.

## Required Behavior

1. nate-ntm MUST NOT connect directly to `mcp_agent_mail`, call Agent Mail tools, register agents, poll inboxes, or retain Agent Mail transport or registration secrets.
2. nate-oha MUST remain the sole Agent Mail client for each managed agent.
3. Creating a swarm MUST allocate a unique durable swarm instance identifier and a unique virtual Agent Mail project key independent of repository path, Git remote, and reusable swarm name.
4. nate-ntm MUST pass the virtual project key and a stable requested Agent Mail identity to each nate-oha process through its launch configuration.
5. nate-oha MUST ensure the virtual project, register or restore its own Agent Mail identity, retain its registration token, and expose the curated facade.
6. nate-ntm MUST persist only the public orchestration metadata required to recreate the launch: swarm instance ID, virtual project key, requested Agent Mail identity, conversation ID, workspace configuration, and constructor-specific state.
7. Resuming a swarm MUST reuse its swarm instance ID, virtual Agent Mail project key, requested identities, workspaces, and conversations.
8. Creating another swarm for the same repository MUST create a new swarm instance ID and virtual Agent Mail project key by default without discovering or reusing another swarm’s Agent Mail project.
9. Existing fake Agent Mail adapters and runtime-owned Agent Mail metadata MUST be removed rather than retained as compatibility abstractions.
10. Agent Mail MUST remain optional for agent types that do not support or enable it.

## Scenarios and Examples

### Create two swarms for one repository

Given one repository at `/work/project`, creating swarms twice produces distinct coordination namespaces:

```text
swarm instance: 01K...A
Agent Mail project: nate-ntm:01K...A

swarm instance: 01K...B
Agent Mail project: nate-ntm:01K...B
```

Both swarms may use the same repository or Git remote without seeing each other’s Agent Mail messages.

### Discard and restart

An operator abandons swarm `01K...A` and creates a new swarm. nate-ntm leaves the old metadata and Agent Mail history untouched, creates a new swarm instance, and launches new nate-oha agents into a new virtual Agent Mail project.

### Resume

An operator resumes swarm `01K...A`. nate-ntm reloads the exact virtual project key and requested identities, reconstructs the same nate-oha launch configuration, and resumes the same OpenHands conversations. nate-oha restores or re-registers its own Agent Mail identity.

### Future Git-remote clone swarm

A future constructor may create one central Git remote and one clone per agent. Every nate-oha process receives:

- its clone as `openhands.workspace_root`;
- the same swarm-scoped virtual Agent Mail project key;
- its own stable requested Agent Mail identity.

Repository identity, workspace identity, swarm identity, and Agent Mail identity remain separate.

## Constraints

- The design MUST preserve one Agent Mail implementation path: nate-oha.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, or runtime-side inbox polling is retained.
- Agent Mail secrets MUST NOT be written into nate-ntm metadata, state, events, logs, or API responses.
- The virtual-project capability may require an upstream `mcp_agent_mail` change. nate-ntm must model the desired contract rather than reproducing path-based identity locally.
- The MVP MUST not depend on a mailbox watcher, unsolicited control notification, or event-driven scheduler.

## Success Criteria

- nate-ntm has no production or fake dependency that invokes `mcp_agent_mail`.
- No nate-ntm metadata contains an Agent Mail bearer token, registration token, or legacy credential field.
- Two swarms created from the same repository receive different virtual Agent Mail project keys.
- Resuming a swarm reuses its previous virtual project key and requested identities.
- Every Agent Mail-enabled nate-oha launch receives the correct virtual project key and requested identity.
- nate-oha remains solely responsible for project creation, registration, inbox access, credentials, and model-facing tools.
- Macro-level tests cover create, resume, start-over, launch propagation, and secret exclusion.

## Scope

- Correct swarm, repository, workspace, and Agent Mail identity semantics.
- Remove runtime-owned Agent Mail adapters, fake inbox state, and Agent Mail credential fields.
- Add swarm-scoped virtual Agent Mail project metadata.
- Extend nate-oha launch configuration with explicit virtual project and requested identity values.
- Update create and resume behavior and their macro tests.
- Define the upstream virtual-project requirement for `mcp_agent_mail`.
- Correct older Feature 001 documents where they assign Agent Mail ownership to nate-ntm.

## Non-Goals

- Implement mailbox monitoring or polling in nate-oha.
- Add unsolicited Agent Mail events to ACP or another control channel.
- Implement mailbox-driven or event-driven scheduling.
- Expose live mailbox state through nate-ntm APIs.
- Implement the Git-remote clone constructor; this epic only establishes the identity model it needs.
- Add an Agent Mail facade, credential broker, or message proxy to nate-ntm.
- Preserve or migrate the old runtime-owned Agent Mail adapter interface or development metadata.
- Implement generic distributed scheduling or multi-host execution.

The accepted future monitoring direction is documented in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md`.

## Terminology

- **Repository identity**: The source repository or Git remote containing the code.
- **Workspace identity**: The concrete directory assigned to one agent, such as a dedicated clone.
- **Swarm name**: A human-readable label that may be reused.
- **Swarm instance ID**: A unique durable identifier for one orchestration instance.
- **Virtual Agent Mail project key**: A swarm-scoped, non-filesystem coordination namespace, normally `nate-ntm:<swarm-instance-id>`.
- **Requested Agent Mail identity**: The stable name or identity hint nate-ntm supplies when launching nate-oha.
- **Resolved Agent Mail name**: The public name returned after nate-oha registers; it is not required by this MVP.

## Open Questions

1. What exact upstream API should create or ensure a virtual Agent Mail project: `ensure_project_by_key`, a `virtual` identity mode, or another explicit contract?
2. What exact nate-oha configuration fields should nate-ntm populate for the virtual project key and requested identity?
3. Should requested Agent Mail identities be derived deterministically from `agent_id`, explicitly supplied by constructors, or both?
4. Does nate-oha re-register idempotently on every process start, or restore registration state from its own durable storage?