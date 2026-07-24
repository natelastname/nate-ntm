# nate-specify

A minimal three-stage specification workflow for competent coding agents.

1. **Design** — define required behavior in `spec.md`.
2. **Research** — resolve uncertainty in `research.md` and optional supporting artifacts.
3. **Planning and tasks** — derive user stories and produce `plan.md`, `tasks.md`, and `quickstart.md`.

Stage instructions live in `instructions/`. Sparse artifact templates live in `templates/`.

Create an epic with:

```bash
bash .nate-specify/create-epic <lowercase-hyphenated-name>
```

The script only chooses the next numeric prefix, creates `specs/NNN-name/`, and copies the templates. It does not inspect or modify Git state.

Always give agents the epic directory explicitly. Do not infer an active epic from a branch or hidden state.
