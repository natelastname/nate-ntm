# Design: Revamp Agent Mail Swarm Construction

## Problem

nate-ntm currently treats Agent Mail as a runtime-owned integration. It creates or restores Agent Mail projects, allocates identities, polls inboxes, persists Agent Mail state, and exposes Agent Mail concepts through runtime scheduling and metadata.

That is the wrong ownership boundary. nate-oha already owns the model-facing Agent Mail facade and is the process that authenticates to mcp_agent_mail, ensures a project, registers an identity, retains registration state, and invokes Agent Mail tools.

However, nate-ntm still needs an Agent Mail swarm constructor. Constructing a coordinated swarm is an orchestration concern even though operating Agent Mail is not. The constructor must be revamped so it configures nate-oha instances without becoming an mcp_agent_mail client or introducing Agent Mail concepts into the runtime core.

## Decision

Agent Mail awareness is permitted only inside the Agent Mail swarm constructor.

The constructor chooses a coordination topology and uses nate-oha's public configuration surface to produce complete nate-oha launch configurations. For the normal topology, it creates one fresh virtual project key and configures every constructed nate-oha agent to join that project with an appropriate requested identity.

After construction, the generated nate-oha configurations are opaque launch artifacts. The nate-ntm runtime launches, persists, stops, and resumes them without interpreting their Agent Mail contents.

nate-oha remains the sole component that communicates with mcp_agent_mail.

## Motivation

This boundary preserves both requirements:

- nate-ntm can offer a convenient constructor that creates a functioning Agent Mail swarm;
- nate-oha remains the only Agent Mail client and lifecycle owner;
- starting a new swarm can produce a fresh virtual coordination project even when another swarm already uses the same repository;
- the runtime core remains independent of Agent Mail's API, credentials, identity rules, and persistence model;
- other constructors and agent runtimes are not forced to understand Agent Mail.

## Required Behavior

1. nate-ntm MUST retain and revamp the constructor that creates Agent Mail-enabled swarms.
2. The Agent Mail swarm constructor MAY understand Agent Mail coordination policy, but that knowledge MUST remain isolated from the runtime core.
3. The constructor MUST produce complete nate-oha launch configurations using a nate-oha-owned configuration API, schema, builder, or template. nate-ntm MUST NOT define a duplicate Agent Mail configuration model.
4. By default, each constructor invocation MUST generate a fresh virtual Agent Mail project key independent of repository path, Git remote, workspace path, and prior swarms.
5. By default, the constructor MUST configure every constructed agent to join the same generated virtual project.
6. The constructor MUST configure each agent with a stable requested identity or identity hint appropriate for that agent.
7. The constructor MAY accept an explicit project key or per-agent configuration overrides when requested by the operator. The runtime MUST remain valid if agents ultimately use different Agent Mail projects or no Agent Mail.
8. The constructor MUST NOT connect to mcp_agent_mail, ensure a project on the server, register an agent, fetch mail, inspect reservations, or receive registration tokens.
9. nate-oha MUST own Agent Mail enablement, server and transport configuration, project creation or ensure behavior, identity registration, credentials, tools, persistence, retries, and failure handling.
10. Once the constructor has produced a nate-oha launch configuration, nate-ntm MUST treat that configuration as an opaque launch artifact.
11. The runtime MUST NOT parse, validate, normalize, derive, copy, or expose Agent Mail-specific fields from generated nate-oha configurations.
12. The runtime MUST NOT contain a production, fake, mock, or compatibility Agent Mail client abstraction.
13. Resuming an agent MUST reuse its existing generic launch artifact and conversation state. Resume MUST NOT contain Agent Mail-specific restoration logic.
14. Starting over with the Agent Mail swarm constructor MUST generate new launch artifacts and a new virtual project key by default rather than discovering or reusing a project associated with the repository.
15. Existing Agent Mail-specific scheduler behavior, runtime state, metadata fields, API fields, adapters, and tests in nate-ntm MUST be removed rather than retained for compatibility.
16. Mailbox monitoring and mailbox-driven scheduling are outside this epic. The accepted future direction is documented in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md`.

## Constructor and Runtime Boundary

### Agent Mail swarm constructor owns

- selecting the Agent Mail swarm topology;
- generating or accepting a virtual project key;
- choosing requested per-agent identities;
- applying those choices through nate-oha's public configuration surface;
- producing one complete nate-oha launch artifact per agent;
- configuring agent workspaces and other constructor-owned swarm inputs.

The constructor performs configuration composition only. It does not verify the project or identities against a running Agent Mail server.

### nate-ntm runtime owns

- swarm and agent lifecycle;
- workspace construction and constructor-specific Git state;
- generic launch artifacts or references;
- process supervision;
- ACP or control connections;
- conversation identifiers;
- generic runtime and scheduler state.

The runtime does not know whether a launch artifact enables Agent Mail.

### nate-oha owns

- interpreting its Agent Mail configuration;
- Agent Mail server and transport configuration;
- virtual-project ensure or creation semantics;
- requested and resolved identities;
- registration tokens and authentication state;
- Agent Mail tools and model-facing policy;
- Agent Mail retries, failures, and recovery;
- any future embedded mailbox monitor.

## Configuration Ownership

The constructor must use nate-oha's configuration implementation rather than reproducing it.

A preferred shape is conceptually:

```python
launch_config = nate_oha.build_config(
    workspace_root=agent_workspace,
    agent_mail=nate_oha.AgentMailConfig(
        project_key=virtual_project_key,
        requested_identity=agent_identity,
    ),
)
```

The exact API is determined by nate-oha. The important constraint is that the Agent Mail configuration type, validation, defaults, and serialization have one owner: nate-oha.

nate-ntm may persist the resulting launch artifact or an opaque reference needed to reproduce it. It must not extract Agent Mail fields into parallel swarm or agent metadata.

## Scenarios and Examples

### Create a conventional Agent Mail swarm

The constructor is invoked for three agents:

```text
constructor invocation: NEW
virtual project key: nate-ntm:<new-unique-id>

agent-a nate-oha config -> same virtual project, identity architect
agent-b nate-oha config -> same virtual project, identity implementer
agent-c nate-oha config -> same virtual project, identity reviewer
```

nate-ntm does not contact mcp_agent_mail. Each nate-oha process ensures the project and registers itself when launched.

### Start over in the same repository

The constructor is invoked again for the same repository. It generates a different virtual project key and new nate-oha launch artifacts. The new agents do not inherit the old swarm's Agent Mail history unless the operator explicitly supplies the old project key.

### Resume

nate-ntm reloads each agent's generic launch artifact and conversation state. nate-oha interprets its own configuration and restores or re-establishes Agent Mail state.

### Heterogeneous topology

An operator supplies overrides so two agents use different Agent Mail projects and a third does not use Agent Mail. The constructor can produce those nate-oha configurations, and the runtime launches all three through the same generic lifecycle path.

### Future Git-remote clone constructor

A constructor creates one clone per agent, generates one virtual Agent Mail project key, and uses nate-oha's configuration surface to pair each clone with that project. Git topology remains constructor-owned; Agent Mail operation remains nate-oha-owned.

## Intentional Divergence from Original NTM

The original NTM directly integrates with Agent Mail: its spawn path ensures projects and registers session and pane identities, while its CLI and runtime expose inbox, send, reservation, status, and recovery behavior.

nate-ntm deliberately adopts a narrower architecture:

- retain Agent Mail-aware swarm construction;
- remove direct Agent Mail runtime integration;
- delegate all server communication and per-agent Agent Mail lifecycle to nate-oha.

## Constraints

- There MUST be one implementation owner for Agent Mail configuration and behavior: nate-oha.
- The Agent Mail swarm constructor MUST use that implementation rather than duplicating its schema or defaults.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, runtime inbox polling, or Agent Mail runtime metadata is retained.
- No Agent Mail-specific runtime type, field, validation rule, scheduler path, or API contract may remain in nate-ntm for the MVP.
- Constructor-generated virtual project keys are configuration inputs, not evidence that nate-ntm owns or has created a server-side project.
- The runtime must remain correct regardless of the Agent Mail topology encoded in individual nate-oha launch artifacts.
- The constructor may depend on virtual-project support exposed through nate-oha, but nate-ntm must not implement mcp_agent_mail's project semantics itself.

## Success Criteria

- nate-ntm contains an Agent Mail swarm constructor that produces usable nate-oha launch artifacts.
- Two default constructor invocations for the same repository produce different virtual project keys.
- All agents from one default constructor invocation are configured for the same virtual project.
- The constructor uses nate-oha-owned configuration types or builders rather than a duplicate nate-ntm Agent Mail model.
- nate-ntm has no runtime dependency on mcp_agent_mail.
- nate-ntm contains no real, fake, or abstract Agent Mail client.
- nate-ntm runtime metadata and API state contain no extracted Agent Mail-specific fields.
- create, stop, and resume work without an Agent Mail-specific runtime code path.
- nate-oha remains solely responsible for server communication, project ensure behavior, registration, credentials, tools, and failures.
- Macro-level tests cover constructor output, fresh-start isolation, opaque resume, and removal of the old runtime integration.

## Scope

- Revamp the Agent Mail swarm constructor.
- Generate fresh virtual project keys for new Agent Mail swarms by default.
- Build nate-oha launch artifacts through nate-oha's public configuration surface.
- Remove runtime-owned Agent Mail clients and adapters.
- Remove Agent Mail-specific runtime metadata, state, scheduling, API fields, configuration, and validation.
- Remove fake Agent Mail behavior and tests that depend on it.
- Ensure launch and resume remain driven by generic opaque launch artifacts.
- Correct older Feature 001 requirements and documentation that assign runtime Agent Mail responsibilities to nate-ntm.
- Preserve the future monitoring decision without implementing it.

## Non-Goals

- Connect to mcp_agent_mail from nate-ntm.
- Ensure projects or register identities from the constructor.
- Implement virtual-project behavior inside nate-ntm rather than nate-oha or mcp_agent_mail.
- Change nate-oha's registration-token persistence beyond what the constructor contract requires.
- Monitor mailboxes or implement mailbox-driven scheduling.
- Add custom ACP or JSON-RPC mailbox notifications.
- Implement the Git-remote clone constructor itself.
- Preserve compatibility with old Agent Mail runtime metadata or adapters.
- Expose Agent Mail state through nate-ntm APIs.

## Terminology

- **Agent Mail swarm constructor**: A nate-ntm constructor that produces a coordinated set of nate-oha launch configurations with an intended Agent Mail topology.
- **Virtual project key**: A non-filesystem Agent Mail project identifier placed into nate-oha configuration; it does not imply that nate-ntm has created the server-side project.
- **Generic launch artifact**: The runtime-owned file, reference, or serialized input required to start a managed agent process without integration-specific interpretation.
- **Opaque nate-oha configuration**: A nate-oha-owned configuration artifact that nate-ntm may launch or persist but does not inspect after construction.
- **Agent Mail ownership**: Responsibility for configuration semantics, connection, project ensure behavior, identity registration, credentials, tools, persistence, and failure handling.

## Open Questions

1. What nate-oha public API should the constructor use to create and serialize complete launch configurations?
2. Should the constructor generate requested Agent Mail identities from nate-ntm agent names, roles, or a nate-oha identity helper?
3. What exact virtual-project API will nate-oha expose once mcp_agent_mail supports explicit non-filesystem projects?
4. Should an explicit project-key override be available in the MVP, or should the first version always generate a fresh shared key?
5. What generic launch artifact should nate-ntm persist for reliable resume: a generated configuration file, profile reference, or another existing mechanism?
