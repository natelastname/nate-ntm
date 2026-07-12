---
description: Add or update a Speckit adapter section on an existing feature design document.
handoffs:
  - label: Build Technical Plan
    agent: speckit.plan
    prompt: Create a plan for the spec. I am building with...
  - label: Clarify Spec Requirements
    agent: speckit.clarify
    prompt: Clarify specification requirements
    send: true
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Purpose

Many projects begin with an engineering design document, concept of operations (CONOP), architecture proposal, or similar document rather than a formal Speckit specification.

Those documents often contain richer architectural context than a generated specification, but they typically lack the explicit requirements-oriented structure that Speckit's planning workflow expects.

This command adds (or updates) a **Speckit adapter section** at the end of such a document.

The adapter section does **not** replace or rewrite the existing design.

Instead, it extracts the implementation-independent requirements that are already implied by the document and presents them in the structure expected by downstream Speckit commands.

The result should allow `speckit.plan` (and later `speckit.tasks`) to treat the document as though it were a conventional Speckit specification while preserving the original design document intact.

---

# Locate the document

The user input must identify the document to modify.

Typical examples include:

```
CONOP.md
docs/runtime.md
specs/003-foo/spec.md
```

Additional text supplied by the user should be treated as guidance for generating the adapter section.

---

# Existing adapter section

If the document already contains a section beginning with

```markdown
## Speckit Adapter Section
```

update that section in place.

Do **not** create duplicates.

The adapter should always reflect the current contents of the design document.

---

# Generate the adapter

Append a section having this overall structure.

```markdown
## Speckit Adapter Section

### User Stories / Acceptance

...

### Functional Requirements

...

### Key Entities

...

### Success Criteria

...

### Assumptions

...
```

The adapter should contain only information that can reasonably be inferred from the existing design plus any explicit user instructions.

Do **not** invent product requirements.

Do **not** redesign the system.

The adapter is a translation layer, not a design exercise.

---

# User Stories

Extract the major user-visible capabilities implied by the design.

Prefer 2–6 stories.

Each story should contain:

- title
- user goal
- independent test
- acceptance scenarios

Use the standard Speckit style.

Example:

```markdown
### P1: Configure runtime

As an operator...

**Independent test**

...

**Acceptance scenarios**

- Given...
- When...
- Then...
```

Stories should be independently implementable whenever practical.

---

# Functional Requirements

Produce a numbered requirement list.

Use identifiers such as

```
FR-001
FR-002
...
```

Requirements should describe externally observable behavior.

Prefer statements such as

> The runtime shall...

instead of implementation details like

> Create runtime.py.

Avoid mentioning filenames unless the design itself makes them externally significant.

---

# Key Entities

Identify the major concepts introduced by the design.

These may include:

- configuration models
- runtime objects
- APIs
- protocols
- resources
- persistent objects

Each entity should have a short description explaining its role.

---

# Success Criteria

Describe measurable outcomes demonstrating that the feature is complete.

These should be observable from outside the implementation.

Prefer statements like:

- configuration can launch both runtime modes
- invalid configuration produces actionable errors
- feature behaves without legacy dependencies

Avoid code-level completion criteria.

---

# Assumptions

Record assumptions that appear throughout the design but are not themselves requirements.

Examples include:

- compatibility expectations
- migration assumptions
- future extensibility
- implementation constraints
- scope limitations

---

# Preserve the design

The existing document is the authoritative engineering design.

The adapter must not modify, reorder, summarize, or remove any existing content outside the adapter section.

Only add or update the adapter.

---

# Writing style

The adapter should read like it had originally been written as part of a Speckit specification.

Prefer concise, declarative language.

Avoid speculative wording unless the source document is itself uncertain.

Maintain terminology already used by the design document.

Do not introduce new names for existing concepts.

---

# Completion

After updating the document:

- ensure there is exactly one `## Speckit Adapter Section`
- ensure all major sections are present
- ensure the adapter is internally consistent with the design
- do not make unrelated edits elsewhere in the document
