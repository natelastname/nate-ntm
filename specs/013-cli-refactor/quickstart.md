# Quickstart: Swarm Identity, Storage, and CLI Cleanup

## Prerequisites

- Work from the `013-cli-refactor` branch.
- The adjacent editable `../nate-oha` checkout is available.
- `uv sync` succeeds in both repositories.
- Agent configuration JSON files are available; the examples use `planner.json` and `implementer.json`.
- The commands below create test swarm directories under `~/.nate-ntm/swarms/`. Record every generated ID and delete only those exact directories after validation.

## Setup

Create a disposable project directory and copy or generate two valid complete nate-oha configurations:

```bash
project=$(mktemp -d)
cp /path/to/planner.json "$project/planner.json"
cp /path/to/implementer.json "$project/implementer.json"
cd "$project"
```

Confirm no project-local metadata exists:

```bash
test ! -e .nate_ntm
```

## End-to-End Validation

### 1. Dry-run from the working directory

```bash
uv run nate-ntm swarm create \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail \
  --dry-run | tee dry-run.json
```

Read the generated swarm ID:

```bash
swarm_id=$(python -c 'import json; print(json.load(open("dry-run.json"))["swarm_id"])')
printf '%s\n' "$swarm_id"
```

Verify its shape and defaults:

```bash
python - <<'PY'
import json, re
state = json.load(open("dry-run.json"))
assert re.fullmatch(r"[0-9a-f]{32}", state["swarm_id"])
assert state["agent_mail_project_id"] == state["swarm_id"]
assert all(
    agent["nate_oha_config"]["features"]["agent_mail"]["project"] == state["swarm_id"]
    for agent in state["agents"].values()
)
PY

test ! -e "$HOME/.nate-ntm/swarms/$swarm_id"
test ! -e .nate_ntm
```

### 2. Persist a generated swarm

```bash
create_output=$(uv run nate-ntm swarm create \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail)
printf '%s\n' "$create_output"
```

Extract the reported 32-character generated ID using the final CLI wording implemented by the epic, then set it here:

```bash
created_id=<reported-swarm-id>
state_file="$HOME/.nate-ntm/swarms/$created_id/swarm.json"
test -f "$state_file"
test ! -e .nate_ntm
```

Verify the persisted project and Agent Mail defaults:

```bash
CREATED_ID="$created_id" PROJECT="$project" python - <<'PY'
import json, os
from pathlib import Path
state = json.load(open(Path.home() / ".nate-ntm" / "swarms" / os.environ["CREATED_ID"] / "swarm.json"))
assert state["swarm_id"] == os.environ["CREATED_ID"]
assert Path(state["project_path"]).resolve() == Path(os.environ["PROJECT"]).resolve()
assert state["agent_mail_project_id"] == state["swarm_id"]
PY
```

### 3. Create a second swarm for the same project

```bash
second_output=$(uv run nate-ntm swarm create \
  --agent planner.json \
  --constructor agent-mail)
printf '%s\n' "$second_output"
second_id=<reported-second-swarm-id>

test "$second_id" != "$created_id"
test -f "$HOME/.nate-ntm/swarms/$created_id/swarm.json"
test -f "$HOME/.nate-ntm/swarms/$second_id/swarm.json"
```

### 4. Verify explicit identifiers and Agent Mail overrides

```bash
explicit_id="epic013-$(python -c 'import uuid; print(uuid.uuid4().hex)')"
explicit_mail="mail-$explicit_id"

uv run nate-ntm swarm create \
  --project "$project" \
  --swarm-id "$explicit_id" \
  --agent planner.json \
  --constructor agent-mail \
  --agent-mail-project-id "$explicit_mail" \
  --agent-mail-url http://127.0.0.1:9999
```

Verify exact preservation:

```bash
EXPLICIT_ID="$explicit_id" EXPLICIT_MAIL="$explicit_mail" python - <<'PY'
import json, os
from pathlib import Path
state = json.load(open(Path.home() / ".nate-ntm" / "swarms" / os.environ["EXPLICIT_ID"] / "swarm.json"))
assert state["swarm_id"] == os.environ["EXPLICIT_ID"]
assert state["agent_mail_project_id"] == os.environ["EXPLICIT_MAIL"]
agent_mail = next(iter(state["agents"].values()))["nate_oha_config"]["features"]["agent_mail"]
assert agent_mail["project"] == os.environ["EXPLICIT_MAIL"]
assert agent_mail["upstream_url"] == "http://127.0.0.1:9999"
PY
```

### 5. Resume by swarm ID only

Start the persisted swarm using the generated ID:

```bash
uv run nate-ntm runtime start --swarm-id "$created_id"
```

For automated or non-blocking validation, use the repository's runtime test harness or terminate the process after confirming startup. The command must recover the project path from persisted state and must not require `--project`, constructor options, or a creation mode.

### 6. Run tests

From nate-ntm:

```bash
uv run pytest tests/unit/runtime/test_metadata_store.py \
  tests/integration/quickstart/test_swarm_create.py \
  tests/test_swarm_constructors.py \
  tests/unit/cli/test_cli_runtime_start.py \
  tests/integration/quickstart/test_resume_swarm_us2.py \
  tests/unit/runtime/test_agent_mail_client.py
uv run pytest
```

From the adjacent nate-oha repository:

```bash
cd ../nate-oha
uv run pytest tests/test_agent_mail_config.py
uv run pytest
```

## Expected Results

- Omitted swarm IDs are distinct UUID4-hex strings.
- Omitted `--project` resolves to the working directory.
- Every persisted swarm lives at `~/.nate-ntm/swarms/<swarm-id>/swarm.json`.
- Multiple swarms can reference the same project directory.
- No project-local `.nate_ntm/` directory is created.
- The default Agent Mail project ID exactly equals the swarm ID.
- Explicit swarm and Agent Mail project IDs are preserved exactly after validation.
- Agent Mail project values are JSON strings and Python strings, not `Path` values.
- Runtime start locates and resumes the swarm using only `--swarm-id` plus runtime-specific options.
- Both complete test suites pass.

## Expected Failures

Each command below must fail without creating a new swarm directory:

```bash
uv run nate-ntm swarm create \
  --agent planner.json \
  --agent-mail-project-id unused

uv run nate-ntm swarm create \
  --agent planner.json \
  --agent-mail-url http://127.0.0.1:9999

uv run nate-ntm swarm create \
  --swarm-id ../escape \
  --agent planner.json

uv run nate-ntm runtime start --project "$project"
```

Reusing an existing explicit ID without the documented destructive replacement option must also fail and leave the existing `swarm.json` unchanged.

## Cleanup

Delete only the exact swarm directories created by this procedure:

```bash
rm -rf -- \
  "$HOME/.nate-ntm/swarms/$created_id" \
  "$HOME/.nate-ntm/swarms/$second_id" \
  "$HOME/.nate-ntm/swarms/$explicit_id"
rm -rf -- "$project"
```

Do not enumerate or clear `~/.nate-ntm/swarms/` globally.

## Completion Criteria

The epic is accepted when all end-to-end checks and both default test suites pass, the exact test swarm directories are removed, and repository searches find no canonical project-local storage path, runtime create mode, or removed Agent Mail construction environment aliases.
