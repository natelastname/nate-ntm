# Design: Agent Mail Ownership Revamp

## Problem

nate-ntm currently models Agent Mail as a runtime-owned integration. The runtime creates or restores an Agent Mail project, allocates per-agent identities, polls unread mail, persists Agent Mail credentials, and feeds mailbox state into the scheduler.

That model duplicates responsibility already owned by nate-oha. nate-oha is the component that exposes the curated Agent Mail tools to the model, authenticates to mcp_agent_mail, ensures the project, registers the agent, and holds the per-agent registration token. Making nate-ntm a second Agent Mail client creates two lifecycle owners, two authentication paths, and two places where Agent Mail API changes must be reflected.

The existing design also assumes that an Agent Mail project is derived from a filesystem or Git identity and corresponds one-to-one with a swarm. That prevents clean creation of multiple independent swarms for the same repository and makes “discard this swarm and start over” ambiguous.

A further design error would be to move all Agent Mail configuration into swarm metadata merely because the coordination namespace is shared. Agent Mail has shared, per-agent, and deployment-level concerns. Only the values whose semantics are genuinely shared by every Agent Mail-enabled agent belong at the swarm level.

## Motivation

A swarm is an orchestration instance, not a repository. The system needs to support:

- multiple independent swarms using the same repository or remote;
- abandoning an old swarm and creating a clean replacement without inheriting its mail;
- explicit resume of one existing swarm with the same coordination namespace;
- one Agent Mail lifecycle owner per managed agent;
- agents with distinct Agent Mail enablement, identities, programs, models, and credentials;
- future constructors that give each agent an isolated clone while preserving one swarm-scoped communication space.

Removing direct Agent Mail access from nate-ntm keeps the runtime focused on orchestration: constructing workspaces, launching agents, supervising ACP connections, persisting swarm metadata, and exposing runtime state.

## Required Behavior

1. nate-ntm MUST NOT connect directly to mcp_agent_mail, call Agent Mail tools, register agents, poll inboxes, or store Agent Mail transport or registration secrets.
2. nate-oha MUST remain the sole Agent Mail client for each managed agent.
3. Creating a swarm MUST allocate a unique swarm instance identifier and a unique virtual Agent Mail project key independent of repository path, Git remote, and human-readable swarm name.
4. The virtual Agent Mail project key MUST be swarm-level metadata because it identifies the shared coordination namespace used by all Agent Mail-enabled agents in that swarm.
5. Agent Mail enablement MUST be an agent-level property. A swarm MAY contain agents that do not use Agent Mail.
6. Each Agent Mail-enabled agent MUST have its own stable requested Agent Mail identity in agent metadata.
7. nate-ntm MUST pass the swarm’s virtual project key and the agent’s requested identity into that agent’s nate-oha launch configuration.
8. nate-oha MUST ensure the virtual project, register or restore its own Agent Mail identity, retain its registration token, and expose the curated Agent Mail facade to the model.
9. Agent-specific Agent Mail settings, including enablement, requested identity, program, model metadata, and any agent-specific policy or prompt choice, MUST remain in the agent’s launch configuration rather than being promoted into swarm metadata.
10. Agent Mail server connection settings and transport credential references MUST be treated as deployment or nate-oha configuration. They MUST NOT be persisted as swarm identity merely because every agent currently uses the same server.
11. nate-ntm MAY carry opaque, non-secret configuration references required to construct nate-oha launch configuration, but it MUST NOT resolve, inspect, duplicate, or persist Agent Mail bearer tokens or per-agent registration tokens.
12. nate-ntm MUST persist only the orchestration metadata required to recreate each launch: swarm instance ID, virtual project key, per-agent Agent Mail enablement, requested Agent Mail identity, nate-oha conversation identifier, workspace configuration, and constructor-specific state.
13. Resuming a swarm MUST reuse the existing swarm instance identifier, virtual Agent Mail project key, per-agent Agent Mail enablement, requested identities, workspaces, and conversations.
14. Creating a new swarm for the same repository MUST create a new swarm instance identifier and virtual Agent Mail project key by default, without checking for or reusing another swarm’s Agent Mail project.
15. Existing real and fake Agent Mail adapters in nate-ntm MUST be removed rather than retained as compatibility abstractions.
16. Mailbox monitoring and mailbox-driven scheduling are explicitly outside the scope of this epic. Their accepted future ownership is documented in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md`.

## Configuration Ownership

Agent Mail configuration is divided by semantic ownership rather than stored wholesale at one level.

### Swarm-level

The swarm owns only values that define shared coordination identity:

- `agent_mail_project_key`
- optional swarm-wide defaults used solely to initialize new agent specifications

A default is not authoritative agent configuration. Once an agent specification is created, its effective settings are stored with that agent.

### Agent-level

Each managed agent owns the Agent Mail settings that may differ between agents:

- `agent_mail_enabled`
- `requested_agent_mail_identity`
- Agent Mail program and model metadata supplied during registration
- model-facing prompt or tool-policy selection
- any future per-agent Agent Mail behavior

These values are part of the nate-oha launch specification and are restored per agent on resume.

### Deployment or nate-oha-level

The execution environment or nate-oha configuration owns connection and secret-bearing settings:

- Agent Mail upstream URL
- transport authentication configuration
- bearer-token or secret references
- retry, timeout, and client transport details
- per-agent registration token after registration

These settings do not define swarm identity. nate-ntm should pass through an opaque launch-config source or rely on the environment already used by nate-oha, rather than copying them into swarm metadata.

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

### Agents with different Agent Mail settings

One swarm may contain:

```text
agent-a:
  Agent Mail enabled
  requested identity: architect

agent-b:
  Agent Mail enabled
  requested identity: implementer

agent-c:
  Agent Mail disabled
```

The enabled agents receive the same swarm-level virtual project key but retain separate agent-level identities and configuration. The disabled agent receives no Agent Mail launch configuration.

### Shared server configuration

Several nate-oha processes may connect to the same Agent Mail server and may obtain credentials from the same environment or secret source. That does not make the server URL or credential a swarm identity field. A future deployment may route different agents through different servers or credential scopes without changing the swarm model.

### Discard and restart

An operator abandons swarm `01K...A` and creates a new swarm. nate-ntm leaves the old metadata and Agent Mail history untouched, creates a new swarm instance, and launches new nate-oha agents into the new virtual Agent Mail project.

### Resume

An operator resumes swarm `01K...A`. nate-ntm reloads the exact virtual project key and each agent’s Agent Mail enablement and requested identity, recreates the same nate-oha launch configuration, and resumes the same OpenHands conversations. Each nate-oha instance restores or re-registers its own Agent Mail identity within that project.

### Git-remote clone swarm

A constructor creates one central Git remote and one clone per agent. Every Agent Mail-enabled nate-oha process receives:

- its clone as `openhands.workspace_root`;
- the same swarm-scoped virtual Agent Mail project key;
- its own agent-level requested Agent Mail identity and settings.

Repository identity, workspace identity, swarm identity, and Agent Mail identity remain separate.

## Constraints

- The design MUST preserve one implementation path for Agent Mail ownership: nate-oha.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, or runtime-side inbox polling is retained.
- Agent Mail secrets MUST not be written into nate-ntm project metadata.
- Shared current values MUST NOT be promoted to swarm-level identity unless their semantics are inherently swarm-wide.
- The virtual Agent Mail project capability may require an upstream mcp_agent_mail change. nate-ntm must model the desired contract explicitly rather than reproducing path-based identity locally.
- The runtime must remain valid when Agent Mail is disabled for a particular agent.

## Success Criteria

- nate-ntm has no production or fake dependency that invokes mcp_agent_mail.
- No nate-ntm metadata file contains an Agent Mail bearer token or per-agent registration token.
- Two new swarms created from the same repository receive different virtual Agent Mail project keys.
- Resuming a swarm reuses its previous virtual Agent Mail project key and each agent’s effective Agent Mail launch settings.
- nate-oha is solely responsible for project creation, registration, inbox access, and model-facing Agent Mail tools.
- Agent Mail can be enabled or disabled independently per agent.
- The swarm metadata contains the shared virtual project key but does not absorb agent-specific policy or deployment-level connection configuration.
- Macro-level tests cover create, resume, start-over, mixed Agent Mail enablement, and launch-configuration reconstruction without mocking mcp_agent_mail inside nate-ntm.

## Scope

- Correct swarm, repository, workspace, and Agent Mail identity semantics.
- Remove runtime-owned Agent Mail adapters and polling.
- Add swarm-scoped virtual Agent Mail project metadata.
- Add explicit per-agent Agent Mail enablement and requested identity metadata.
- Extend nate-oha launch configuration with the effective swarm-level project key and agent-level settings.
- Preserve those public launch inputs across resume.
- Define the upstream virtual-project requirement for mcp_agent_mail.
- Correct older Feature 001 assumptions that make nate-ntm an Agent Mail client.

## Non-Goals

- Mailbox monitoring or mailbox-driven scheduling.
- Custom ACP or JSON-RPC mailbox notifications.
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
- **Agent Mail enablement**: An agent-level decision indicating whether that nate-oha instance should initialize Agent Mail.
- **Requested Agent Mail identity**: The stable per-agent name or identity hint nate-ntm supplies when launching nate-oha.
- **Deployment-level Agent Mail configuration**: Server, transport, retry, and secret-reference configuration owned by the execution environment or nate-oha rather than by swarm identity.
- **Resolved Agent Mail name**: The public identity returned after nate-oha registers with Agent Mail.

## Open Questions

1. What exact upstream API should create or ensure a virtual Agent Mail project: a new `ensure_project_by_key` tool or an explicit `virtual`/`literal` identity mode?
2. Does nate-oha already have a durable place for its registration token, or should it re-register idempotently on every process start?
3. Should nate-ntm model an opaque nate-oha configuration profile reference per agent, or should all non-secret nate-oha settings be materialized directly in each agent launch specification?
4. Should swarm constructors be allowed to define Agent Mail defaults for new agents, provided those defaults are copied into agent specifications rather than treated as authoritative swarm configuration?
