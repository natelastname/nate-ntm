# Research & Design Decisions: SwarmACPMux (Feature 008)

This document captures key technical decisions and rationale made during `/speckit.plan` for the SwarmACPMux feature. It serves as a reference for how the mux is intended to behave, how it composes with the existing nate_ntm runtime, and what alternatives were considered.

The intent is to keep this file aligned with the implementation; if the code diverges materially from these decisions, either this document or the code should be updated.

## 1. Role and Boundaries of SwarmACPMux

- **Decision**: Implement `SwarmACPMux` as a *connection-scoped* object that sits between a single external ACP client session and the nate_ntm Swarm Runtime.
  - One mux instance per external ACP session.
  - Each mux is attached to **at most one agent at a time**.
  - The mux is responsible for attachment state and event forwarding, not for owning ACP connections or swarm lifecycle.
- **Rationale**:
  - Keeps ownership of per-agent ACP sessions in existing components (`NateOhaAcpClient` / `SwarmAgentClient`).
  - Keeps ownership of swarm and agent metadata in `RuntimeDaemon`/`SwarmState` and associated persistence.
  - Avoids creating a second "mini-runtime" or scheduler; the mux is a thin coordination layer.
  - Fits naturally with a server that spawns a mux per inbound ACP WebSocket / session.
- **Alternatives Considered**:
  - **Runtime-owned global mux**: a single, process-wide mux that knows about all external sessions.
    - Rejected because it tangles external transport concerns with core runtime scheduling and makes it harder to reason about per-session lifecycle.
  - **External-only mux**: a separate process that mirrors runtime state manually.
    - Rejected because it would have to replicate runtime bookkeeping and event-stream semantics, leading to duplication and consistency risks.

## 2. Replay-capable Agent Event Streams

- **Decision**: Treat per-agent event history as a *replay-capable stream* that can be subscribed to by multiple consumers, including SwarmACPMux instances.
  - Each agent has a single `AgentEventStream` abstraction that maintains a bounded history of `AgentEvent` objects.
  - A subscriber (such as a mux) obtains a handle that delivers:
    1. a replay of retained events (subject to a limit); then
    2. live events as they are appended.
  - The mux uses this stream to feed the external ACP session with a single ordered sequence of `SessionUpdate`-carrying events.
- **Rationale**:
  - Matches the spec's requirement that a newly attached client can see *recent* history for the agent, not just future updates.
  - Allows multiple independent consumers (dashboards, logs, SwarmACPMux instances) to share a single event-source implementation.
  - Keeps the replay logic inside the runtime, rather than exposing raw persisted history to the mux.
- **Alternatives Considered**:
  - **Replay from durable storage** on attach (e.g., reading from `.nate_ntm/` or external logs):
    - Rejected for MVP because it complicates durability and ordering guarantees and exceeds what the spec requires.
  - **Live-only streams** with no replay:
    - Simpler, but fails the spec requirement that attachment can show recent context without re-running the agent.

## 3. SessionUpdate Representation and Propagation

- **Decision**: Represent ACP updates in the runtime using a typed `SessionUpdate` model (via an `acp_types` or equivalent module) and carry that type all the way into `AgentEvent` where feasible.
  - Where the runtime already has a raw `SessionUpdate` instance (from the ACP client), it is attached to the corresponding `AgentEvent` as `acp_update`.
  - Where that is not possible (e.g., historical events that did not store the typed object), a helper such as `require_session_update(event)` is used to reconstruct or fail fast.
- **Rationale**:
  - The mux should not have to re-parse protocol-level updates; it should receive a well-typed object from the runtime.
  - Keeping `SessionUpdate` in `AgentEvent` simplifies forwarding logic and error handling in the mux.
  - Centralizing reconstruction in a helper allows callers to have a single, well-defined failure mode when data is missing or malformed.
- **Alternatives Considered**:
  - **Stringly-typed payloads** in events (only JSON blobs or dicts):
    - Rejected because it pushes protocol knowledge into each consumer and weakens type-safety at the boundary where we need it most.
  - **Mux re-parsing wire JSON** from the ACP client directly:
    - Rejected because it bypasses the existing ACP client/protocol layers and risks divergence between internal and external representations.

## 4. Reserved Swarm-Control Protocol

- **Decision**: Treat a small set of `SessionUpdate` names as *reserved swarm-control operations* that are intercepted by the Swarm ACP server adapter and routed to mux/runtime helpers instead of forwarded to agents.
  - Examples (per spec 008):
    - `_attach` / `_detach`
    - `_swarm_status`
    - `_agent_detail`
  - The adapter inspects incoming updates, selects a handler based on `name`, and calls into the mux/runtime rather than treating these as ordinary agent requests.
  - Responses and errors are mapped back into ACP responses on the same external session.
- **Rationale**:
  - Cleanly separates swarm-level control from per-agent conversations.
  - Allows an external client to inspect swarm state and switch attachments without needing out-of-band APIs.
  - Keeps per-agent ACP sessions free of these reserved names, reducing ambiguity and potential clashes with agent tools.
- **Alternatives Considered**:
  - **Out-of-band HTTP or JSON-RPC API** for swarm control, separate from ACP:
    - Rejected for this feature because it fragments control surfaces and contradicts the spec's goal of an ACP-centric experience.
  - **Passing reserved updates through to agents** and having tools interpret them:
    - Rejected because it would entangle swarm orchestration with agent behavior and tool prompts.

## 5. Error Model and Observability

- **Decision**: Keep the mux error model small and explicit, with errors surfaced as structured ACP failures at the boundary.
  - Introduce a focused error type (e.g., `SwarmACPMuxError`) to represent mux-specific problems such as:
    - attaching to an unknown or unavailable agent;
    - attempting to send a request when no agent is attached;
    - inconsistencies in the event stream (e.g., missing `SessionUpdate` when one is required);
    - internal cancellation / shutdown of the mux.
  - Errors are logged once at the mux/runtime boundary, then mapped into ACP error responses with stable machine-readable codes and human-readable messages.
- **Rationale**:
  - Keeps logging and observability concerns in the runtime, where we already have logging configuration and test helpers.
  - Gives external ACP clients predictable failure modes without exposing internal stack traces.
  - Makes it easier to write integration tests that assert on specific error codes and behaviors.
- **Alternatives Considered**:
  - **Treat all errors as generic runtime failures**:
    - Simpler, but makes it difficult for clients to distinguish user mistakes (e.g., unknown agent) from infrastructure problems.
  - **Fully mirroring internal exception hierarchies into ACP error codes**:
    - Overly coupled and likely to create churn when internal implementations change.

## 6. Open Questions / To Revisit Later

These items are intentionally left flexible for future iterations and are **not** required to complete the initial SwarmACPMux implementation:

1. **Exact `SessionUpdate` schema coverage**
   - How much of the upstream ACP SDK should be mirrored into `nate_ntm.runtime` types vs. treated as opaque payloads?
   - For now, we assume a minimal typed model sufficient to carry the session ID, update name, and payload for mux purposes.

2. **Event retention policy for `AgentEventStream`**
   - Concrete limits (max events, time window) are not yet fixed.
   - The current plan is to match existing runtime behavior and only tighten or expose configuration if needed by clients.

3. **Multi-subscriber backpressure and flow control**
   - The initial implementation assumes subscribers (including SwarmACPMux) are reasonably well-behaved and do not block indefinitely.
   - If backpressure becomes a problem, we may need per-subscriber queues or drop policies.

4. **Extended reserved operations**
   - The spec outlines a core set of reserved updates. Additional operations (e.g., listing agents with filters, toggling debug modes) may be added later.
   - Such extensions should be captured in the contracts under `specs/008-swarm-acp-mux/contracts/` and validated via new integration tests.

5. **Cross-feature alignment with the Runtime Orchestrator (spec 001)**
   - Some responsibilities (e.g., swarm status shapes, agent detail schemas) overlap between specs 001 and 008.
   - As the implementation solidifies, we may refactor shared contracts or data-model sections to reduce duplication.
