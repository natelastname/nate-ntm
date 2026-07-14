
# RULES

1. DO NOT waste your time on updating documentation files unless you are ordered to do so.
2. **[IMPORTANT]** This project uses a `uv`-managed virtual environment
   - DO NOT run `pytest` directly; Use `uv run pytest ...` to run pytest.
   - DO NOT run `pip install ...` directly; Use `uv add ...`
3. DO NOT gate tests behind environment variable checks. 
4. DO NOT try to minimize dependencies for CI. That is NOT a requirement of the project.
5. DO assume that the environment is set up correctly 
   - ALWAYS assume `nate-oha` is installed
   - ALWAYS assume `mcp_agent_mail` is running on `127.0.0.1`
   - **IF ANY OF THESE PREREQS ARE NOT MET, TEST MUST FAIL.**

# Agent Discipline and Spec-kit Workflows

When working in this repository, organize multi-step work around
**spec-kit** features and tasks.

- Treat spec-kit artifacts for the current feature (spec, plan, tasks,
  checklists) as the primary coordination surface across agents and
  sessions.
- When starting substantial work:
  - Use `./speckit.specify` (and other `./speckit.*` commands) to create or
    locate the active feature. These `./speckit.*` forms are the chat-safe
    way to invoke spec-kit commands that are canonically named `/speckit.*`.
  - Read the current spec, plan, and tasks under `specs/` and
    `.specify/`.
  - Update tasks and specs when you discover new work or learn
    something important.
        
## Spec-kit hooks and subagent delegation

Some spec-kit templates include example blocks that contain lines like:

- `EXECUTE_COMMAND: speckit.git.feature`
- `EXECUTE_COMMAND: speckit.git.commit`

In this repository, treat these as **instructions for you to actually run the
referenced spec-kit command as a separate, delegated flow**, not as passive
metadata for another orchestrator.

- When you encounter `EXECUTE_COMMAND: <command>` in a template you are
  following:
  - Interpret `<command>` as the name of another spec-kit command (for
    example, `speckit.git.feature` or `speckit.git.commit`).
  - Prefer to start a **new, delegated run** bound to that command’s
    markdown template (a subagent, second conversation, or equivalent), let
    it complete (including any shell scripts it calls), then resume the
    original `/speckit.*` command with the updated context.
  - If you include an `EXECUTE_COMMAND:` line in your reply (for example,
    inside an “Extension Hooks” block), keep the wording and formatting
    exactly as shown in the template.
- Agents that cannot spawn subagents should still treat
  `EXECUTE_COMMAND: <command>` as a strong instruction to run the referenced
  `./speckit.*` command sequentially, but as a logically separate phase from
  the current command.

For a more detailed description of hook handling and `EXECUTE_COMMAND:`
semantics, see `AGENTS_MK2.md` §3.2.


<!-- br-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`/`bd`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View ready issues (open, unblocked, not deferred)
br ready              # or: bd ready

# List and search
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br search "keyword"   # Full-text search

# Create and update
br create --title="..." --description="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once

# Sync with git
br sync --flush-only  # Export DB to JSONL
br sync --status      # Check sync status
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only open, unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always sync before ending session

<!-- end-br-agent-instructions -->
