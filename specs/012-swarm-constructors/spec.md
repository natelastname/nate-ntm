# Feature Specification: Swarm Constructors

**Feature Branch**: `[012-swarm-constructors]`

**Created**: 2026-07-24

**Status**: Draft

**Input**: User description: "nate-ntm needs a way to have constructors—for example, a flag passed during swarm creation that edits each agent configuration to give the swarm an automatically generated Agent Mail setup."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create a swarm with automatic Agent Mail setup (Priority: P1)

An operator wants to create a swarm without manually assigning Agent Mail projects, identities, or per-agent Agent Mail configuration. The operator selects the Agent Mail constructor when creating the swarm, and nate_ntm generates a complete, mutually consistent setup for every agent.

**Why this priority**: Agent Mail configuration is shared swarm-wide state that is tedious and error-prone to construct manually. Automating it is the immediate reason for introducing constructors.

**Independent Test**: From a base swarm definition containing multiple agents but no Agent Mail configuration, an operator can create the swarm with the Agent Mail constructor and inspect a materialized configuration in which every agent has a unique identity, all agents reference the same generated Agent Mail project, and the swarm can be resumed without generating new identities.

**Acceptance Scenarios**:

1. **Given** a valid swarm definition with multiple agents and no Agent Mail setup, **when** the operator creates the swarm with the Agent Mail constructor enabled, **then** nate_ntm generates one shared Agent Mail project configuration and a unique Agent Mail identity for every agent.
2. **Given** an Agent Mail constructor has materialized a swarm, **when** the operator inspects the stored swarm configuration, **then** all generated values are explicit and visible in the persisted configuration.
3. **Given** a previously constructed swarm, **when** the operator resumes it, **then** nate_ntm reuses the persisted Agent Mail project and agent identities rather than running the constructor again or generating replacements.

---

### User Story 2 - Apply reusable constructors during swarm creation (Priority: P2)

An operator or developer wants to package a coherent swarm-wide configuration transformation as a named constructor and select it during swarm creation.

**Why this priority**: The feature should provide one general mechanism rather than embedding Agent Mail-specific mutation logic directly in the swarm creation command.

**Independent Test**: A test constructor can be registered, selected during swarm creation, and shown to transform the complete swarm definition before validation and persistence.

**Acceptance Scenarios**:

1. **Given** a registered constructor, **when** the operator selects it during swarm creation, **then** nate_ntm passes the complete draft swarm configuration and construction context to that constructor exactly once.
2. **Given** a constructor that updates multiple agents and shared swarm metadata, **when** construction completes, **then** subsequent constructors and final validation receive the updated complete swarm configuration.
3. **Given** no constructors are selected, **when** the operator creates a swarm, **then** nate_ntm follows the ordinary creation path without applying implicit constructors.

---

### User Story 3 - Compose multiple constructors predictably (Priority: P3)

An operator wants to select multiple constructors, such as Agent Mail setup and role-specific prompt generation, and have them applied in an explicit, predictable order.

**Why this priority**: Constructor composition makes the abstraction useful beyond its first integration, but it must not introduce hidden or nondeterministic configuration behavior.

**Independent Test**: Two constructors whose transformations depend on order can be selected in a known sequence, and the resulting persisted swarm configuration demonstrates that nate_ntm applied them in that sequence exactly once.

**Acceptance Scenarios**:

1. **Given** multiple selected constructors, **when** a swarm is created, **then** nate_ntm applies them in the order supplied by the operator or declared by the swarm definition.
2. **Given** a constructor raises an error, **when** construction is in progress, **then** swarm creation stops, the original error surfaces to the caller, and no swarm state is saved.
3. **Given** two constructors produce an invalid or conflicting configuration, **when** final validation runs, **then** swarm creation fails with the underlying validation error.

---

### Edge Cases

- What happens when the Agent Mail service rejects the generated project or identity names?
- What happens when two agents begin with the same name and generated Agent Mail identities would collide?
- What happens when a constructor is selected more than once?
- What happens when constructor parameters are malformed or reference an unknown constructor?
- What happens when an existing explicit configuration conflicts with values a constructor would generate?
- What happens when swarm creation fails after a constructor has performed an external side effect?

## Clarifications

### Session 2026-07-24

- Q: When do constructors run?

  → A: Constructors run only while creating and materializing a new swarm. They are not runtime hooks and do not rerun when the swarm is started or resumed.

- Q: What scope does a constructor receive?

  → A: A constructor receives and transforms the complete swarm configuration so it can coordinate shared state and per-agent configuration atomically.

- Q: What is persisted?

  → A: nate_ntm persists both the selected constructor declarations and the fully materialized swarm configuration. Runtime startup and resume consume the materialized configuration directly.

- Q: How are multiple constructors ordered?

  → A: Constructors are applied sequentially in the explicit order supplied during swarm creation or recorded in the swarm definition.

- Q: How should constructor errors be handled initially?

  → A: Constructor and validation errors should surface directly. This feature does not need a custom error abstraction, redaction layer, or compensating cleanup framework.

- Q: Must generated credentials or secrets be hidden from persisted configuration?

  → A: No. For the current system, generated configuration may be persisted as ordinary explicit configuration without special secret-handling machinery.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: nate_ntm MUST allow an operator to select zero or more named constructors when creating a swarm.
- **FR-002**: A constructor MUST receive the complete draft swarm configuration and the stable swarm-creation inputs it needs.
- **FR-003**: A constructor MUST return a complete transformed swarm configuration rather than mutating runtime state after swarm creation.
- **FR-004**: nate_ntm MUST apply selected constructors exactly once, sequentially, in explicit order before final swarm validation and persistence.
- **FR-005**: nate_ntm MUST validate the fully constructed swarm configuration after all constructors have run.
- **FR-006**: nate_ntm MUST NOT save swarm state when a constructor or final validation raises an error.
- **FR-007**: nate_ntm MUST persist the ordered constructor declarations and their parameters as part of the swarm's construction metadata.
- **FR-008**: nate_ntm MUST persist the fully materialized swarm configuration, including all generated values required for startup and resume.
- **FR-009**: Starting or resuming an existing swarm MUST use the persisted materialized configuration and MUST NOT rerun constructors implicitly.
- **FR-010**: nate_ntm MUST provide an Agent Mail constructor that generates or initializes one shared Agent Mail project configuration for the swarm.
- **FR-011**: The Agent Mail constructor MUST assign every agent a stable, unique Agent Mail identity and add the required Agent Mail configuration to each agent.
- **FR-012**: The Agent Mail constructor MUST detect duplicate or otherwise invalid generated identities before the swarm is persisted.
- **FR-013**: Explicit user configuration MUST have defined conflict semantics: a constructor MUST either preserve compatible explicit values or reject conflicting values; it MUST NOT silently overwrite conflicting explicit values.
- **FR-014**: Constructor registration and lookup MUST provide one canonical implementation path for built-in and future constructors.
- **FR-015**: Selecting an unknown constructor, supplying invalid constructor parameters, or selecting the same non-repeatable constructor more than once MUST fail before swarm state is persisted.
- **FR-016**: Errors raised by constructors, external services, configuration validation, or persistence MUST surface through the existing CLI error behavior without a constructor-specific wrapping or redaction layer.

### Key Entities *(include if feature involves data)*

- **Swarm Constructor**: A named, registered transformation that receives a complete draft swarm configuration plus stable creation inputs and returns a complete transformed swarm configuration.
- **Constructor Declaration**: Persisted metadata identifying a constructor, its explicit order, and its parameters.
- **Construction Inputs**: Stable values available during materialization, such as the project path and swarm identifier.
- **Draft Swarm Configuration**: The not-yet-persisted complete swarm state passed through the constructor pipeline.
- **Materialized Swarm Configuration**: The explicit, validated, persisted configuration produced after all constructors have run. This is the sole configuration consumed by runtime startup and resume.
- **Agent Mail Constructor**: The built-in constructor that coordinates swarm-wide Agent Mail project setup and per-agent Agent Mail identities and configuration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a swarm of 20 agents with no preexisting Agent Mail setup, the Agent Mail constructor produces a valid materialized configuration containing one shared project and 20 unique agent identities in 100% of normal test runs.
- **SC-002**: Starting and resuming a constructed swarm reuses 100% of persisted generated identities and does not invoke the constructor pipeline.
- **SC-003**: When any constructor or final validation raises an error, no swarm state is persisted in 100% of tested failure cases.
- **SC-004**: Given the same draft swarm configuration, stable creation inputs, constructor versions, parameters, and ordering, constructors produce semantically equivalent materialized configuration in 100% of repeatability tests that exclude external nondeterminism.
- **SC-005**: An operator can determine which constructors created a swarm, in what order, and with which parameters solely by inspecting persisted swarm metadata.

## Assumptions

- Swarm construction is distinct from runtime startup and occurs before managed agent subprocesses are launched.
- The existing project-local `swarm.json` remains the source of truth for constructed swarm configuration.
- Agent Mail project creation and identity registration are available through an existing nate_ntm or nate-oha integration surface.
- Generated identifiers may include a persisted random or unique component; determinism means they are generated once and then reused, not necessarily derivable from agent names alone.
- Constructor implementations are trusted nate_ntm code. Loading arbitrary third-party constructor code is outside the scope of this feature.
- Persisted swarm configuration is allowed to contain credentials and other sensitive values for now; specialized secret storage is out of scope.

## Out of Scope

- Rerunning constructors automatically during swarm resume or every runtime launch.
- Continuously reconciling runtime state against constructor declarations.
- Arbitrary user-provided executable constructor plugins.
- A general migration framework for modifying already materialized swarms.
- A constructor-specific exception hierarchy, error-redaction layer, rollback protocol, or compensating transaction framework.
- Role assignment, prompt generation, repository provisioning, or other constructors beyond Agent Mail, except as necessary to prove that the constructor abstraction is reusable.
