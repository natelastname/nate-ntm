# Design: Agent Mail Ownership Revamp

## Problem

nate-ntm currently models Agent Mail as a runtime-owned integration. The runtime creates or restores an Agent Mail project, allocates per-agent identities, polls unread mail, persists Agent Mail credentials, and feeds mailbox state into the scheduler.

That model duplicates responsibility already owned by nate-oha. nate-oha is the component that exposes the curated Agent Mail tools to the model, authenticates to mcp_agent_mail, ensures the project, registers the agent, and holds the per-agent registration token. Making nate-ntm a second Agent Mail client creates two lifecycle owners, two authentication paths, and two places where Agent Mail API changes must be reflected.

The existing design also assumes that an Agent Mail project is derived from a filesystem or Git identity and corresponds one-to-one with a swarm. That prevents clean creation of multiple independent swarms for the same repository and makes “discard this swarm and start over” ambiguous.

A further design error would be to replace that repository-to-project assumption with a swarm-to-project assumption. Agent Mail project membership is part of an individual nate-oha instance's launch configuration. A constructor may choose to place every agent in one project, but the runtime does not require all agents in a swarm to share one Agent Mail project.

## Motivation

A swarm is an orchestration instance, not an Agent Mail namespace. The system needs to support:

- multiple independent swarms using the same repository or remote;
- abandoning an old swarm and creating a clean replacement without inheriting its mail;
- explicit resume of existing agents with the same launch configuration;
- one Agent Mail lifecycle owner per managed agent;
- agents with distinct Agent Mail enablement, project keys, identities, programs, models, and credentials;
- constructors that normally place agents in one shared coordination project without making that topology a runtime invariant;
- future constructors that give each agent an isolated clone while choosing whatever Agent Mail topology fits the swarm.

Removing direct Agent Mail access from nate-ntm keeps the runtime focused on orchestration: constructing workspaces, launching agents, supervising ACP connections, persisting agent launch metadata, and exposing runtime state.

## Required Behavior

1. nate-ntm MUST NOT connect directly to mcp_agent_mail, call Agent Mail tools, register agents, poll inboxes, or store Agent Mail transport or registration secrets.
2. nate-oha MUST remain the sole Agent Mail client for each managed agent.
3. Agent Mail enablement MUST be an agent-level property. A swarm MAY contain agents that do not use Agent Mail.
4. Each Agent Mail-enabled agent MUST have its own Agent Mail project key in its persisted launch configuration.
5. Each Agent Mail-enabled agent MUST have its own stable requested Agent Mail identity in its persisted launch configuration.
6. nate-ntm MUST pass that agent's project key and requested identity into that agent's nate-oha launch configuration.
7. nate-oha MUST ensure the configured project, register or restore its own Agent Mail identity, retain its registration token, and expose the curated Agent Mail facade to the model.
8. Agent-specific Agent Mail settings, including enablement, project key, requested identity, program, model metadata, and any agent-specific policy or prompt choice, MUST remain in the agent's launch configuration.
9. Agent Mail server connection settings and transport credential references MUST be treated as deployment or nate-oha configuration. They MUST NOT be persisted as swarm identity merely because several agents currently use the same server.
10. nate-ntm MAY carry opaque, non-secret configuration references required to construct nate-oha launch configuration, but it MUST NOT resolve, inspect, duplicate, or persist Agent Mail bearer tokens or per-agent registration tokens.
11. nate-ntm MUST persist only the orchestration metadata required to recreate each launch: swarm instance ID, per-agent Agent Mail enablement, per-agent project key, requested Agent Mail identity, nate-oha conversation identifier, workspace configuration, and constructor-specific state.
12. Resuming a swarm MUST recreate every agent with its previously persisted Agent Mail enablement, project key, requested identity, workspace, and conversation.
13. Creating a new swarm MUST create new agent launch specifications by default. A constructor MAY generate new virtual Agent Mail project keys, reuse explicit keys supplied by the operator, assign different keys to different agents, or disable Agent Mail for selected agents.
14. No runtime invariant may require all Agent Mail-enabled agents in a swarm to share the same Agent Mail project.
15. A swarm constructor MAY define a shared default project key and copy it into every new Agent Mail-enabled agent specification.
16. Existing real and fake Agent Mail adapters in nate-ntm MUST be removed rather than retained as compatibility abstractions.
17. Mailbox monitoring and mailbox-driven scheduling are explicitly outside the scope of this epic. Their accepted future ownership is documented in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md`.

## Configuration Ownership

Agent Mail configuration is divided by semantic ownership rather than stored wholesale at one level.

### Swarm-level

The swarm has no authoritative Agent Mail project field.

A swarm constructor may accept defaults such as a shared virtual project key, but those values are constructor inputs only. The constructor copies the effective value into each generated agent specification. After construction, each agent's launch configuration is authoritative.

### Agent-level

Each managed agent owns the Agent Mail settings that may differ between agents:

- `agent_mail_enabled`
- `agent_mail_project_key`
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

Given one repository at `/work/project`, a constructor may create two independent swarms and assign fresh virtual Agent Mail project keys to their agents:

```text
swarm instance: 01K...A
agent-a project: nate-ntm:01K...A
agent-b project: nate-ntm:01K...A

swarm instance: 01K...B
agent-a project: nate-ntm:01K...B
agent-b project: nate-ntm:01K...B
```

This is a useful constructor policy, not a swarm-level invariant. Both swarms may use the same repository or Git remote without seeing each other's Agent Mail messages.

### Agents with different Agent Mail projects

One swarm may contain:

```text
agent-a:
  Agent Mail enabled
  project key: project:implementation
  requested identity: implementer

agent-b:
  Agent Mail enabled
  project key: project:review
  requested identity: reviewer

agent-c:
  Agent Mail disabled
```

This topology is unusual but valid. nate-ntm launches each agent from its own persisted specification and does not attempt to reconcile or normalize project membership.

### Conventional shared-project swarm

A normal constructor may generate one virtual key and copy it into each Agent Mail-enabled agent:

```text
constructor default: nate-ntm:01K...A

agent-a.agent_mail_project_key = nate-ntm:01K...A
agent-b.agent_mail_project_key = nate-ntm:01K...A
agent-c.agent_mail_enabled = false
```

The shared project is therefore an outcome of construction, not a separate authoritative field that agents inherit dynamically.

### Shared server configuration

Several nate-oha processes may connect to the same Agent Mail server and may obtain credentials from the same environment or secret source. That does not make the server URL or credential a swarm identity field. A future deployment may route different agents through different servers or credential scopes without changing the swarm model.

### Discard and restart

An operator abandons an old swarm and creates a new swarm. The selected constructor creates new agent launch specifications. By default it may assign a new virtual project key to all new Agent Mail-enabled agents, while leaving the old Agent Mail history untouched.

### Resume

An operator resumes a swarm. nate-ntm reloads each agent's exact Agent Mail enablement, project key, and requested identity, recreates the same nate-oha launch configuration, and resumes the same OpenHands conversation. Each nate-oha instance restores or re-registers its own Agent Mail identity within its configured project.

### Git-remote clone swarm

A constructor creates one central Git remote and one clone per agent. It may also create one virtual Agent Mail project key and copy it into every Agent Mail-enabled agent specification. Each nate-oha process receives:

- its clone as `openhands.workspace_root`;
- its own persisted Agent Mail project key;
- its own requested Agent Mail identity and settings.

Repository identity, workspace identity, swarm identity, Agent Mail project membership, and Agent Mail agent identity remain separate.

## Constraints

- The design MUST preserve one implementation path for Agent Mail ownership: nate-oha.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, or runtime-side inbox polling is retained.
- Agent Mail secrets MUST not be written into nate-ntm project metadata.
- No Agent Mail value may be promoted to swarm-level identity merely because a constructor commonly gives that value to every agent.
- The virtual Agent Mail project capability may require an upstream mcp_agent_mail change. nate-ntm must model the desired contract explicitly rather than reproducing path-based identity locally.
- The runtime must remain valid when Agent Mail is disabled for a particular agent.
- The runtime must remain valid when Agent Mail-enabled agents in one swarm use different project keys.

## Success Criteria

- nate-ntm has no production or fake dependency that invokes mcp_agent_mail.
- No nate-ntm metadata file contains an Agent Mail bearer token or per-agent registration token.
- Every Agent Mail-enabled agent has an explicit project key in its persisted launch specification.
- Resuming a swarm recreates every agent with its previous Agent Mail project key and other effective launch settings.
- nate-oha is solely responsible for project creation, registration, inbox access, and model-facing Agent Mail tools.
- Agent Mail can be enabled or disabled independently per agent.
- Two agents in one swarm may use different Agent Mail project keys without violating runtime validation.
- A constructor may still produce the conventional topology where every enabled agent shares one new virtual project key.
- Macro-level tests cover create, resume, start-over, mixed Agent Mail enablement, heterogeneous project membership, and launch-configuration reconstruction without mocking mcp_agent_mail inside nate-ntm.

## Scope

- Correct repository, workspace, swarm, Agent Mail project, and Agent Mail identity semantics.
- Remove runtime-owned Agent Mail adapters and polling.
- Add explicit per-agent Agent Mail project-key, enablement, and requested-identity metadata.
- Extend nate-oha launch configuration with each agent's effective Agent Mail settings.
- Preserve those public launch inputs across resume.
- Define the upstream virtual-project requirement for mcp_agent_mail.
- Correct older Feature 001 assumptions that make nate-ntm an Agent Mail client or require one Agent Mail project per swarm.

## Non-Goals

- Mailbox monitoring or mailbox-driven scheduling.
- Custom ACP or JSON-RPC mailbox notifications.
- Implement the Git-remote clone constructor itself; this epic establishes the launch model that constructor will use.
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
- **Agent Mail project key**: An agent-level launch value identifying the Agent Mail project that one nate-oha instance joins. Several agents may share a key, but the runtime does not require them to do so.
- **Virtual Agent Mail project key**: A non-filesystem project key generated explicitly, commonly by a swarm constructor.
- **Agent Mail enablement**: An agent-level decision indicating whether that nate-oha instance should initialize Agent Mail.
- **Requested Agent Mail identity**: The stable per-agent name or identity hint nate-ntm supplies when launching nate-oha.
- **Deployment-level Agent Mail configuration**: Server, transport, retry, and secret-reference configuration owned by the execution environment or nate-oha rather than by swarm identity.
- **Resolved Agent Mail name**: The public identity returned after nate-oha registers with Agent Mail.

## Open Questions

1. What exact upstream API should create or ensure a virtual Agent Mail project: a new `ensure_project_by_key` tool or an explicit `virtual`/`literal` identity mode?
2. Does nate-oha already have a durable place for its registration token, or should it re-register idempotently on every process start?
3. Should nate-ntm model an opaque nate-oha configuration profile reference per agent, or should all non-secret nate-oha settings be materialized directly in each agent launch specification?
4. Which constructors should default all Agent Mail-enabled agents to one generated virtual project, and which should require project keys to be specified explicitly?