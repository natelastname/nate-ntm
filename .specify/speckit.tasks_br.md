```
description: Generate Beads issues from Spec Kit design artifacts.
```
## User Input

```
$ARGUMENTS
```

Use the user input as extra guidance for issue scope, naming, or implementation priorities.

## Goal

Create a Beads issue graph for the current Spec Kit feature so agents can select work with:

```
br ready --json
```

## Steps

### 1. Locate the active feature

Run from the repository root:

```
.specify/scripts/bash/setup-tasks.sh --json
```

Parse:

- `FEATURE_DIR`
- `AVAILABLE_DOCS`

Use `FEATURE_DIR` as the source directory for all feature artifacts.

### 2. Read the design documents

Read these files from `FEATURE_DIR`:

Required:

- `spec.md` — user stories, priorities, acceptance criteria
- `plan.md` — architecture, tech stack, project structure

Read these if present:

- `research.md` — design decisions and constraints
- `data-model.md` — entities and relationships
- `contracts/` — APIs, CLIs, schemas, protocols
- `quickstart.md` — validation scenarios

Also read if present:

- `.specify/memory/constitution.md`

### 3. Initialize Beads

Check whether Beads is already initialized:

```
br where
```

If not initialized, run:

```
br init
```

Then verify:

```
br doctor
```

### 4. Create the feature epic

Create one top-level epic for the feature:

```
br create “<feature name>“ --type epic --priority 1 --json
```

The epic description should summarize:

- feature goal
- source directory
- key user stories
- MVP scope
- validation approach

### 5. Create implementation issues

Create one Beads issue per concrete task.

Use this issue shape:

```
br create “<task title>“ --type task --priority <priority> --json
```

Each issue description should include:

```
## Context

Feature: <feature name>
Source docs: <spec.md, plan.md, etc.>
User story: <US1 / US2 / none>

## Task

<specific instruction>

## Files

- `path/to/file`

## Acceptance Criteria

- <verifiable result>
- <verifiable result>

## Validation

<command, test, manual check, or quickstart step>
```

### 6. Organize issues by phase

Create issues in this order:

1. Setup
  - project structure
    - dependencies
    - configuration
    - scaffolding
2. Foundation
  - shared models
    - shared services
    - storage
    - API/CLI framework
    - error handling
    - logging
3. User stories
  - one group per user story from `spec.md`
    - process in priority order: P1, then P2, then P3
    - each story should be independently testable
4. Polish
  - documentation
    - cleanup
    - integration checks
    - quickstart validation
    - performance/security hardening if relevant

### 7. Add dependencies

Use Beads dependencies to express blocking relationships:

```
br dep add <blocked_issue_id> <blocking_issue_id>
```

Dependency guidance:

- Foundation depends on setup.
- User-story work depends on foundation.
- Services depend on models.
- Interfaces depend on services.
- Validation depends on implementation.
- Polish depends on completed user stories.

Avoid unnecessary dependencies between tasks that can run in parallel.

### 8. Add labels

Add useful labels:

```
br label add <issue_id> feature:<feature-slug>
br label add <issue_id> phase:<setup|foundation|US1|US2|polish>
br label add <issue_id> kind:<implementation|test|docs|validation>
```

For MVP issues:

```
br label add <issue_id> mvp
```

For parallel-safe issues:

```
br label add <issue_id> parallel
```

### 9. Validate the issue graph

Run:

```
br ready --json
br graph
br count --json
br lint
```

Confirm:

- ready issues are the correct starting tasks
- blocked issues have sensible dependencies
- each user story has enough work to be implemented independently
- every issue has clear files, acceptance criteria, and validation

### 10. Sync Beads state

Run:

```
br sync
```

## Completion Report

Report:

- feature epic ID
- total issue count
- issue count by phase
- issue count by user story
- MVP issue list
- currently ready issues
- validation commands run
- any warnings or missing design artifacts

## Done When

- Beads is initialized
- feature epic exists
- implementation issues exist
- dependencies are recorded
- labels are applied
- `br ready --json` shows the correct starting work
- Beads state is synced
