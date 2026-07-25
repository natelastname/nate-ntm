# Quickstart: Swarm Identity and Lifecycle

## Prerequisites

- The adjacent editable `../nate-oha` checkout is available.
- `uv sync` succeeds.
- One complete nate-oha JSON5 configuration is available.

The commands below create state under `~/.nate-ntm/swarms/`. Delete only the exact swarm IDs created during validation.

## Create two agents from one configuration

```bash
project=$(mktemp -d)
cp /path/to/agent.json "$project/agent.json"
cd "$project"

uv run nate-ntm swarm create \
  --agent planner:agent.json \
  --agent implementer:agent.json \
  --constructor agent-mail \
  --dry-run
```

Every `--agent` value must have the form:

```text
AGENT_ID:CONFIG_PATH
```

Agent IDs are explicit. Configuration filenames never determine identity, and the same configuration file may be used by multiple agents.

## Persist a generated swarm

```bash
create_output=$(uv run nate-ntm swarm create \
  --agent planner:agent.json \
  --agent implementer:agent.json \
  --constructor agent-mail)
printf '%s\n' "$create_output"
```

Record the reported ID:

```bash
swarm_id=<reported-swarm-id>
state_file="$HOME/.nate-ntm/swarms/$swarm_id/swarm.json"
test -f "$state_file"
```

The Agent Mail project ID defaults exactly to the swarm ID, while each agent receives its own identity and credentials.

## Explicit identity and Agent Mail overrides

```bash
explicit_id="quickstart-$(python -c 'import uuid; print(uuid.uuid4().hex)')"

uv run nate-ntm swarm create \
  --project "$project" \
  --swarm-id "$explicit_id" \
  --agent planner:agent.json \
  --agent implementer:agent.json \
  --constructor agent-mail \
  --agent-mail-project-id planning-mail \
  --agent-mail-url http://127.0.0.1:9999
```

## Resume

```bash
uv run nate-ntm runtime start --swarm-id "$swarm_id"
```

Resume uses only the swarm ID. The persisted swarm supplies the project path, agents, complete nate-oha configurations, and constructor results.

## Expected failures

These forms must fail:

```bash
# Bare paths are not agent specifications.
uv run nate-ntm swarm create --agent agent.json

# Missing ID or path.
uv run nate-ntm swarm create --agent :agent.json
uv run nate-ntm swarm create --agent planner:

# Duplicate explicit IDs.
uv run nate-ntm swarm create \
  --agent planner:agent.json \
  --agent planner:agent.json

# Agent Mail options without the constructor.
uv run nate-ntm swarm create \
  --agent planner:agent.json \
  --agent-mail-project-id unused
```

## Validation

```bash
uv run pytest tests/integration/quickstart/test_swarm_create.py \
  tests/test_swarm_constructors.py
uv run pytest
```

## Cleanup

```bash
rm -rf -- \
  "$HOME/.nate-ntm/swarms/$swarm_id" \
  "$HOME/.nate-ntm/swarms/$explicit_id" \
  "$project"
```

Do not enumerate or clear `~/.nate-ntm/swarms/` globally.
