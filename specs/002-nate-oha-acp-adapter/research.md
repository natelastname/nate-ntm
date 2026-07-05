# Research & Design Decisions: nate_OHA ACP Production Adapter

This document consolidates the key design decisions and any clarifications required to implement `NateOhaAcpClient` as the production `BaseAcpClient` implementation for `nate_ntm`.

## Decision 1: Per-agent nate_OHA process model

- **Decision**: Run a dedicated `nate_OHA` ACP process per managed agent configured to use the production adapter.
- **Rationale**:
  - Matches FR-002 and the ownership boundary defined in the spec.
  - Provides strong isolation between agents (failures or resource usage for one agent do not directly corrupt another agent’s state).
  - Aligns with nate_OHA’s CLI/env contract in `NATE_OHA_GUIDE.md`, which assumes a single logical agent context per process.
- **Alternatives considered**:
  - **Shared multi-tenant nate_OHA process** for multiple agents:
    - Rejected because it would require introducing a new multiplexing protocol between `nate_ntm` and nate_OHA, complicating failure handling and resource accounting.
    - Would blur the ownership boundary between the runtime and the ACP adapter and is not required by current use cases.

## Decision 2: Adapter selection and OpenHandsAcpClient retirement

- **Decision**: Make `NateOhaAcpClient` the canonical production implementation of `BaseAcpClient`, keep `FakeAcpClient` for fake/dev/test only, and retire `OpenHandsAcpClient` as a selectable production adapter.
- **Rationale**:
  - Ensures a single, well-defined production path for ACP integration.
  - Reduces configuration ambiguity between development and production environments.
  - Matches FR-001 and FR-008 and simplifies long-term maintenance and observability for ACP adapters.
- **Alternatives considered**:
  - **Keeping multiple production-capable adapters** (including `OpenHandsAcpClient`) behind `BaseAcpClient`:
    - Rejected because it would fragment operational experience and complicate incident response and testing.
    - The OpenHands-specific behavior remains available behind nate_OHA; `NateOhaAcpClient` is the only production adapter that the runtime needs to expose.

## Decision 3: Identity and conversation continuity on shutdown/resume

- **Decision**: On swarm shutdown and later resume, each nate_OHA–backed agent must reuse the same Agent Mail identity and the same persisted OpenHands conversation identifier.
- **Rationale**:
  - Directly implements FR-005 and SC-002.
  - Ensures that long-running coordination and conversation state is preserved across runtime restarts.
  - Keeps ownership of durable state in Agent Mail and OpenHands, with the runtime and adapter persisting only the metadata required to reconnect.
- **Alternatives considered**:
  - **Creating a new OpenHands conversation on resume**:
    - Rejected because it would fragment history and make it difficult for operators to reason about continuity.
    - Would require additional reconciliation logic to avoid double-processing messages or losing partially completed work.

## Decision 4: Normative CLI/env contract via NATE_OHA_GUIDE.md

- **Decision**: Treat `NATE_OHA_GUIDE.md` as the normative reference for the nate_OHA CLI and environment contract and implement `NateOhaAcpClient` strictly against that contract.
- **Rationale**:
  - Aligns implementation details (flags, environment variables, working directory expectations) with a single, versioned source of truth.
  - Simplifies future upgrades of nate_OHA by centralizing interface changes in one guide.
  - Matches FR-003, FR-004, and FR-011 and clarifies the adapter’s responsibilities.
- **Alternatives considered**:
  - **Ad-hoc CLI/env usage defined only in code or comments**:
    - Rejected because it would make it harder to audit and evolve the interface and would increase the risk of drift between nate_OHA and `nate_ntm`.

## Open Questions / Clarifications

At this stage, no blockers remain that require additional research beyond the existing specification and `NATE_OHA_GUIDE.md`. If future changes introduce new technologies (e.g., alternative transport mechanisms or distributed nate_OHA deployments), they should be captured here as new decisions with updated rationale and alternatives.
