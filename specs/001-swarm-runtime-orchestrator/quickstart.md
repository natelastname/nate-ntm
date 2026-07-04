# Quickstart: nate_ntm Swarm Runtime Orchestrator (MVP)

This quickstart describes how to run and validate the nate_ntm Swarm Runtime Orchestrator MVP end-to-end on a local machine.

It is **not** an implementation guide; it assumes the runtime and its CLI/API are implemented according to the spec, plan, and contracts.

## 1. Prerequisites

- Python 3.11 installed and available on `PATH`.
- The `nate_ntm` repository cloned locally.
- Dependencies installed (example):

  ```bash
  cd /path/to/nate_ntm
  pip install -e .
  ```

- Access to required external services (can be real or mocked for testing):
  - OpenHands agent server (for ACP/conversation handling).
  - Agent Mail service (for mailbox coordination).
- Any necessary credentials configured via environment variables or config files (outside the runtime codebase).

## 2. Start a New Swarm

### 2.1 Start the Runtime Daemon (create mode)

From the project root, start the runtime in **create** mode and run the
WebSocket control API in the foreground:

```bash
nate-ntm runtime start \
  --project /abs/path/to/your/project \
  --mode create \
  --agents 2 \
  --with-control-api
```

This command:

- Resolves a `RuntimeConfig` for the given project directory.
- Creates fresh swarm metadata under `.nate_ntm/` in the project directory.
- Initializes or reuses the corresponding coordination project in Agent Mail.
- Creates two placeholder agents (`agent-1` and `agent-2`) with bound Agent
  Mail identities and ACP conversations.
- Starts a local WebSocket JSON-RPC control API bound to
  `127.0.0.1:8765` (or the host/port configured in `RuntimeConfig`).
- Blocks until a shutdown is requested via the runtime control API.

Leave this command running in one terminal while you inspect the runtime from
another.

### 2.2 Check Runtime Status via API

In a second terminal, use the CLI helper to query `runtime.get_status` (see
`contracts/runtime-api.md`):

```bash
nate-ntm api call runtime.get_status
```

Expected outcome (high level):

- Runtime status is `Running`.
- Swarm ID and project path are correct.
- Agent counts reflect the configured agents (for the example above,
  `total` should be `2`, with both agents typically `Idle` shortly after
  startup).

## 3. Resume a Previous Swarm

### 3.1 Shut Down Gracefully

From another terminal (while the runtime is still running):

```bash
nate-ntm api call runtime.shutdown --param timeout_seconds=30
```

Expected outcome:

- Runtime transitions to `ShuttingDown` and then exits.
- Swarm metadata (including Agent Mail identities and conversation IDs) remains stored under `.nate_ntm/`.

### 3.2 Restart in Resume Mode

Start the Runtime again in **resume** mode, reusing the existing swarm
metadata and agents:

```bash
nate-ntm runtime start \
  --project /abs/path/to/your/project \
  --mode resume \
  --with-control-api
```

Then query status from another terminal as before:

```bash
nate-ntm api call runtime.get_status
```

Expected outcome:

- Runtime loads existing metadata from `.nate_ntm/`.
- Agents are relaunched with the same Agent Mail identities and conversation IDs.
- Any unread Agent Mail present at shutdown is still available and eligible for scheduling.

## 4. Inspect a Single Agent

### 4.1 Get Swarm Overview

```bash
nate-ntm api call swarm.get_overview
```

Expected outcome:

- You see a list of agents with IDs, display names, and statuses.

### 4.2 Inspect Agent Detail

Pick an `agent_id` from the overview and run:

```bash
nate-ntm api call agent.get_detail --param agent_id=<agent_id> --param max_events=50
```

Expected outcome:

- You receive metadata for the agent (status, Agent Mail identity, conversation ID).
- You see a recent sequence of events from the Agent Event Stream (turns, tool calls, errors, etc.).

### 4.3 Live Event Streaming (Optional)

To attach a live inspection view:

```bash
nate-ntm api call events.subscribe --param agent_ids='["<agent_id>"]' --param include_runtime=true
```

Then watch for `events.notify` messages via the appropriate client.

Expected outcome:

- New events for the agent and runtime are delivered with end-to-end latency under ~1 second for the vast majority of events under normal load.

## 5. Validation Checklist (Mapped to Spec Success Criteria)

- **SC-001 (Startup & Status)**:
  - [ ] `runtime.get_status` returns `Running` within ~10 seconds of starting the Runtime under normal conditions.
- **SC-002 (Resume Behavior)**:
  - [ ] After shutdown and `--mode resume`, agents reuse the same Agent Mail identities and conversation IDs, and unread mail present at shutdown is still available.
- **SC-003 (Agent Failure Handling)**:
  - [ ] When an agent subprocess is intentionally killed (e.g., via OS signal) during a run, the Runtime detects the failure and restarts the agent according to policy.
- **SC-004 (Inspection Latency)**:
  - [ ] `agent.get_detail` returns recent events, and `events.notify` delivers new events with end-to-end latency under ~1 second for at least 95% of events in a normal run.
- **SC-005 (15–20 Agent Scenario)**:
  - [ ] With a swarm of ~15–20 active agents, the checks above (SC-001 through SC-004) still hold for at least 90% of runs under normal conditions.

## 6. Notes

- This quickstart assumes a single Runtime instance per project directory; running multiple swarms concurrently requires running multiple Runtime processes.
- The runtime control API is bound to `localhost` only in the MVP; any remote usage should be via SSH or equivalent until explicit remote access support is added in a future iteration.
