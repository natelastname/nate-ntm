# Design: Agent Mail Ownership Revamp

## Problem

nate-ntm currently models Agent Mail as a runtime-owned integration. The runtime creates or restores an Agent Mail project, allocates per-agent identities, polls unread mail, persists Agent Mail credentials, and feeds mailbox state into the scheduler.

That model duplicates responsibility already owned by nate-oha. nate-oha is the component that exposes the curated Agent Mail tools to the model, authenticates to mcp_agent_mail, ensures the project, registers the agent, and holds the per-agent registration token. Making nate-ntm a second Agent Mail client creates two lifecycle owners, two authentication paths, and two places where Agent Mail API changes must be reflected.

The existing design also assumes that an Agent Mail project is derived from a filesystem or Git identity and corresponds one-to-one with a swarm. That prevents clean creation of multiple independent swarms for the same repository and makes “discard this swarm and start over” ambiguous.

## Motivation

A swarm is an orchestration instance, not a repository. The system needs to support:

- multiple independent swarms using the same repository or remote;
- abandoning an old swarm and creating a clean replacement without inheriting its mail;
- explicit resume of one existing swarm with the same coordination namespace;
- one Agent Mail lifecycle owner per managed agent;
- future constructors that give each agent an isolated clone while preserving one swarm-scoped communication space.

Removing direct Agent Mail access from nate-ntm also keeps the runtime focused on orchestration: constructing workspaces, launching agents, supervising ACP connections, persisting swarm metadata, and exposing runtime state.

## Required Behavior

1. nate-ntm MUST NOT connect directly to mcp_agent_mail, call Agent Mail tools, register agents, poll inboxes, or store Agent Mail transport or registration secrets.
2. nate-oha MUST remain the sole Agent Mail client for each managed agent.
3. Creating a swarm MUST allocate a unique swarm instance identifier and a unique virtual Agent Mail project key independent of repository path, Git remote, and human-readable swarm name.
4. nate-ntm MUST pass the virtual project key and a stable requested Agent Mail identity to each nate-oha process through its launch configuration.
5. nate-oha MUST ensure the virtual project, register or restore its own Agent Mail identity, retain its registration token, and expose the curated Agent Mail facade to the model.
6. nate-oha MUST report resolved public Agent Mail state needed by the orchestrator, including its resolved Agent Mail name and mailbox-status changes, through the existing control connection or a narrowly defined extension of it.
7. nate-ntm MUST persist only orchestration metadata required to recreate the launch: virtual project key, requested Agent Mail identity, resolved public Agent Mail name when reported, nate-oha conversation identifier, workspace configuration, and constructor-specific state.
8. Resuming a swarm MUST reuse the existing swarm instance identifier, virtual Agent Mail project key, requested identities, workspaces, and conversations.
9. Creating a new swarm for the same repository MUST create a new swarm instance identifier and virtual Agent Mail project key by default, without checking for or reusing another swarm’s Agent Mail project.
10. Mailbox-driven scheduling MUST use status or wake events emitted by nate-oha. nate-ntm MUST NOT poll Agent Mail to infer unread state.
11. A temporary loss of Agent Mail connectivity MUST be represented as an agent-owned integration status and MUST NOT require a second runtime-owned Agent Mail client.
12. Existing fake Agent Mail adapters in nate-ntm MUST be removed rather than retained as compatibility abstractions.

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

An operator abandons swarm `01K...A` and creates a new swarm. nate-ntm leaves the old metadata and Agent Mail history untouched, creates a new swarm instance, and launches new nate-oha agents into the new virtual Agent Mail project.

### Resume

An operator resumes swarm `01K...A`. nate-ntm reloads the exact virtual project key and requested agent identities, recreates the same nate-oha launch configuration, and resumes the same OpenHands conversations. nate-oha restores or re-registers its Agent Mail identity within that project.

### Mail arrives while an agent is idle

nate-oha detects unread mail through its own Agent Mail integration and emits a mailbox-status or wake event over the control channel. nate-ntm updates runtime state and may schedule a new turn. nate-ntm never calls `fetch_inbox` itself.

### Git-remote clone swarm

A constructor creates one central Git remote and one clone per agent. Every nate-oha process receives:

- its clone as `openhands.workspace_root`;
- the same swarm-scoped virtual Agent Mail project key;
- its own stable requested Agent Mail identity.

Repository identity, workspace identity, swarm identity, and Agent Mail identity remain separate.

## Constraints

- The design MUST preserve one implementation path for Agent Mail ownership: nate-oha.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, or runtime-side inbox polling is retained.
- Agent Mail secrets MUST not be written into nate-ntm project metadata.
- The virtual Agent Mail project capability may require an upstream mcp_agent_mail change. nate-ntm must model the desired contract explicitly rather than reproducing path-based identity locally.
- Control-channel additions must remain narrow and agent-agnostic enough to support other agent runtimes later.
- The runtime must remain valid when Agent Mail is disabled for a particular agent type.

## Success Criteria

- nate-ntm has no production or fake dependency that invokes mcp_agent_mail.
- No nate-ntm metadata file contains an Agent Mail bearer token or per-agent registration token.
- Two new swarms created from the same repository receive different virtual Agent Mail project keys.
- Resuming a swarm reuses its previous virtual Agent Mail project key and requested identities.
- nate-oha is solely responsible for project creation, registration, inbox access, and model-facing Agent Mail tools.
- nate-ntm can display public Agent Mail identity and mailbox availability using events reported by nate-oha.
- Macro-level tests cover create, resume, start-over, and mailbox-wake behavior without mocking mcp_agent_mail inside nate-ntm.

## Scope

- Correct swarm, repository, workspace, and Agent Mail identity semantics.
- Remove runtime-owned Agent Mail adapters and polling.
- Add swarm-scoped virtual Agent Mail project metadata.
- Extend nate-oha launch configuration with explicit virtual project and requested identity values.
- Define the control-channel contract for resolved identity and mailbox status.
- Update create, resume, scheduler, status API, tests, and design documents.
- Define the upstream virtual-project requirement for mcp_agent_mail.

## Non-Goals

- Implement the Git-remote clone constructor itself; this epic prepares the identity and ownership model it requires.
- Add a second Agent Mail facade to nate-ntm.
- Store or proxy Agent Mail messages in nate-ntm.
- Make nate-ntm an Agent Mail credential broker.
- Preserve the old runtime-owned Agent Mail adapter interface.
- Implement generic distributed scheduling or multi-host execution.

## Terminology

- **Repository identity**: The source repository or Git remote containing the code.
- **Workspace identity**: The concrete directory assigned to one agent, such as its dedicated clone.
- **Swarm name**: A human-readable label that may be reused.
- **Swarm instance ID**: A unique durable identifier for one orchestration instance.
- **Virtual Agent Mail project key**: A swarm-scoped, non-filesystem coordination namespace, normally `nate-ntm:<swarm-instance-id>`.
- **Requested Agent Mail identity**: The stable name or identity hint nate-ntm supplies when launching nate-oha.
- **Resolved Agent Mail name**: The public identity returned after nate-oha registers with Agent Mail.
- **Mailbox wake event**: A nate-oha-originated control event indicating mailbox state that may require a new turn.

## Open Questions

1. What exact upstream API should create or ensure a virtual Agent Mail project: a new `ensure_project_by_key` tool or an explicit `virtual`/`literal` identity mode?
2. Does nate-oha already have a durable place for its registration token, or should it re-register idempotently on every process start?
3. Which control-channel mechanism should carry resolved identity and mailbox wake events: ACP session updates, custom JSON-RPC methods, or a nate-oha-specific event stream?
4. Should nate-ntm persist the resolved Agent Mail name, or treat it as runtime-observed state reconstructed after launch?
5. What mailbox condition should trigger a turn: any unread message, only new message IDs, explicit priority, or an agent-configurable policy?
