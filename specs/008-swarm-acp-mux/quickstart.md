# Quickstart: SwarmACPMux (Feature 008)

This quickstart describes how to exercise the SwarmACPMux behavior end-to-end once the feature is implemented.

It assumes the nate_ntm Swarm Runtime Orchestrator (spec 001) is already implemented and working according to its own quickstart, and focuses specifically on the path where an external ACP client talks to the swarm via the mux.

> This is **not** an implementation guide; it assumes the runtime, ACP integrations, and Swarm ACP server adapter have been implemented according to the spec, plan, and contracts.

## 1. Prerequisites

- Python 3.11+ installed and available on `PATH`.
- The `nate_ntm` repository cloned locally and installed in editable mode:

  ```bash
  cd /path/to/nate_ntm
  uv run pip install -e .
  ```

  (Adjust commands if the project provides a dedicated install script; the key requirement is that the `nate-ntm` CLI entrypoint is available.)

- External services available (real or mocked):
  - OpenHands agent server (for ACP/conversation handling).
  - Agent Mail service (for mailbox coordination).
- Any necessary credentials configured via environment variables or config files, per project documentation.

- The Swarm Runtime Orchestrator (spec 001) working end-to-end:
  - You can start the runtime daemon in `create` and `resume` modes.
  - `runtime.get_status`, `swarm.get_overview`, and `agent.get_detail` work via the runtime control API.

- A Swarm ACP server adapter that:
  - Accepts ACP connections from external clients.
  - Creates a `SwarmACPMux` instance per external ACP session.
  - Routes reserved swarm-control operations (`_attach`, `_detach`, `_swarm_status`, `_agent_detail`, ...) to mux/runtime helpers.
  - Forwards ordinary ACP requests to the currently attached agent.

- An ACP-capable client or test harness able to:
  - Establish an ACP session to the Swarm ACP server.
  - Send `SessionUpdate` messages with named updates and JSON payloads.
  - Receive and display `SessionUpdate` messages from the server.

## 2. Start the Runtime and Swarm

1. **Start the runtime daemon** (create or resume a swarm) as in the orchestrator quickstart. For example:

   ```bash
   nate-ntm runtime start \
     --project /abs/path/to/your/project \
     --mode create \
     --agents 1 \
     --with-control-api
   ```

   Leave this running in one terminal.

2. **Confirm runtime status** from another terminal:

   ```bash
   nate-ntm api call runtime.get_status
   ```

   You should see the runtime in `Running` state with at least one agent.

## 3. Start the Swarm ACP Server Adapter

In a new terminal, start the Swarm ACP server adapter that integrates with the runtime and exposes ACP over (for example) a WebSocket endpoint:

```bash
nate-ntm acp server start \
  --project /abs/path/to/your/project \
  --runtime-api ws://127.0.0.1:<runtime-port> \
  --bind 127.0.0.1:<acp-port>
```

The concrete command-line shape will depend on the adapter implementation; the important behaviors are:

- Each external ACP connection results in a new `SwarmACPMux` instance.
- The adapter decodes `SessionUpdate` messages from the client, detects reserved updates, and calls into mux/runtime helpers as described in the contracts.

## 4. Attach to an Agent and Replay Events

1. **Connect an ACP client** to the Swarm ACP server (for example, using an ACP test harness or a CLI tool).

2. **Request swarm status** via a reserved update (shape approximated):

   ```jsonc
   // Client -> Server
   {
     "session": "s-001",
     "update": {
       "name": "_swarm_status",
       "payload": {}
     }
   }
   ```

   **Expected outcome:**
   - You receive a `SessionUpdate` describing the current swarm: runtime status, agent counts, and a list of agents.

3. **Choose an `agent_id`** from the status response.

4. **Attach to that agent** via `_attach`:

   ```jsonc
   // Client -> Server
   {
     "session": "s-001",
     "update": {
       "name": "_attach",
       "payload": {
         "agent_id": "agent-1",
         "max_events": 50
       }
     }
   }
   ```

   **Expected outcome:**
   - The mux validates that `agent-1` exists and is attachable.
   - The mux subscribes to that agent's `AgentEventStream` with a replay limit of ~50 events.
   - You receive a sequence of `SessionUpdate` messages corresponding to recent events for `agent-1`, followed by live events.

## 5. Send Work and Observe Updates

1. **Send a normal ACP request** (for example, a prompt or tool call) to the attached agent:

   ```jsonc
   // Client -> Server
   {
     "session": "s-001",
     "update": {
       "name": "user_message",
       "payload": {
         "content": "Summarize the current project status." }
     }
   }
   ```

   (The exact update name and payload depend on the ACP schema you use; this is illustrative.)

2. **Observe responses and intermediate updates** over the same ACP session:

   - Turn start / completion notifications.
   - Tool calls and results (if any).
   - Error updates if the agent or tools fail.

3. **Optionally, attach a second observer** using the runtime control API:

   - Call `agent.get_detail` via the runtime API for the same `agent_id`.
   - Optionally, subscribe via an events/streaming API if available.

   **Expected outcome:**
   - Both the SwarmACPMux-driven ACP client and the runtime API observer see a consistent sequence of events for the agent (within the bounds of their respective APIs).

## 6. Detach and Clean Up

1. **Detach from the agent** using `_detach`:

   ```jsonc
   // Client -> Server
   {
     "session": "s-001",
     "update": {
       "name": "_detach",
       "payload": {}
     }
   }
   ```

   **Expected outcome:**
   - The mux cancels its event subscription and forwarding task for `agent-1`.
   - The external session is no longer associated with any agent.
   - The agent itself continues running in the runtime.

2. **Verify swarm status again** with `_swarm_status`:

   - The swarm status should still show the agent as present and running.

3. **Close the ACP session** and shut down the Swarm ACP server adapter and runtime daemon when finished.

## 7. Validation Checklist (Mapped to Spec 008 Goals)

- **SC-008-01 (Attachment & Replay)**:
  - [ ] After `_attach`, the client receives a bounded replay of recent events for the chosen agent, followed by live events.

- **SC-008-02 (Forwarding of Agent Updates)**:
  - [ ] Ordinary ACP updates sent by the client (e.g., prompts) are routed to the attached agent and result in corresponding updates on the same ACP session.

- **SC-008-03 (Reserved Control Routing)**:
  - [ ] `_swarm_status` and `_agent_detail` are handled by the mux/runtime and do **not** appear as tool calls or messages inside the agent conversation.

- **SC-008-04 (Multiple Subscribers)**:
  - [ ] With a runtime observer (e.g., `agent.get_detail` or an events subscription) watching the same agent, both observers see consistent sequences of events.

- **SC-008-05 (Detach Semantics)**:
  - [ ] `_detach` stops further events being delivered to the ACP session, but the agent remains running and visible in swarm status.

## 8. Notes

- This quickstart assumes a single Runtime instance and a single Swarm ACP server per project. Running multiple independent swarms or ACP servers requires separate processes.
- Error codes and detailed payload shapes are defined in the contracts under `specs/008-swarm-acp-mux/contracts/` and may evolve over time; always consult the contract documents when writing new tests or clients.
