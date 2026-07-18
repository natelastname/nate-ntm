# Data Model: SwarmACPMux and Agent Event Streams (Feature 008)

This document extracts and structures the core entities, fields, relationships, and state transitions implied by the SwarmACPMux spec (`specs/008-swarm-acp-mux/spec.md`) and the existing runtime orchestrator.

The goal is to clarify **what data the mux and runtime own for this feature**, how it is represented in memory, and how it changes over time, without over-constraining implementation details.

## 1. Overview

Feature 008 introduces a small, connection-scoped component (`SwarmACPMux`) that sits between an external ACP client session and the nate_ntm runtime. Rather than adding new persistent state, it organizes and exposes *existing* runtime state via:

- a replay-capable **AgentEventStream** per agent;
- a connection-scoped **SwarmACPMux** instance per external ACP session; and
- a small set of **reserved swarm-control operations** handled at the ACP boundary.

All new data introduced by this feature is **in-memory only**; durable state remains owned by the runtime as described in the orchestrator data model.

## 2. Core In-Memory Entities

### 2.1 AgentEvent

Represents an individual event emitted by the runtime for a specific agent. This extends the orchestrator's AgentEvent concept to carry ACP-specific payloads.

**Fields (conceptual):

- `event_id: str`
  - Unique identifier for the event within the agent's event stream.
- `timestamp: datetime`
  - Time at which the event occurred or was observed by the runtime.
- `agent_id: str`
  - Agent associated with the event.
- `source: str`
  - Origin of the event (e.g., `"ACP"`, `"AgentMail"`, `"Runtime"`, `"Client"`).
- `type: str`
  - Event type (e.g., `"TurnStarted"`, `"TurnCompleted"`, `"TurnFailed"`, `"ToolCall"`, `"Log"`).
- `payload: dict | object`
  - Event-specific payload (summarized, not necessarily the full raw data).
- `acp_update: SessionUpdate | None`
  - Optional typed ACP `SessionUpdate` associated with this event, if the event corresponds directly to an ACP update.

**Notes:**

- Not every event has a meaningful `SessionUpdate` (e.g., internal runtime bookkeeping events), so `acp_update` may be `None`.
- For events that should be visible on the external ACP stream, the runtime is expected to attach the underlying `SessionUpdate` where possible.

### 2.2 AgentEventStream

Represents a bounded, replay-capable, transient stream of recent AgentEvents for a single agent.

**Conceptual structure:**

- `events: Deque[AgentEvent]`
  - Ordered sequence of recent events (oldest to newest), capped by a configured maximum length or memory budget.
- `max_events: int`
  - Upper bound on the number of events retained.
- `subscribers: set[SubscriberHandle]`
  - Registered subscribers that should receive replay and live updates.

**Behavioral notes:**

- When the stream is full and a new event arrives, the oldest event is dropped.
- A new subscriber receives:
  - a replay of existing events (up to some limit, possibly filtered by `max_events` or a caller-provided bound), then
  - live events as they are appended.
- The stream is not a durability mechanism; it is safe to discard entirely between runtime restarts.

### 2.3 SwarmACPMux

Represents the connection-scoped mux state for a single external ACP client session.

**Fields (conceptual, roughly matching the spec's dataclass outline):**

- `runtime: RuntimeDaemon`
  - Handle to the running runtime instance. Used to query swarm/agent status and to access AgentEventStreams.
- `external_session_id: str`
  - Identifier for the external ACP session (as seen by the ACP server / client library).
- `attached_agent_id: str | None`
  - Agent currently attached to this external session, if any.
- `event_subscription: AgentEventSubscription | None`
  - Handle representing the mux's subscription to the attached agent's AgentEventStream.
- `forwarding_task: asyncio.Task | None`
  - Background task responsible for pulling events from the subscription and sending them to the external ACP client.
- `logger: logging.Logger`
  - Logger scoped to this mux instance.

**Invariants:**

- At most one `attached_agent_id` per mux at any time.
- If `attached_agent_id` is not `None`, there should be an active `event_subscription` and `forwarding_task` associated with that agent.
- Detaching must cancel the forwarding task and subscription cleanly, without affecting other subscribers.

### 2.4 Reserved Operation Dispatch (Adapter-Level)

While not a separate class in the runtime, the Swarm ACP server adapter effectively maintains a *dispatch table* for reserved `SessionUpdate` names.

Conceptually:

- `reserved_handlers: dict[str, Callable[[SwarmACPMux, SessionUpdate], Awaitable[SessionUpdate]]]`
  - Maps reserved update names (e.g., `"_attach"`, `"_detach"`, `"_swarm_status"`, `"_agent_detail"`) to handler coroutines.
  - Handlers use the mux and runtime to perform the requested operation and return an appropriate ACP response update.

## 3. Swarm and Agent Views for the Mux

Although SwarmACPMux does not introduce new persisted entities, it relies on and slightly constrains the shapes of existing runtime views.

### 3.1 SwarmStatus View

Used to answer `_swarm_status` requests.

**Conceptual shape (aligned with the runtime control API):**

- `swarm_id: str`
- `project_path: str`
- `runtime_status: RuntimeStatus`
- `agent_counts: dict[str, int]`
  - Counts keyed by agent lifecycle state (e.g., `"starting"`, `"idle"`, `"running"`, `"waiting"`, `"failed"`).
- `agents: list[AgentSummary]`
  - Where `AgentSummary` includes at least:
    - `agent_id: str`
    - `display_name: str`
    - `status: AgentStatus`
    - `has_unread_mail: bool`
    - `last_error: str | None`

The mux does not own this structure; it calls into the runtime (e.g., `runtime.get_swarm_status_view()`) to obtain it and wraps it into an ACP `SessionUpdate` when responding to `_swarm_status`.

### 3.2 AgentDetail View

Used to answer `_agent_detail` requests and to provide context for mux attachment.

**Conceptual shape:**

- `agent: {
    agent_id: str,
    display_name: str,
    status: AgentStatus,
    agent_mail_identity: str,
    conversation_id: str,
    last_error: str | None,
  }`
- `events: list[AgentEvent]`
  - Recent events for the agent, typically constrained by a `max_events` parameter.

As with SwarmStatus, this is produced by the runtime (building on its own data model) and only re-packaged for ACP by the mux/adapter.

## 4. State Transitions

### 4.1 Attachment Lifecycle per Mux

For a single `SwarmACPMux` instance:

1. **Initial state**
   - `attached_agent_id = None`
   - `event_subscription = None`
   - `forwarding_task = None`

2. **Attach (`_attach`)**
   - Validate the requested `agent_id` against runtime state (agent exists and is eligible).
   - If already attached to a different agent:
     - Cancel existing `forwarding_task` and `event_subscription`.
   - Obtain an `AgentEventStream` subscription for the new agent (respecting any replay limits).
   - Spawn `forwarding_task` to read from the subscription and send events to the external ACP client.
   - Set `attached_agent_id` to the new `agent_id`.

3. **Forwarding loop**
   - For each `AgentEvent` received from the subscription:
     - Ensure a usable `SessionUpdate` is available (`event.acp_update` or via a helper).
     - Map it into the external ACP session (preserving ordering and session identity).
   - On subscription cancellation, shutdown, or error, the task should terminate and clear or update mux state appropriately.

4. **Detach (`_detach`)**
   - Cancel `forwarding_task` and `event_subscription` if present.
   - Clear `attached_agent_id`.
   - Ensure the agent itself continues running; only the external attachment is affected.

5. **Shutdown**
   - On runtime shutdown or external session closure, ensure mux resources are cleaned up:
     - Cancel forwarding task and subscription.
     - Remove mux instance from any registries maintained by the adapter.

### 4.2 EventStream Retention and Replay

- When a new subscription is created for an agent:
  - The subscriber may supply a `max_events` or similar hint.
  - The stream replies with up to that many of the most recent events, in order.
  - Subsequent events are delivered live until the subscriber unsubscribes or the stream is torn down.
- When the runtime restarts:
  - In-memory streams are re-created empty; SwarmACPMux instances are also torn down.
  - External clients are expected to reconnect and re-attach as needed.

## 5. Relationships Summary

- One **RuntimeDaemon** manages exactly one **Swarm** (per process), as described in the orchestrator spec.
- One **Swarm** has many **Agents**, each with its own **AgentEventStream**.
- Each **AgentEventStream** may have multiple subscribers (dashboards, logs, SwarmACPMux instances).
- Each **SwarmACPMux** is associated with exactly one external ACP session and, at any given time, at most one attached agent.
- Reserved operations (`_attach`, `_detach`, `_swarm_status`, `_agent_detail`, ...) are dispatched by the Swarm ACP server adapter using a shared dispatch table but executed against the specific mux and runtime instance for that external session.

This data model should be treated as a guide rather than a rigid schema. Implementations may adjust field names and internal structures as long as they preserve the semantics required by the spec—especially around connection-scoped mux behavior, replay-capable event delivery, and clear separation between swarm-level control and per-agent ACP conversations.
