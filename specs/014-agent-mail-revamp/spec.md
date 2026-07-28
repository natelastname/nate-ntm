# Design: Remove Agent Mail Ownership from nate-ntm

## Problem

nate-ntm currently models Agent Mail as part of the swarm runtime. It creates or restores Agent Mail projects, allocates identities, polls inboxes, persists Agent Mail-related state, and exposes Agent Mail concepts through runtime scheduling and metadata.

That is the wrong ownership boundary. nate-oha already owns the model-facing Agent Mail facade and is the process that authenticates to mcp_agent_mail, chooses or ensures a project, registers an identity, retains registration state, and invokes Agent Mail tools.

Keeping any Agent Mail-specific configuration or lifecycle model in nate-ntm creates duplicate ownership and forces nate-ntm to understand an integration that belongs entirely to the managed agent runtime.

## Motivation

nate-ntm should orchestrate agent processes, not reimplement their integrations.

The runtime needs to know how to construct, launch, stop, inspect, and resume a nate-oha process. It does not need to know:

- whether that process uses Agent Mail;
- which Agent Mail server it uses;
- which Agent Mail project it joins;
- which Agent Mail identity it requests or receives;
- how it authenticates;
- how it persists registration state;
- which Agent Mail tools or policies it exposes.

Those are nate-oha concerns. Different agents in the same swarm may use the same Agent Mail project, different projects, or no Agent Mail at all without requiring any special representation in nate-ntm.

## Required Behavior

1. nate-ntm MUST NOT connect directly to mcp_agent_mail or invoke any Agent Mail operation.
2. nate-ntm MUST NOT create, derive, ensure, discover, validate, or persist Agent Mail project identifiers.
3. nate-ntm MUST NOT allocate, validate, or persist Agent Mail identities.
4. nate-ntm MUST NOT store Agent Mail transport credentials, registration tokens, secret references, server URLs, retry settings, tool policy, or other Agent Mail-specific configuration.
5. nate-ntm MUST NOT model Agent Mail enablement as swarm metadata, agent metadata, runtime state, or API state.
6. nate-ntm MUST NOT contain a production, fake, mock, or compatibility Agent Mail client abstraction.
7. nate-oha MUST be the sole owner of Agent Mail configuration, authentication, project selection, registration, persistence, tools, and failure handling for its process.
8. nate-ntm MUST launch nate-oha using the same generic agent-launch mechanism used for all other nate-oha configuration.
9. Any nate-oha configuration file, profile, command argument, or environment supplied to an agent MUST be treated as an opaque launch input by nate-ntm. nate-ntm MUST NOT parse or reconstruct Agent Mail-specific fields from it.
10. Resuming an agent MUST reuse its generic launch specification and conversation state. Resume MUST NOT contain Agent Mail-specific restoration logic.
11. Agents in one swarm MAY use different nate-oha configurations. nate-ntm MUST NOT infer that they share integrations merely because they belong to one swarm.
12. Existing Agent Mail-specific scheduler behavior, runtime state, metadata fields, API fields, adapters, and tests in nate-ntm MUST be removed rather than retained for compatibility.
13. Mailbox monitoring and mailbox-driven scheduling are outside this epic. The accepted future direction is documented in `specs/014-agent-mail-revamp/agent-mail-monitoring-decision.md`.

## Ownership Boundary

### nate-ntm owns

- swarm and agent lifecycle;
- workspace construction;
- generic nate-oha launch specifications;
- process supervision;
- ACP or control connections;
- conversation identifiers;
- generic runtime and scheduler state;
- constructor-specific workspace and Git state.

### nate-oha owns

- whether Agent Mail is enabled;
- Agent Mail server and transport configuration;
- Agent Mail project selection, including virtual-project semantics;
- Agent Mail requested and resolved identities;
- registration tokens and authentication state;
- Agent Mail tools and model-facing policy;
- Agent Mail retries, failures, and recovery;
- any future embedded mailbox monitor.

The boundary is behavioral, not merely structural: nate-ntm must not gain knowledge of Agent Mail configuration by embedding it in otherwise generic metadata.

## Scenarios and Examples

### Agents use one shared Agent Mail project

Three nate-oha configurations happen to select the same Agent Mail project. nate-ntm launches the three agents from their configured launch specifications and has no representation of the shared project.

### Agents use different Agent Mail projects

Two agents in one swarm use nate-oha configurations that select different Agent Mail projects. nate-ntm launches both normally. No swarm invariant is violated because Agent Mail project membership is not part of the nate-ntm model.

### Agent Mail is disabled

A nate-oha configuration does not enable Agent Mail. nate-ntm does not need a flag or alternate code path; it launches the agent exactly as it launches any other configured nate-oha process.

### Start over

An operator discards an old swarm and creates another. The new agents receive whatever nate-oha launch configurations the selected constructor or operator provides. nate-ntm does not search for, reuse, clear, or create Agent Mail projects.

### Resume

An operator resumes a swarm. nate-ntm restores each agent's generic launch specification, workspace, and conversation state. nate-oha restores its own integrations, including Agent Mail when configured.

### Future Git-remote clone constructor

A constructor creates one clone per agent and supplies a nate-oha launch specification for each clone. The constructor does not need an Agent Mail-specific runtime contract. Any desired Agent Mail topology is represented entirely by the nate-oha configurations supplied to those agents.

## Constraints

- There MUST be one implementation path for Agent Mail ownership: nate-oha.
- No compatibility layer for `BaseAgentMailClient`, `FakeAgentMailClient`, runtime inbox polling, or Agent Mail metadata is retained.
- No Agent Mail-specific type, field, validation rule, or API contract may remain in nate-ntm merely to support future scheduling.
- Generic launch configuration must remain generic. An opaque nate-oha configuration reference is acceptable; an Agent Mail-aware nate-ntm configuration object is not.
- The runtime must remain correct regardless of the Agent Mail topology chosen by individual nate-oha processes.
- This epic must not depend on adding virtual-project support to mcp_agent_mail. That capability belongs to nate-oha and mcp_agent_mail work, not to nate-ntm.

## Success Criteria

- nate-ntm has no runtime dependency on mcp_agent_mail.
- nate-ntm contains no real, fake, or abstract Agent Mail client.
- nate-ntm metadata and runtime state contain no Agent Mail-specific fields.
- nate-ntm APIs expose no Agent Mail-specific fields in the MVP.
- create, stop, and resume work without any Agent Mail-specific code path.
- agents using the same project, different projects, or no Agent Mail all require the same nate-ntm lifecycle path.
- nate-oha remains solely responsible for all Agent Mail behavior.
- Macro-level tests verify lifecycle behavior after deleting the old Agent Mail integration and assert that no Agent Mail-specific runtime surface remains.

## Scope

- Remove runtime-owned Agent Mail clients and adapters.
- Remove Agent Mail-specific metadata, state, scheduling, API fields, configuration, and validation from nate-ntm.
- Remove fake Agent Mail behavior and tests that depend on it.
- Ensure nate-oha launch and resume remain driven by generic agent-launch specifications.
- Correct older Feature 001 requirements and documentation that assign Agent Mail responsibilities to nate-ntm.
- Preserve the future monitoring decision without implementing it.

## Non-Goals

- Define or implement virtual Agent Mail projects.
- Configure Agent Mail inside nate-oha.
- Change nate-oha registration or credential persistence.
- Monitor mailboxes or implement mailbox-driven scheduling.
- Add custom ACP or JSON-RPC mailbox notifications.
- Implement the Git-remote clone constructor.
- Preserve compatibility with old Agent Mail metadata or adapters.
- Expose Agent Mail state through nate-ntm APIs.

## Terminology

- **Generic agent launch specification**: The runtime-owned information required to start a managed agent process, without integration-specific interpretation.
- **Opaque nate-oha configuration**: A nate-oha-owned configuration file, profile, argument set, or environment source that nate-ntm may pass to the process but does not inspect semantically.
- **Agent Mail ownership**: Responsibility for Agent Mail configuration, connection, project selection, identity, credentials, tools, persistence, and failure handling.

## Open Questions

1. What is the minimal generic nate-oha launch reference that nate-ntm should persist for reliable resume: a configuration path, profile name, serialized generic launch command, or another existing mechanism?
2. Which existing Feature 001 runtime fields and API responses are Agent Mail-specific and must be deleted?
3. Should the future mailbox event contract be designed as a generic agent-originated event mechanism so nate-ntm remains unaware of Agent Mail semantics?