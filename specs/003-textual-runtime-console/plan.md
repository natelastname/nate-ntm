# Implementation Plan: Textual Runtime Console

**Branch**: `[003-textual-runtime-console]` | **Spec**: `specs/003-textual-runtime-console/spec.md`

**Input**: Feature specification from `specs/003-textual-runtime-console/spec.md` and high-level concept of operations from `TUI_CONOP.md`.

**Note**: This plan follows the patterns established in `specs/001-swarm-runtime-orchestrator/plan.md` and `specs/002-nate-oha-acp-adapter/plan.md`, adapted for the Textual-based runtime console.

## Summary

Implement a Textual-based terminal console application that connects to a single running `nate_ntm` runtime, maintains one shared Runtime Session per connected runtime, and presents an at-a-glance overview screen as the default view. The console will consume the runtime's public control and event APIs to show live swarm health, support inspecting individual agents while keeping overall context visible, and surface a live event view, all backed by a cached, latest-known view of runtime state. The architecture must explicitly support adding future screens (for example, Agent Mail, ACP, logs, dashboards) without creating additional runtime connections.

## Technical Context

**Language/Version**: Python 3.13 (project requires `>=3.13,<3.14.1`)

**Primary Dependencies**:
- `textual` for the terminal UI application and layout
- `nate_ntm` runtime control API and event stream as defined by Feature 001 (`specs/001-swarm-runtime-orchestrator/`)
- Standard library networking and async primitives used by the existing runtime client APIs

**Runtime Integration**:
- The console is a **separate process** from the `nate_ntm` runtime daemon.
- All interaction with the runtime flows through the **public runtime control API** and **event stream** (WebSocket or equivalent), never through direct imports of runtime internals.
- The console introduces a `RuntimeSession` abstraction on the client side that:
  - Owns the single connection to the runtime control API and event stream for the current session
  - Maintains cached, latest-known snapshots of runtime, swarm, and agent state
  - Provides a subscription/notification mechanism for screens to react to state changes

**Testing**:
- `pytest`-based tests for console logic (state management, event handling, degradation behavior)
- Textual "pilot"/simulation-style tests where feasible for navigation and basic rendering sanity
- End-to-end tests that run a local runtime (from Feature 001) and drive the console against it for the three user stories

**Target Platform**:
- Developer workstations and small servers running Linux or macOS, in a terminal capable of full-screen Textual applications.

**Project Type**:
- Python Textual TUI application that consumes the existing `nate_ntm` runtime APIs.

## Architectural Emphasis

The following architectural decisions from the spec are treated as non-negotiable and are **layered around a reusable client library**, not the Textual app:

1. **RuntimeClient (Reusable Protocol Client)**
   - Introduce a `RuntimeClient` abstraction in a non-TUI module (for example, `src/nate_ntm/api/runtime_client.py`) that wraps:
     - JSON-RPC control API calls (building on `JsonRpcHttpClient` in `src/nate_ntm/api/client.py`).
     - `/events` WebSocket subscription and reconnect logic.
     - Serialization and protocol details.
   - `RuntimeClient` is the **only** component that knows about HTTP, WebSockets, JSON-RPC envelopes, and FastAPI routing details.
   - The client is designed to be reusable by:
     - The Textual console
     - Future ACP tooling
     - Scripting and automated tests
     - Other Python applications that need to talk to a runtime.

2. **RuntimeSession (Cached Runtime Model)**
   - Implement a `RuntimeSession` object in a dedicated client module (for example, `src/nate_ntm/tui/runtime_session.py`) that **depends on `RuntimeClient`**.
   - `RuntimeSession` owns the local cached model of a single runtime instance:
     - Latest-known runtime status and swarm overview
     - Agent cache (summary and detail)
     - Event buffers with bounded history
     - Update notifications and subscription APIs for consumers
     - Periodic refresh logic that re-syncs snapshots via `RuntimeClient`.
   - `RuntimeSession` must not handle raw transport concerns (HTTP/WebSocket); those live in `RuntimeClient`.

3. **Textual as Presentation Only**
   - Implement the console as a Textual `App` and a set of screens/widgets that **observe a `RuntimeSession`**.
   - Textual components should know almost nothing about JSON-RPC, WebSockets, or FastAPI; they interact only with the higher-level `RuntimeSession` interface.

4. **Default Overview Screen (Console != Overview)**
   - The console launches into an **overview screen** as the default view, but the overview is one screen among many.
   - Screen navigation is designed from the start to accommodate future screens (Agent Mail, ACP, logs, dashboards) without architectural changes.

5. **Public Runtime API Only**
   - Neither `RuntimeClient` nor `RuntimeSession` may import or depend on private runtime implementation details (e.g., internal scheduler types, metadata store internals).
   - All state, control, and event information is obtained via the runtime's documented public control and event APIs from Feature 001.

6. **Event Stream plus Periodic Refresh**
   - `RuntimeSession` combines:
     - **Periodic status snapshots** from `RuntimeClient` (for example, `runtime.get_status`, `swarm.get_overview`), and
     - **Live event stream** updates from `RuntimeClient`'s event subscription.
   - Events are treated as incremental updates to the cached snapshots, not as the sole source of truth; the session periodically re-syncs against the control API to avoid drift.
   - If the event stream becomes unavailable, the overview and agent views remain usable based on the latest-known snapshots, and the UI clearly indicates degraded live visibility.

7. **Future Screens Supported by Structure, Not Implemented Yet**
   - This feature **does not** implement Agent Mail, ACP, or log-centric screens.
   - Instead, the navigation structure, `RuntimeSession` abstraction, and `RuntimeClient` layer must make adding such screens straightforward in follow-on features without changing the protocol or transport code.

## Project Structure (This Feature)

```text
specs/003-textual-runtime-console/
├── spec.md              # Approved feature specification
├── plan.md              # This file (implementation plan)
├── tasks.md             # Execution tasks (to be created by /speckit.tasks-style workflow)
└── checklists/
    └── requirements.md  # Requirements checklist
```

Proposed source layout for the client + console (subject to refinement during implementation):

```text
src/
└── nate_ntm/
    ├── tui/
    │   ├── __init__.py
    │   ├── app.py              # Textual App entrypoint for the runtime console
    │   ├── runtime_session.py  # Shared RuntimeSession abstraction and client wiring
    │   ├── screens/
    │   │   ├── __init__.py
    │   │   ├── overview.py     # Default overview screen (User Story 1)
    │   │   └── agent_inspect.py# Focused agent inspection view (User Story 2)
    │   └── widgets/
    │       ├── __init__.py
    │       ├── status_bar.py   # Connection/runtime status indicators
    │       ├── swarm_summary.py# Aggregate swarm health widget
    │       ├── agent_table.py  # Agent list/selection widget
    │       └── event_view.py   # Live event log widget (User Story 3)
    └── cli/
        └── console.py          # CLI entrypoint that launches the Textual console

tests/
└── tui/
    ├── unit/
    │   ├── test_runtime_session.py
    │   ├── test_overview_screen.py
    │   └── test_event_handling.py
    └── integration/
        └── test_console_against_runtime.py
```

**Structure Decision**: Introduce a reusable `RuntimeClient` under `nate_ntm.api.runtime_client` and a `nate_ntm.tui` package to keep console-related code isolated from the runtime daemon internals. All runtime interaction flows through `RuntimeClient` and a single shared `RuntimeSession` abstraction; Textual screens and widgets are thin consumers of `RuntimeSession`, making it straightforward to add new screens in future features and to reuse `RuntimeClient` from non-TUI code.

## Constitution Check

The project constitution (`.specify/memory/constitution.md`) does not yet define concrete, enforceable gates. For this feature, we adopt the following guardrails:

- Keep the console implementation **client-only** with respect to the runtime: no backdoors into runtime internals.
- Prioritize **observability and robustness** over pixel-perfect TUI design.
- Preserve the ability to test console behavior via automated scenarios (no hard dependency on manual interaction-only flows).

At this stage, no constitution violations or unusual complexity have been identified for this feature.

## Complexity Tracking

> Fill ONLY if Constitution Check identifies violations that must be justified.

No additional structural complexity beyond introducing a `tui` package and a `RuntimeSession` abstraction has been identified. This section can be updated if future decisions add new frameworks or cross-cutting concerns.
