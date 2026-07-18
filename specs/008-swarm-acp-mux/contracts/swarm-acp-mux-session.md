# Contract: SwarmACPMux ACP Session Behavior (Feature 008)

This document defines the **MVP contract** for how the SwarmACPMux and Swarm ACP server adapter expose the nate_ntm swarm to external ACP clients.

The goal is to:

- Provide a clear mapping between ACP `SessionUpdate` messages and runtime/mux behavior.
- Define a small set of **reserved swarm-control operations** handled by the adapter/mux instead of individual agents.
- Ensure a consistent replay-then-live event stream for an attached agent over a single ACP session.

> NOTE: The underlying ACP schema (including the precise `SessionUpdate` type) is defined by the ACP SDK and is not re-specified here. This contract describes conventions and responsibilities *on top of* that schema.

---

## 1. General Conventions

- One **SwarmACPMux instance** is created per external ACP session.
- Each mux is attached to **at most one agent at a time**.
- The external ACP session is identified by a `session_id` (or equivalent) in the ACP SDK; the mux treats this as an opaque string.
- Messages between the client and server are modeled as `SessionUpdate` objects.
- Certain `SessionUpdate.name` values are **reserved** for swarm-level control.
- All other updates are treated as **ordinary agent-directed updates** and forwarded to the currently attached agent.

### 1.1 Error Handling

- Errors are returned as ACP error updates (or equivalent in the SDK), with:
  - a machine-readable `code` (integer or string, depending on SDK conventions);
  - a human-readable `message`;
  - optional `data` with additional context (e.g., `agent_id`, `reason`).
- The adapter/mux is responsible for mapping internal exceptions into stable error codes.

Recommended (non-exhaustive) error classes for mux-related failures:

- `MUX_NO_ATTACHED_AGENT` – client attempted an agent-directed operation with no attached agent.
- `MUX_UNKNOWN_AGENT` – requested `agent_id` does not exist.
- `MUX_AGENT_UNAVAILABLE` – agent exists but is not in a state that can be attached to (e.g., `Failed`).
- `MUX_INVALID_REQUEST` – malformed payload for a reserved operation.
- `MUX_INTERNAL_ERROR` – unexpected internal failure; should be logged in detail on the server side.

---

## 2. Reserved Swarm-Control Operations

Reserved operations are identified by the `name` field of a `SessionUpdate`. The `payload` field is a JSON object whose structure is defined below.

Reserved operations are **handled entirely by the adapter/mux + runtime** and MUST NOT be forwarded to agent conversations.

### 2.1 `_swarm_status`

Return high-level status of the swarm and its agents.

**Request:**

```jsonc
{
  "name": "_swarm_status",
  "payload": {}
}
```

**Result (payload shape, approximate):**

```jsonc
{
  "swarm_id": "default",
  "project_path": "/abs/path/to/project",
  "runtime_status": "Running",   // RuntimeStatus
  "agent_counts": {
    "total": 4,
    "starting": 0,
    "idle": 3,
    "running": 1,
    "waiting": 0,
    "failed": 0
  },
  "agents": [
    {
      "agent_id": "nav-1",
      "display_name": "Navigator 1",
      "status": "Running",       // AgentStatus
      "has_unread_mail": true,
      "last_error": null
    }
    // ...
  ]
}
```

Errors are returned if the runtime is not running or the swarm cannot be queried.

### 2.2 `_agent_detail`

Return detailed information for a single agent, including recent events.

**Request:**

```jsonc
{
  "name": "_agent_detail",
  "payload": {
    "agent_id": "nav-1",
    "max_events": 100 // optional, default determined by server
  }
}
```

**Result (payload shape, approximate):**

```jsonc
{
  "agent": {
    "agent_id": "nav-1",
    "display_name": "Navigator 1",
    "status": "Running",
    "agent_mail_identity": "...",
    "conversation_id": "...",
    "last_error": null
  },
  "events": [
    {
      "event_id": "e-123",
      "timestamp": "2026-07-18T12:34:56Z",
      "agent_id": "nav-1",
      "source": "ACP",
      "type": "TurnStarted",
      "payload": { "turn_id": "t-001" }
    }
    // ... up to max_events
  ]
}
```

Errors are returned if `agent_id` is unknown or if the runtime cannot provide details.

### 2.3 `_attach`

Attach this external ACP session to a specific agent and begin streaming that agent's events.

**Request:**

```jsonc
{
  "name": "_attach",
  "payload": {
    "agent_id": "nav-1",
    "max_events": 50 // optional, replay bound for initial events
  }
}
```

**Server behavior:**

1. Validate `agent_id` against runtime state.
2. If the mux is currently attached to a different agent:
   - Cancel the existing event subscription / forwarding task.
3. Subscribe to the target agent's `AgentEventStream` with the requested replay bound.
4. Start a forwarding task that:
   - replays up to `max_events` past events; then
   - delivers live events as they occur.

**Result (payload shape, approximate):**

```jsonc
{
  "attached_agent_id": "nav-1"
}
```

After a successful `_attach`, the client should expect to receive a sequence of `SessionUpdate` messages corresponding to the agent's replayed and live events.

Common error cases:

- `MUX_UNKNOWN_AGENT` – the requested `agent_id` does not exist.
- `MUX_AGENT_UNAVAILABLE` – the agent exists but is not attachable.

### 2.4 `_detach`

Detach the current external ACP session from any agent.

**Request:**

```jsonc
{
  "name": "_detach",
  "payload": {}
}
```

**Server behavior:**

1. If the mux is attached to an agent:
   - Cancel the forwarding task and event subscription.
   - Clear `attached_agent_id`.
2. The underlying agent remains running; only the external attachment is removed.

**Result (payload shape, approximate):**

```jsonc
{
  "detached": true
}
```

Errors may be omitted when detaching an already-detached session (idempotent behavior is acceptable), or a specific `MUX_NO_ATTACHED_AGENT` error may be returned depending on design preference.

---

## 3. Ordinary Agent-Directed Updates

All `SessionUpdate` messages whose `name` is **not** one of the reserved swarm-control operations are treated as **agent-directed updates**.

### 3.1 Preconditions

- The mux MUST have a non-`null` `attached_agent_id`.
- The runtime must consider the attached agent to be running or otherwise able to process requests.

If these preconditions are not met, the server returns an error, for example:

```jsonc
{
  "error": {
    "code": "MUX_NO_ATTACHED_AGENT",
    "message": "No agent is attached to this session. Use _attach first.",
    "data": {}
  }
}
```

### 3.2 Forwarding Rules

- The adapter forwards the update to the underlying per-agent ACP client session corresponding to `attached_agent_id`.
- The agent's responses and intermediate ACP updates (tool calls, logs, etc.) are observed by the runtime and converted into `AgentEvent` objects.
- Each such event with a `SessionUpdate` is forwarded back to the external client via the mux's forwarding task.

This ensures:

- the external client observes a **single ordered stream** of updates for the attached agent;
- the same underlying events can also be consumed by other runtime subscribers (dashboards, logs, etc.).

---

## 4. Lifecycle & Shutdown Semantics

- When the external ACP session closes:
  - The corresponding `SwarmACPMux` instance is torn down.
  - Any event subscriptions and forwarding tasks are cancelled.

- When the runtime shuts down:
  - All mux instances are eventually torn down.
  - The adapter should surface a clear error or close the ACP connections.

- Mux teardown should be **best-effort graceful**:
  - Cancel tasks.
  - Log any final errors.
  - Avoid leaking resources or leaving dangling subscriptions.

---

## 5. Alignment with Specs 001 and 008

- SwarmACPMux builds on the runtime orchestrator's data model and contracts (spec 001), especially the concepts of:
  - `RuntimeStatus` and `AgentStatus`.
  - `AgentEvent` and `AgentEventStream`.
  - Swarm and agent inspection views.

- Feature 008 adds:
  - A connection-scoped mux per external ACP session.
  - Reserved swarm-control operations handled at the ACP boundary.
  - Replay-capable, per-agent event delivery into ACP `SessionUpdate` streams.

Implementations should adhere to the shapes and behaviors described here closely enough that:

- ACP clients can be written against this document; and
- tests can assert on the presence and semantics of reserved operations and error codes,

while still allowing for additive fields and non-breaking refinements as the ACP SDK and runtime evolve.
