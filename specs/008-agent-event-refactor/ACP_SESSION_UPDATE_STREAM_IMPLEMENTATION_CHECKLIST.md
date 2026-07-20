# Phase 1 — Core Types & Stream

## Runtime Types

- [x] Introduce `src/nate_ntm/runtime/acp_types.py`
- [x] Define canonical `SessionUpdate` runtime type alias
- [x] Centralize ACP SDK imports through `acp_types.py`

## Stream Types

- [x] Create `ReceivedSessionUpdate`
- [x] Include:
  - [x] `sequence`
  - [x] `received_at`
  - [x] `update`
- [x] Keep `ReceivedSessionUpdate` immutable (`frozen=True`)

## Error Hierarchy

- [x] `AcpUpdateStreamError`
- [x] `StreamClosedError`
- [x] `SubscriberOverflowError`
- [x] `AgentSessionNotActive`

---

# Phase 2 — AcpSessionUpdateStream

## Stream Ownership

- [x] Implement `AcpSessionUpdateStream`
- [x] One stream per concrete `AcpAgentSession`
- [x] Never share streams between sessions

## Publishing

- [x] `publish()`
- [x] Assign sequence numbers internally
- [x] Monotonic sequence starting at 1
- [x] Reject publish after close

## Replay Buffer

- [x] Bounded retained history
- [x] Configurable history size
- [x] Oldest entries evicted first

## Subscription

- [x] Async context manager API
- [x] Replay retained history
- [x] Atomic transition to live stream
- [x] No replay/live duplicates
- [x] No replay/live gaps

## Live Delivery

- [x] Independent queue per subscriber
- [x] Configurable queue size
- [x] Subscribers do not interfere with one another

## Overflow

- [x] Detect subscriber overflow
- [x] Raise `SubscriberOverflowError`
- [x] No silent data loss
- [x] Overflow isolated to one subscriber

## Closure

- [x] Idempotent `close()`
- [x] Preserve optional close error
- [x] Existing subscribers drain queued events
- [x] New subscribers receive retained snapshot
- [x] Publish-after-close raises `StreamClosedError`

---

# Phase 3 — Session Integration

## AcpAgentSession

- [x] Add `update_stream`
- [x] Allocate stream during session creation
- [x] Close stream during shutdown
- [ ] Close stream during replacement
- [x] Never store stream on `AgentRuntimeState`

## ACP Callback Path

Canonical path:
```
ProtocolClient.session_update()
↓
BaseAcpClient._on_session_update()
↓
AcpSessionUpdateStream.publish()
```

Checklist:

- [x] Single publication path
- [x] No generic event envelopes
- [x] No serialization
- [x] Reject stale callbacks
- [x] Preserve typed `SessionUpdate`

---

# Phase 4 — Adapter API

## subscribe_acp_updates()

- [x] Implement API
- [x] Resolve current session once
- [x] Bind to concrete session
- [x] Delegate to `update_stream.subscribe()`
- [x] Raise `AgentSessionNotActive` if missing
- [x] Raise `AgentSessionNotActive` if inactive
- [x] Do not follow replacement sessions
- [x] Replay retained history after stream closure
- [x] Naturally terminate after replay on closed streams

## Canonical Subscription API

- [x] All ACP-aware consumers use `subscribe_acp_updates()`
- [x] Compatibility wrappers delegate only
- [x] No second replay implementation
- [x] No second subscriber registry
- [x] No second buffering implementation

---

# Runtime Invariants

## Session Ownership

- [x] Exactly one stream per session
- [x] Stream lifetime equals session lifetime

## Sequencing

- [x] Sequence numbers local to one session
- [x] Sequence numbers strictly monotonic

## Replay Contract

- [x] Subscriber receives retained history
- [x] Subscriber receives all subsequent live updates
- [x] No duplicates
- [x] No gaps except explicit overflow

## Failure Semantics

- [x] Overflow is explicit
- [x] No silent loss
- [x] Closure is deterministic
- [x] Subscriber cleanup is deterministic

---

# Validation

## Stream Contract

- [x] Replay retained updates
- [x] Receive live updates
- [x] Verify contiguous ordering
- [x] Verify iterator termination

## Replay/Live Race

- [ ] Concurrent publish/subscribe
- [ ] No duplicate boundary
- [ ] No missing boundary event

## Overflow

- [x] Slow subscriber overflows
- [x] Receives `SubscriberOverflowError`
- [ ] Other subscribers continue

## Closure

- [x] Publish after close fails
- [x] Existing subscribers drain
- [x] New subscribers replay then terminate

## Adapter

- [x] Missing session raises `AgentSessionNotActive`
- [x] Inactive session raises `AgentSessionNotActive`
- [ ] Replacement session not automatically followed
- [x] Stale callback rejected
- [x] Typed callback reaches stream exactly once

---

# Cleanup

## Legacy ACP Subscription APIs

- [ ] Remove `subscribe_events()`
- [ ] Remove `iter_events()`
- [ ] Remove `wait_for_event()`
- [ ] Remove ACP-specific subscriber registries
- [ ] Remove duplicate replay/buffering logic

---

# Out of Scope (Do Not Implement Here)

- [ ] SwarmACPMux
- [ ] Generic `AgentEvent` removal
- [ ] `/events` API redesign
- [ ] Agent Mail redesign
- [ ] Runtime observability redesign

---
