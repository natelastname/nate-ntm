# Feature Specification: Textual Runtime Console

**Feature Branch**: `003-textual-runtime-console`

**Created**: 2026-07-06

**Status**: Draft

**Input**: User description: "Read TUI_CONOP.md for a high level overview of the feature. There is one thing has already been decided: The library that we will use for this TUI is `textual` (which is already installed in `./.venv`.)"

This specification is derived from the high-level design in `TUI_CONOP.md`, which defines the Textual Runtime Console as the primary terminal-based operator interface for a running `nate_ntm` swarm runtime.

Future features — including Agent Mail, ACP attachment, log exploration, dashboards, and additional operational tooling — are expected to be implemented as additional screens within this console rather than as separate terminal applications.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Monitor swarm health in real time (Priority: P1)

An operator running a `nate_ntm` runtime wants a single terminal view that summarizes overall swarm health and activity so they can quickly see whether the system is behaving as expected.

**Why this priority**: This is the core purpose of the console and the minimum viable value: without a clear, continuously updating overview, the console does not justify its existence.

**Independent Test**: Start a test runtime with a small swarm, launch the console connected to that runtime, and verify that the overview screen alone provides enough information to determine whether the swarm is healthy or unhealthy without using any other tools.

**Acceptance Scenarios**:

1. **Given** a running runtime with an active swarm, **When** the operator launches the console and connects to that runtime, **Then** the initial screen shows at-a-glance indicators of overall runtime health, swarm status, and agent-level state.
2. **Given** a running runtime where swarm conditions change over time (agents start, stop, succeed, fail, or become unhealthy), **When** those changes occur, **Then** the overview screen updates automatically without requiring manual refresh so that the displayed state remains current.

---

### User Story 2 - Inspect an agent while monitoring the swarm (Priority: P2)

An operator viewing the overview notices an agent in an unexpected or unhealthy state and wants to see more detail about that specific agent without losing the overall swarm context.

**Why this priority**: Being able to drill into a problematic agent directly from the main monitor is essential for debugging and triage while keeping situational awareness of the rest of the swarm.

**Independent Test**: From the overview screen, select a single agent and verify that additional details about that agent are shown inline or in a focused panel, while the rest of the swarm context remains visible.

**Acceptance Scenarios**:

1. **Given** the operator is on the overview screen, **When** they move selection to a specific agent and activate a detail view action, **Then** the console displays additional information about that agent (status, recent activity, and relevant metadata) without navigating away from the overview.
2. **Given** the operator is viewing details for one agent, **When** they change the selected agent, **Then** the detail view updates to show information for the newly selected agent while the overall swarm summary remains visible.

---

### User Story 3 - Observe live runtime events while monitoring (Priority: P3)

An operator wants to see a live stream of runtime events (for the swarm and/or selected agents) alongside the high-level overview so they can connect what they see in the summary view to specific actions and transitions happening in the system.

**Why this priority**: Live events connect state changes to concrete activity, enabling faster diagnosis and building trust that the console reflects what the runtime is actually doing.

**Independent Test**: With the console connected to a test runtime that is emitting events, verify that events appear in the console shortly after they occur and that the operator can correlate events with visible changes to agent or swarm state.

**Acceptance Scenarios**:

1. **Given** the console is connected to a running runtime that emits events, **When** the runtime produces new events, **Then** those events appear in a live event view within the console without manual refresh.
2. **Given** the operator filters focus to a specific agent or subset of the swarm (where such filtering is supported), **When** relevant events occur, **Then** the event view makes it possible to understand how those events relate to the visible agent or swarm state.

---

### Edge Cases

- The operator launches the console when no runtime is reachable (for example, incorrect address or the runtime is not running). The console must clearly communicate that it cannot connect and provide guidance for retrying or exiting.
- The console is connected to a runtime that shuts down or becomes unreachable while the console is open. The console must detect loss of connection, update the UI to show that the runtime is no longer available, and avoid leaving stale state that looks live.
- The swarm is large (for example, hundreds or thousands of agents). The console must remain responsive and make it possible to understand overall health without requiring the operator to scroll through every agent individually.
- The runtime event stream becomes temporarily unavailable or lags. The console must handle this gracefully (for example, by indicating degraded event visibility) while still presenting the best available snapshot from periodic status updates.
- The runtime produces events faster than the operator can reasonably read them. The console must degrade the event view gracefully (for example, by summarizing, compacting, or windowing events) instead of attempting to display every event indefinitely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The console MUST provide a launch mechanism that allows an operator to connect from a terminal to a specific running `nate_ntm` runtime instance.
- **FR-002**: The console architecture MUST maintain exactly one Runtime Session for each connected runtime. All screens within the console MUST obtain runtime state through that shared session, which provides reusable views over the same underlying connection and state cache.
- **FR-003**: After connection, the console MUST provide an initial "overview" screen as the default view, summarizing overall runtime health, swarm status, agent counts by state, and recent activity in a compact, at-a-glance layout.
- **FR-004**: The console MUST ensure that the overview screen updates automatically to reflect changes in runtime and swarm state without requiring manual refresh, using the runtime's public control surface and live event mechanisms.
- **FR-005**: The console MUST allow the operator to navigate a list or table of agents from the overview and select an individual agent for inspection while keeping the overall swarm context visible.
- **FR-006**: When an agent is selected, the console MUST display additional information about that agent sufficient to support operator inspection and diagnosis, whether shown in-line on the overview or in a dedicated detail pane.
- **FR-007**: The console MUST consume the runtime's live event stream so that relevant events appear in the UI shortly after they occur, and visible state changes are consistent with the events being received.
- **FR-008**: The console MUST use only the runtime's public control and event interfaces and MUST NOT rely on private or internal runtime implementation details.
- **FR-009**: The console MUST provide a clear, discoverable mechanism to initiate a graceful runtime shutdown from within the interface, including an explicit confirmation step to prevent accidental termination.
- **FR-010**: The console MUST handle connection errors and partial runtime API or event-stream outages in a user-friendly way by presenting the most recent known state together with a clear indication that live updates have been interrupted, and by providing the ability to retry or change the target runtime without crashing.
- **FR-011**: The console MUST provide basic keyboard-oriented navigation and visible hints or help so that operators can learn available actions without reading project documentation.

### Key Entities *(include if feature involves data)*

- **Runtime Session**: Represents the console's shared communication layer with a specific `nate_ntm` runtime instance. It owns the runtime connection(s), maintains cached state derived from the runtime's public APIs, and provides a common, latest-known view of runtime and swarm state to every screen in the application.
- **Swarm**: The collection of agents managed by the connected runtime, including aggregate health information, counts by state, and other high-level indicators used on the overview screen.
- **Agent**: An individual unit of work or capability within the swarm. Conceptually includes identity, latest known state, recent activity or events, and any metadata needed to present meaningful information in the console.
- **Runtime Event**: A discrete occurrence emitted by the runtime (for example, agent state change, task completion, error, or system-level event) that can be displayed in the console's live event view and correlated with visible state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From the time an operator launches the console against a reachable runtime, the overview screen is fully populated with the latest known swarm state within 10 seconds in typical development environments.
- **SC-002**: When swarm or runtime state changes (for example, agent status transitions or runtime health changes), those changes are reflected on the overview screen within a few seconds, without requiring the operator to trigger a refresh.
- **SC-003**: In end-to-end tests, an operator can determine overall runtime health using only the console (without relying on external tools) once the console is connected to a runtime.
- **SC-004**: In end-to-end tests, an operator can select an individual agent from the primary monitoring workflow and inspect its latest known state without losing context of the rest of the swarm.
- **SC-005**: During test runs where the runtime emits a steady stream of events, events that are successfully received from the runtime's event stream are reflected in the console within approximately 2 seconds under normal operating conditions, so that operators can correlate visible state changes with the corresponding events.
- **SC-006**: Adding a new screen that reuses the shared runtime session (for example, a simple prototype log view) can be done without modifying the core runtime session management logic, demonstrating that the architecture supports incremental growth.

## Assumptions

- The console is operated in a terminal environment on a Linux-like system with adequate support for interactive, full-screen text interfaces.
- Only one runtime connection is active per console session; managing multiple runtimes simultaneously is out of scope for this feature.
- The runtime's public control and event interfaces are stable, documented, and available from the environment where the console runs.
- Advanced runtime management capabilities (for example, configuration editing, dashboards, deep log exploration, and ACP interaction) are out of scope for this initial feature and will be delivered as future screens built on the same console architecture.
