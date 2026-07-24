# Research Stage

## Input

An explicit epic directory under `specs/` containing an approved `spec.md`.

## Goal

Resolve enough uncertainty to make implementation planning credible.

## Work

1. Read the specification and inspect the relevant repository architecture and existing behavior.
2. Identify questions that must be answered before planning.
3. Classify each question as:
   - answerable from the repository or available documentation;
   - requiring an experiment;
   - requiring evidence from the user or an unavailable environment;
   - requiring a product or policy decision from the user.
4. Gather evidence. When the agent cannot gather it directly, create the smallest reproducible research instrument: a command sequence, script, diagnostic capture, fixture request, or focused questionnaire.
5. Record findings, evidence, decisions, tradeoffs, and remaining unknowns in `<epic>/research.md`.
6. Create or update supporting artifacts only when useful, such as `data-model.md`, `contracts/`, or `diagnostics/`.

## Rules

- Research exists to remove uncertainty, not to produce mandatory paperwork.
- Cite concrete repository locations, command output, documentation, or captured evidence.
- Distinguish observed facts, decisions, assumptions, and recommendations.
- Research instruments gather facts; they must not manage Git or workflow state.
- Delete unused optional template artifacts rather than filling them with fiction.

## Completion

Research is complete when the remaining unknowns do not prevent a competent agent from producing an executable plan, or when unresolved decisions are explicitly returned to the user.
