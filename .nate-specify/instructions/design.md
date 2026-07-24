# Design Stage

## Input

An explicit epic directory under `specs/`, supplied by the user.

## Goal

Define the problem and required behavior without deciding the implementation plan or dividing the work into user stories.

## Work

1. Read the repository areas relevant to the request.
2. Clarify the problem, motivation, users or consumers, required behavior, constraints, success criteria, terminology, scope, and non-goals.
3. Record concrete scenarios or examples when they make behavior clearer.
4. Identify unresolved questions. Do not silently invent requirements.
5. Write or update `<epic>/spec.md`.

## Rules

- Treat the spec as a behavioral contract, not an implementation plan.
- Do not generate tasks, phases, file-level changes, or user stories in this stage.
- Do not create architecture merely to fill template sections.
- Preserve explicit user decisions and distinguish them from assumptions.
- Keep the document proportional to the feature.

## Completion

The design is complete when `spec.md` clearly states what must be true, what is excluded, and which questions remain for research.
