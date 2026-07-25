# nate_ntm

Swarm runtime orchestrator for coordinating coding agents around a local project directory. A swarm is a durable, independently addressable object whose complete state includes its project path and per-agent nate-oha configuration.

## Installation

Requires Python 3.13+.

```bash
uv sync
uv run pytest
```

The `nate-ntm` entrypoint is defined by `pyproject.toml`.

## Create a swarm

Each `--agent` value has the form `AGENT_ID:CONFIG_PATH`. Agent identity is explicit and independent of the configuration filename, so one configuration can instantiate multiple agents:

```bash
nate-ntm swarm create \
  --agent planner:agent.json \
  --agent implementer:agent.json
```

`--project` is optional and overrides the working-directory default. `--swarm-id` is also optional; omitted IDs are generated with `uuid4().hex`.

Each swarm is stored at:

```text
~/.nate-ntm/swarms/<swarm-id>/swarm.json
```

The project directory does not identify or locate a swarm. Multiple swarms may use the same project directory.

## Agent Mail constructor

The `agent-mail` constructor materializes one shared Agent Mail project plus an identity and credential for each explicitly named agent:

```bash
nate-ntm swarm create \
  --agent planner:agent.json \
  --agent implementer:agent.json \
  --constructor agent-mail
```

The Agent Mail project ID defaults exactly to the swarm ID. Explicit overrides are construction-only inputs:

```bash
nate-ntm swarm create \
  --agent planner:agent.json \
  --constructor agent-mail \
  --agent-mail-project-id planning-mail \
  --agent-mail-url http://127.0.0.1:8765
```

Use `--dry-run` to print the complete materialized swarm without creating its storage directory. Constructors run only during `swarm create`; their results are persisted and reused unchanged.

## Start an existing swarm

An existing swarm is addressed only by ID:

```bash
nate-ntm runtime start --swarm-id <swarm-id>
```

The runtime loads the persisted project path and per-agent configuration from `swarm.json`. There is no runtime create mode and no project-path lookup fallback.

## Control API

The runtime exposes a local JSON-RPC 2.0 API and an `/events` WebSocket endpoint. Invoke a method with:

```bash
nate-ntm api call runtime.get_status
```

Shared result models live in `src/nate_ntm/api/models.py`.

## Design

Epic 013 defines the current identity, persistence, and CLI model:

- `specs/013-cli-refactor/spec.md`
- `specs/013-cli-refactor/research.md`
- `specs/013-cli-refactor/plan.md`
- `specs/013-cli-refactor/tasks.md`
- `specs/013-cli-refactor/quickstart.md`

## License

MIT / Expat
