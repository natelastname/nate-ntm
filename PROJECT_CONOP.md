# nate_ntm Concept of Operations (CONOP)

# 1. Purpose

`nate_ntm` is a long-running orchestration runtime for managing swarms of OpenHands-compatible coding agents.

Its purpose is to bridge three independent systems:

- **OpenHands ACP**, which provides structured control of agent execution.
- **`mcp_agent_mail`**, which provides durable inter-agent coordination.
- **Human operators and tooling**, which observe and steer the swarm.

Unlike traditional terminal-based orchestrators, `nate_ntm` does not automate interactive CLIs through terminal keystrokes. Instead, it communicates directly with OpenHands agents using ACP and exposes its own control interface for user interfaces and external automation.

# 2. System Responsibilities

`nate_ntm` owns the runtime lifecycle of a swarm.

Specifically, it is responsible for:

- spawning OpenHands-compatible agent subprocesses,
- maintaining ACP connections to each agent,
- creating and managing Agent Mail identities,
- supervising agent lifecycle,
- polling Agent Mail,
- deciding when idle agents should be resumed,
- injecting mailbox-derived prompts,
- exposing runtime state through a local API,
- maintaining recent ACP event history for live inspection.

It is **not** responsible for durable conversation history (owned by OpenHands) or durable coordination state (owned by Agent Mail).

# 3. High-Level Architecture

```
                 User Interface(s)
                  CLI / TUI / Web
                        │
                        │ JSON-RPC over WebSocket
                        ▼
                +-------------------+

                |    nate_ntm       |
                |-------------------|
                | Scheduler         |
                | ACP Clients       |
                | Agent Registry    |
                | Event Buffers     |
                | Agent Mail Client |
                +-------------------+
                   │ │
              ACP │ │ MCP
                   ▼ ▼
           OpenHands mcp_agent_mail
             Agents Server
```

The runtime is the sole owner of ACP connections.

User interfaces never communicate directly with agent subprocesses.

# 4. Execution Model

Each managed agent has three identities.

## Runtime Identity

Local runtime metadata.

Example:

- runtime id
- status
- current turn
- subprocess handle
- conversation id

## ACP Identity

Represents the active ACP session between `nate_ntm` and the agent subprocess.

Only the runtime communicates over ACP.

## Agent Mail Identity

Persistent identity used for inter-agent coordination.

Example:

- BlueLake
- GreenCastle
- RedStone

This identity survives process restarts.

# 5. Swarm Startup

When creating a swarm:

```
nate_ntm spawn /abs/path/to/project
```

the runtime:

1. ensures the Agent Mail project exists,
2. creates or restores swarm metadata,
3. creates or restores Agent Mail identities,
4. launches OpenHands subprocesses,
5. establishes ACP sessions,
6. records each conversation id,
7. starts the scheduler.

# 6. Resume Model

Resume is a first-class capability.

Each swarm persists sufficient metadata to reconstruct itself.

Per-agent state includes:

- Agent Mail identity
- Agent Mail credentials
- OpenHands conversation id
- launch configuration
- model
- task description

When resuming:

```
nate_ntm resume PROJECT
```

the runtime:

1. reloads swarm metadata,
2. restarts each subprocess,
3. reconnects using the stored OpenHands conversation id,
4. restores the same Agent Mail identity,
5. fetches unread mailbox state,
6. resumes scheduler operation.

OpenHands is the canonical owner of conversation history.

`nate_ntm` stores only the information required to reconnect.

# 7. Scheduler

The scheduler owns swarm progress.

Responsibilities include:

- polling Agent Mail,
- identifying idle agents with pending work,
- constructing mailbox prompts,
- initiating ACP turns,
- tracking active turns,
- restarting failed agents,
- enforcing retry policies,
- acknowledging completed mail.

Agent Mail never wakes agents directly.

The scheduler is the component that converts mailbox state into new ACP turns.

# 8. Agent Lifecycle

Typical lifecycle:

- Starting
- Idle
- Running (triggered by mail or user work)
- Waiting (after turn completion)
- Idle (after scheduler action)

Failure transitions:

- Running
- Failed (when process exits)
- Starting (after restart policy)

Graceful shutdown is always preferred.

The runtime should:

1. request cancellation through ACP,
2. wait for completion,
3. terminate subprocess,
4. force kill only after timeout.

# 9. ACP Event Model

`nate_ntm` is the sole consumer of ACP event streams.

For each agent, it maintains an in-memory ring buffer containing the most recent ACP events.

This enables:

- live attach,
- fast UI startup,
- reconnecting interfaces,
- inspection of recent activity.

The ring buffer is **not** the canonical conversation history.

Durable replay is provided by OpenHands using the stored conversation id.

# 10. User Interface Model

User interfaces are independent clients.

Examples include:

- terminal dashboard,
- command-line utilities,
- web UI,
- editor integrations.

They connect to the runtime rather than directly to agents.

```
UI
 │
 ▼
JSON-RPC over WebSocket
 │
 ▼
nate_ntm
```

The runtime multiplexes ACP events to any interested UI.

Multiple interfaces may attach simultaneously.

# 11. Runtime API

The runtime exposes a local JSON-RPC API over WebSocket.

The precise protocol is intentionally left unspecified.

Its responsibilities include:

- swarm inspection,
- agent inspection,
- event subscriptions,
- runtime control,
- user interaction,
- scheduler interaction.

The protocol is bidirectional.

Clients send requests.

The runtime pushes asynchronous notifications, including:

- ACP events,
- agent state changes,
- scheduler events,
- mailbox events.

This API is intended to become the single integration point for all frontends.

# 12. MVP User Experience

The initial interface is a terminal dashboard.

Top section:

- swarm status
- project
- running agents
- idle agents
- failed agents
- unread mailbox counts

Bottom section:

- one row per agent
- status
- current task
- current turn
- last activity

Selecting an agent opens a live ACP event viewer.

The viewer displays:

- replay of the in-memory event buffer,
- live streamed ACP events,
- runtime status changes.

The UI never communicates directly with OpenHands.

All interaction passes through the runtime.

# 13. Design Principles

1. OpenHands owns conversation durability.
2. Agent Mail owns coordination durability.
3. `nate_ntm` owns runtime supervision.
4. ACP is the exclusive control protocol for agents.
5. User interfaces communicate only with the runtime.
6. Runtime state is authoritative while the swarm is executing.
7. Swarms must be resumable without loss of agent identity or conversation continuity.
