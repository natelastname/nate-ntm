# Research & Design Decisions: SwarmACPMux (Feature 008)

This document records the key design decisions for SwarmACPMux and the replay-capable agent event stream, updated to align with the current runtime and spec 001 contracts.

It supersedes earlier notes that:

- pushed ACP SDK `SessionUpdate` types into `AgentEvent`; and
- treated reserved swarm controls as `SessionUpdate.name` values,

both of which conflict with existing boundaries in the codebase.

## 1. Role and Boundaries of SwarmACPMux

**Decision**: Implement `SwarmACPMux` as a *connection-scoped* mux between a single external ACP session and the nate_ntm swarm.

- One mux instance per external ACP session.
- Each mux is attached to **at most one agent at a time**, but it may switch attachments over its lifetime.
- The mux owns:
  - connection-local attachment state (`attached_agent_id`);
  - a forwarding task that reads from a per-agent event subscription and writes to the external ACP connection;
  - connection-local closed/open state.
- The mux does **not** own:
  - agent lifecycle or ACP connections to agents;
  - swarm metadata or persistent state;
  - the representation of ACP protocol messages.

**Rationale**:

- Keeps per-agent ACP sessions in `NateOhaAcpClient` (or another `SwarmAgentClient`), as they are today.
- Keeps swarm metadata and event history in `RuntimeDaemon` / `SwarmState`, matching spec 001.
- Avoids creating a second "mini-runtime"; the mux is a narrow coordination layer.

## 2. Replay-Capable Agent Event Streams

**Decision**: Consolidate retained history and live subscriber delivery into a single `AgentEventStream` abstraction per agent, while preserving the existing semantics from `NateOhaAcpClient`.

A correct `AgentEventStream` provides:

- one bounded **retained history deque** per agent;
- one bounded **queue per subscriber**, with drop-oldest semantics for slow subscribers;
- a clear **closure sentinel** when an agent stream ends; and
- an **atomic replay-to-live transition** for each subscriber:
  - replay retained events up to a boundary;
  - then continue with live events on the same queue.

The public contract for subscribers (including the mux) is:

```python
@asynccontextmanager
async def subscribe(self) -> AsyncIterator[AsyncIterator[AgentEvent]]:
    ...  # replay then live, then closure
```

`NateOhaAcpClient.subscribe_events(agent_id)` becomes a thin wrapper around this stream.

**Rationale**:

- Matches the current behavior where live subscribers see their own bounded queues with drop-oldest policy.
- Centralizes replay and ordering in one place.
- Makes SwarmACPMux just another subscriber, without special-case logic.

## 3. AgentEvent Representation and ACP Boundary

**Decision**: Keep `AgentEvent` as a **normalized, ACP-agnostic** runtime model. Do not embed ACP SDK `SessionUpdate` objects in `AgentEvent`.

`AgentEvent` remains:

```python
@dataclass(slots=True)
class AgentEvent:
    event_id: str
    timestamp: datetime
    agent_id: str
    source: Literal["ACP", "AgentMail", "Runtime", "Client"]
    type: str
    payload: Mapping[str, object]  # JSON-serializable
```

ACP-specific concerns live in:

- the ACP integration modules, which convert from ACP SDK types into `AgentEvent` payloads; and
- the Swarm ACP server adapter, which converts from normalized `AgentEvent` payloads back into ACP SDK messages for external clients.

**Rationale**:

- Matches the current design that keeps ACP models behind a boundary, so the rest of the runtime depends only on `AgentEvent`.
- Keeps logging, serialization, and persistence simple.
- Avoids having two representations of the same update (SDK object vs. normalized payload).

**Alternative (rejected)**: Attach a `SessionUpdate`-typed field (`acp_update`) to `AgentEvent`.

- Would couple the runtime core to ACP types.
- Would complicate serialization and replay.
- Would diverge from the existing code’s intentional boundary.

## 4. Reserved Swarm-Control Operations

**Decision**: Treat `_attach`, `_detach`, `_swarm_status`, and `_agent_detail` as **logical swarm-control operations**, not as a special case of `SessionUpdate.name` inside the runtime.

- These are *client-to-swarm* control operations invoked via ACP extension mechanisms (method calls or notifications) at the protocol layer.
- The Swarm ACP server adapter:
  - detects the appropriate ACP request/notification for each operation;
  - calls the corresponding mux method (`attach`, `detach`, `get_swarm_status`, `get_agent_detail`);
  - translates results and errors back into ACP responses.

The mux itself only exposes Python methods; it does not know how the ACP SDK represents those operations on the wire.

**Rationale**:

- Keeps ACP protocol concerns inside the adapter, not the mux.
- Matches the actual code path where `session_update()` is an outbound callback from the agent-side ACP client, not the inbound control surface.
- Avoids binding the design to any particular `SessionUpdate` representation.

## 5. Error Model

**Decision**: Use a small, explicit error hierarchy for mux-level domain failures, and let the ACP adapter map these to protocol-level errors.

```python
class SwarmACPMuxError(RuntimeError):
    pass

class SwarmACPMuxClosedError(SwarmACPMuxError):
    pass

class UnknownAgentError(SwarmACPMuxError):
    pass

class NoAttachedAgentError(SwarmACPMuxError):
    pass

class UnsupportedReservedUpdateError(SwarmACPMuxError):
    pass
```

- `UnknownAgentError` is raised when `_require_known_agent` cannot find an agent in durable `SwarmState.agents`.
- `NoAttachedAgentError` is raised when a prompt/interrupt is attempted with no current attachment.
- `SwarmACPMuxClosedError` is raised after `close()`.
- `UnsupportedReservedUpdateError` is raised when the adapter asks for an unknown reserved operation.

**Rationale**:

- Gives clean, domain-specific failure modes for tests and adapter logic.
- Keeps internal details (tracebacks, transient errors) inside the runtime logs.
- Leaves the mapping to ACP error codes to the adapter.

## 6. Swarm and Agent Views (Alignment with Spec 001)

**Decision**: Reuse the existing runtime control API shapes for swarm overview and agent detail.

- For swarm status, use the `swarm.get_overview` result shape defined in
  `specs/001-swarm-runtime-orchestrator/contracts/runtime-api.md`.
- For agent detail, use the `agent.get_detail` result shape from the same contract, including the `events` list of `AgentEvent` objects.

`SwarmACPMux.get_swarm_status()` and `.get_agent_detail()` add only small mux-local annotations (such as `attached_agent_id` or `attached: bool`) around these existing payloads.

**Rationale**:

- Avoids duplicating or drifting schemas between the runtime control API and ACP-facing controls.
- Makes it straightforward to test ACP-level behavior against the same shapes used by the CLI and dashboards.

## 7. Attach/Detach Semantics and Ordering

**Decision**:

- Attaching requires only that the agent be part of the durable swarm (present in `SwarmState.agents`).
- Attachment is allowed even if the agent is currently failed or stopped; replay is still meaningful for diagnostics.
- Detach is **idempotent**: detaching an already-detached mux is a no-op.
- The ACP adapter must ensure that the client receives an **attach acknowledgment before any replayed events** for the new attachment.

Within the mux:

- `attach(agent_id)`:
  - `_ensure_open()`;
  - `_require_known_agent(agent_id)`;
  - if already attached to the same agent with a live forwarding task, return early;
  - otherwise, `await detach()` and start a new `_forward_agent_events(agent_id)` task.
- `_forward_agent_events`:
  - opens a `subscribe_events(agent_id)` context;
  - forwards each `AgentEvent` via `_forward_external_event`;
  - on normal closure, clears `attached_agent_id` and `_forwarding_task` if they still reference this subscription.

**Rationale**:

- Keeps the mux’s attachment model simple and observable.
- Preserves the diagnostic use case of attaching to failed agents to inspect recent history.
- Gives external clients a clear ordering boundary for events under each attachment.

## 8. Open Items (Non-Blocking for MVP)

These design questions are acknowledged but not required for the first implementation of SwarmACPMux:

1. **Exact ACP extension shapes**
   - Which ACP extension method/notification names and payloads are used for `_attach`, `_detach`, `_swarm_status`, `_agent_detail`?
   - This will be pinned in the Swarm ACP server adapter and the 008 contracts.

2. **Event retention limits**
   - Concrete limits (max events or time window) for `AgentEventStream` are not fixed here; the MVP should match existing runtime behavior and make limits configurable only if needed.

3. **Cross-feature refactoring**
   - If both the runtime control API (spec 001) and SwarmACPMux need the same swarm/agent views, consider refactoring shared helpers/contracts later to avoid duplication.
