# nate-ntm ACP Client API

This document describes how to connect an ACP client to a running `nate-ntm` swarm runtime.

`nate-ntm` exposes a normal ACP agent endpoint plus four underscore-prefixed extension methods for selecting and inspecting agents inside a swarm:

- `_swarm_status`
- `_agent_detail`
- `_attach`
- `_detach`

After attaching to an internal agent, the client uses ordinary ACP `session/prompt`, `session/cancel`, and `session/update` messages. The client does not need a separate ACP connection for every agent.

## Runtime model

A `nate-ntm` runtime owns a materialized swarm. Each swarm contains one or more internal ACP agents. An external ACP connection is represented by a connection-scoped multiplexer with at most one attached internal agent.

Attachment is local to the external TCP connection:

- Different clients may attach independently.
- One client may switch agents by calling `_attach` again.
- Prompts and interrupts are routed to the currently attached agent.
- Session updates from only the currently attached agent are forwarded to that client.
- Closing the TCP connection discards its attachment without changing the persisted swarm.

The external ACP `session_id` identifies the external client session. It is not an internal agent's persisted conversation ID. The runtime maintains those internal conversation IDs itself.

## Starting nate-ntm

A swarm must first be materialized with `swarm create`. For example:

```bash
nate-ntm swarm create \
  --agent planner.json \
  --agent implementer.json \
  --constructor agent-mail
```

The command prints the generated swarm ID. Persisted state is stored at:

```text
~/.nate-ntm/swarms/<swarm-id>/swarm.json
```

Start the existing swarm runtime by ID:

```bash
nate-ntm runtime start --swarm-id <swarm-id>
```

The external ACP endpoint defaults to:

```text
tcp://127.0.0.1:8766
```

The bind address can be changed with:

```bash
nate-ntm runtime start \
  --swarm-id <swarm-id> \
  --acp-host 127.0.0.1 \
  --acp-port 9000
```

The same values may be supplied through `NATE_NTM_ACP_HOST` and `NATE_NTM_ACP_PORT`.

`nate-ntm` also starts an HTTP control API, but ACP clients do not need it. The ACP endpoint is the raw TCP endpoint printed as `Swarm ACP: tcp://...` during startup.

## Transport and framing

The external endpoint uses the Python ACP SDK's stream protocol over a raw TCP connection:

- TCP, not stdio, HTTP, or WebSocket
- JSON-RPC 2.0 ACP messages
- the framing implemented by `acp.connection.Connection`
- server-to-client updates use the standard ACP `session/update` notification

Client implementations should reuse their ACP SDK's stream connection implementation where possible. In the Python ACP SDK, `nate-ntm` connects with `asyncio.open_connection()` and `acp.connect_to_agent()`.

A minimal Python connection looks like this:

```python
import asyncio

from acp import connect_to_agent


async def connect(client_callbacks, host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)
    connection = connect_to_agent(client_callbacks, writer, reader)
    return connection, writer
```

The repository also provides a typed reference client at:

```text
src/nate_ntm/runtime/swarm_acp_client.py
```

Its `SwarmACPClient.connect(...)` method is the clearest executable example.

## Recommended client flow

1. Open one TCP ACP connection.
2. Call `_swarm_status` to discover available agents.
3. Call `_attach` with the selected `agent_id`.
4. Wait for the `_attach` response.
5. Use ordinary ACP `session/prompt` and `session/cancel` operations.
6. Process ordinary ACP `session/update` notifications.
7. Call `_detach` or close the connection when finished.

The client must not send a prompt before attaching an agent.

## Extension method invocation

The Python ACP SDK exposes arbitrary extension methods through `ClientSideConnection.ext_method()`.

The SDK method name passed to `ext_method()` omits the leading underscore; the SDK emits an underscore-prefixed JSON-RPC method on the wire:

```python
result = await connection.ext_method("swarm_status", {})
# Wire method: _swarm_status
```

This is how the repository's typed client invokes all four extensions:

```python
await connection.ext_method("attach", {"agent_id": "planner"})
await connection.ext_method("detach", {})
await connection.ext_method("swarm_status", {})
await connection.ext_method("agent_detail", {"agent_id": "planner"})
```

Clients that construct JSON-RPC messages directly must use the actual underscore-prefixed wire names documented below.

## `_swarm_status`

Returns the current connection's attachment and a runtime overview of the swarm.

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "_swarm_status",
  "params": {}
}
```

`params` must be an empty object.

### Result

```json
{
  "attached_agent_id": null,
  "swarm": {
    "swarm_id": "d84a...",
    "project_path": "/home/user/project",
    "runtime_status": "Running",
    "agent_counts": {
      "total": 2,
      "starting": 0,
      "idle": 2,
      "running": 0,
      "waiting": 0,
      "failed": 0
    },
    "agents": [
      {
        "agent_id": "planner",
        "display_name": "Planner",
        "status": "Idle",
        "has_unread_mail": false,
        "last_error": null
      }
    ]
  }
}
```

The exact overview may gain additional fields. Clients should ignore fields they do not recognize.

## `_agent_detail`

Returns details for one internal agent and whether it is attached to the current external connection.

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "_agent_detail",
  "params": {
    "agent_id": "planner"
  }
}
```

`agent_id` is required and must be a string.

The server accepts an optional integer `max_events` field for forward-compatible event-history limiting, although the current agent-detail result does not expose an `events` collection.

### Result

```json
{
  "attached": false,
  "agent": {
    "agent_id": "planner",
    "display_name": "Planner",
    "status": "Idle",
    "agent_mail_identity": "planner",
    "conversation_id": "opaque-internal-session-id",
    "last_error": null
  }
}
```

The internal `conversation_id` is informational. External clients should not pass it as their own ACP session ID or use it to open a direct connection to the internal agent.

## `_attach`

Selects the internal agent that receives subsequent standard ACP prompts and interrupts on this TCP connection.

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "_attach",
  "params": {
    "agent_id": "planner"
  }
}
```

### Result

```json
{
  "attached_agent_id": "planner"
}
```

### Ordering guarantee

`_attach` is a three-stage transaction:

1. subscribe to the internal agent's update stream;
2. send the successful `_attach` response;
3. begin forwarding retained and live `session/update` notifications.

Therefore, a correct client observes the `_attach` response before any updates released by that attachment. This matters when an internal agent already has retained updates waiting.

Calling `_attach` for the already attached agent is idempotent. Calling it for another agent replaces the current attachment and its update subscription.

`_attach`, `_detach`, and connection shutdown are serialized per external connection.

## `_detach`

Removes the current attachment from this TCP connection.

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "_detach",
  "params": {}
}
```

`params` must be an empty object.

### Result

```json
{
  "detached": true
}
```

Detach is idempotent. Detaching when nothing is attached still succeeds.

After detaching, ordinary prompts and interrupts fail until another `_attach` succeeds.

## Standard ACP operations after attachment

### Prompt

Send a normal ACP `session/prompt` request using the external session ID chosen by the client.

The server currently forwards text content to the attached internal agent. Multiple text blocks are concatenated in order. Non-text blocks are currently ignored at the swarm boundary.

The immediate response is a valid ACP `PromptResponse` with `stop_reason` set to `end_turn`. Agent output and telemetry arrive through standard `session/update` notifications.

Example using the Python SDK:

```python
from acp import text_block

response = await connection.prompt(
    session_id="my-external-session",
    prompt=[text_block("Implement the next task")],
)
```

### Interrupt

Send the normal ACP `session/cancel` operation using the same external session ID:

```python
await connection.cancel(session_id="my-external-session")
```

The interrupt is routed to the currently attached internal agent.

### Session updates

The runtime forwards typed internal updates as ordinary ACP `session/update` notifications. The notification's `sessionId` is the external session ID for this TCP connection, not the internal agent's conversation ID.

A client should use the same update callback it uses for any other ACP agent.

## Errors

The server uses standard JSON-RPC/ACP error envelopes. Stable nate-ntm-specific logical codes are placed in:

```json
{
  "error": {
    "data": {
      "mux_code": "MUX_NO_ATTACHED_AGENT"
    }
  }
}
```

Known `mux_code` values are:

| Code | Meaning |
| --- | --- |
| `MUX_CLOSED` | The connection-scoped multiplexer is closed. |
| `MUX_NO_ATTACHED_AGENT` | A prompt or interrupt was attempted before attachment. |
| `MUX_UNKNOWN_AGENT` | The requested `agent_id` is not in the swarm. |
| `MUX_AGENT_SESSION_NOT_ACTIVE` | The internal agent does not have an active ACP session. |
| `MUX_STALE_ATTACHMENT` | An attachment transaction became stale before activation. |
| `MUX_INVALID_REQUEST` | An extension name or payload is malformed or unsupported. |
| `MUX_INTERNAL_ERROR` | An unexpected runtime failure occurred. |

Malformed parameters and unsupported underscore-prefixed methods map to the JSON-RPC `Invalid params` category with `MUX_INVALID_REQUEST`. Most other mux failures map to JSON-RPC `Internal error` while preserving the more useful `mux_code` in `error.data`.

Clients should branch on `error.data.mux_code`, not on human-readable error messages.

## Connection lifecycle

Each accepted TCP connection owns exactly one `SwarmACPMux` and one attachment state.

The server closes the connection if either:

- inbound ACP processing ends; or
- the mux's update-forwarding task fails.

When the connection closes, the runtime cancels the connection's forwarding subscription and releases its attachment. It does not stop the internal agent or delete swarm state.

Clients should:

- treat EOF as the end of the external ACP session;
- reconnect and call `_attach` again after a transport failure;
- not assume attachment survives reconnection;
- close both the ACP connection and TCP writer cleanly.

## Complete Python example

```python
from acp import text_block
from acp.interfaces import Client

from nate_ntm.runtime.swarm_acp_client import SwarmACPClient


async def run(client_callbacks: Client) -> None:
    async with await SwarmACPClient.connect(
        client_callbacks,
        "127.0.0.1",
        8766,
        session_id="my-client-session",
    ) as swarm:
        status = await swarm.swarm_status()
        agents = status.swarm["agents"]
        if not agents:
            raise RuntimeError("The swarm has no agents")

        agent_id = agents[0]["agent_id"]
        await swarm.attach(agent_id)

        response = await swarm.prompt([text_block("Hello from my ACP client")])
        print(response.stop_reason)

        await swarm.detach()
```

A client outside the `nate-ntm` Python package can implement the same behavior with its own ACP SDK by adding four extension-method wrappers and preserving the attach-before-prompt lifecycle.

## Compatibility guidance

The underscore prefix reserves these names as nate-ntm ACP extensions. Unknown underscore-prefixed methods are rejected.

For forward compatibility:

- ignore unknown fields in successful extension results;
- preserve standard ACP behavior for prompts, cancellation, and updates;
- inspect `error.data.mux_code` for nate-ntm-specific failures;
- discover agents with `_swarm_status` rather than assuming IDs;
- attach again after reconnecting;
- do not depend on internal conversation IDs.
