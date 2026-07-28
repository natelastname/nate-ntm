# Decision: Agent Mail Monitoring Belongs Inside nate-oha

## Status

Accepted for architecture; implementation deferred beyond the Agent Mail Ownership Revamp MVP.

## Context

nate-ntm was originally designed to poll Agent Mail directly so its scheduler could wake idle agents when messages arrived. That design requires nate-ntm to become a second Agent Mail client alongside nate-oha. It duplicates authentication, project resolution, agent registration, inbox access, retry logic, and compatibility with the upstream `mcp_agent_mail` API.

nate-oha already owns the per-agent Agent Mail lifecycle. It authenticates to the upstream service, ensures the project, registers the agent, retains the registration token, and exposes the curated model-facing facade. Mailbox observation therefore belongs with the same lifecycle owner.

## Decision

Future mailbox-driven scheduling will use an embedded Agent Mail monitor inside each nate-oha process.

The monitor is an asynchronous background task owned by nate-oha, not a separate sidecar process. It shares the same Agent Mail integration state and client used by the facade.

```text
nate-oha
├── OpenHands/ACP agent runtime
├── Agent Mail facade
└── embedded Agent Mail monitor
```

The monitor will observe mailbox state independently of model turns and report public state changes to nate-ntm over the existing control connection or a narrowly defined extension of it.

nate-ntm will remain the scheduler. nate-oha observes integration state; nate-ntm decides whether and when to start a turn.

```text
mail arrives
→ nate-oha observes a mailbox-state change
→ nate-oha emits a public notification
→ nate-ntm evaluates scheduling policy
→ nate-ntm starts a turn when eligible
```

## Why an Embedded Monitor

An embedded monitor preserves one Agent Mail implementation and one lifecycle owner. It can reuse nate-oha's authenticated client, resolved virtual project, registered identity, registration token, retry policy, and shutdown lifecycle.

A separate sidecar process would add another executable, another process lifecycle, another failure boundary, and another state-sharing mechanism without providing a corresponding architectural benefit.

A nate-ntm-owned monitor would be worse: it would require nate-ntm to possess or reconstruct Agent Mail credentials and identity state, recreating the duplicate integration this epic removes.

## Event Shape

The future control contract should expose state transitions rather than repeated polling snapshots. Candidate notifications include:

- `AgentMailIdentityResolved`
- `AgentMailMailboxChanged`
- `AgentMailIntegrationFailed`
- `AgentMailIntegrationRecovered`

Mailbox notifications should contain only public scheduling data, such as an unread count, mailbox cursor, newest message identifier, or observation timestamp. They must not contain transport bearer tokens, registration tokens, or message bodies unless a later feature explicitly requires them.

Both nate-oha and nate-ntm should deduplicate notifications because restarts and reconnects may replay observations.

## Startup and Resume

When nate-oha starts or resumes, it should eventually:

1. initialize its Agent Mail integration;
2. ensure the configured virtual project;
3. register or restore its Agent Mail identity;
4. start the embedded monitor;
5. emit an initial public mailbox snapshot;
6. continue emitting only meaningful state changes.

The initial snapshot allows a future scheduler to react to mail that accumulated while the agent process was stopped.

## Current Epic Boundary

This epic does not implement the monitor, unsolicited control notifications, mailbox-state propagation, deduplication, or event-driven wake scheduling.

The Agent Mail Ownership Revamp MVP is limited to:

- removing direct and fake Agent Mail clients from nate-ntm;
- introducing swarm-scoped virtual Agent Mail project identity;
- passing the virtual project key and requested identity to nate-oha;
- preserving those launch inputs across resume;
- ensuring Agent Mail secrets remain owned by nate-oha;
- documenting the upstream virtual-project requirement.

The monitoring architecture remains the accepted direction for a later scheduler epic.