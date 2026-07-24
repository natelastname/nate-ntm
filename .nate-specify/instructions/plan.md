# Planning and Tasks Stage

## Input

An explicit epic directory under `specs/` containing an approved `spec.md` and sufficient completed research.

## Goal

Turn the design and evidence into one executable implementation plan and dependency-ordered task list.

## Work

1. Read the specification, research, and relevant repository code.
2. Derive the smallest set of independently valuable and demonstrable user stories that collectively satisfy the design.
3. Prioritize the stories and identify foundational work that truly blocks them.
4. Write `<epic>/plan.md` with the selected architecture, repository changes, data and interface implications, tradeoffs, risks, and validation strategy.
5. Write `<epic>/tasks.md` as an ordered checklist grouped by setup, genuine foundational work, user story, and final integration only when those divisions are useful.
6. Write `<epic>/quickstart.md` as a concise end-to-end acceptance procedure.
7. Refine optional supporting artifacts when planning exposes missing detail; remove unused ones.

## User Stories

- Derive stories from approved behavior and research, not from arbitrary personas.
- Prefer vertical behavior slices over architectural components.
- Each story should have an independently observable checkpoint when practical.
- Do not disguise modules, layers, or internal chores as user stories.

## Task Rules

- Every task must be concrete, actionable, and include exact file paths.
- Order tasks by real dependencies.
- Mark parallel work only when files and prerequisites genuinely permit it.
- Include a few macro-level tests that prove user-visible behavior; avoid micro-test inventories.
- Do not create compatibility paths, duplicate implementations, speculative abstractions, or unrelated cleanup.
- The default test command must continue to run the complete suite.

## Completion

The stage is complete when another competent coding agent can execute `tasks.md` without rediscovering the design, while `plan.md` explains why the chosen implementation is correct.
