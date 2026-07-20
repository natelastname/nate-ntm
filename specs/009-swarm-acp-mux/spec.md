# SwarmACPMux

## Purpose

`SwarmACPMux` builds on the typed ACP session streaming layer introduced in Epic 008.

> Build `SwarmACPMux`, which multiplexes multiple independent ACP sessions into a single swarm-facing update stream while preserving typed ACP semantics.

Concretely, for each external "swarm ACP" session, `SwarmACPMux`:

- exposes swarm-level control operations (for example `_attach`, `_detach`, `_swarm_status`, `_agent_detail`);
- attaches that external session to **one agent at a time**, but may switch attachments over its lifetime;
- subscribes to the attached agent's typed ACP session updates via `subscribe_acp_updates()`;
- forwards those typed updates into a single, ordered swarm-facing session stream.

`SwarmACPMux` does **not** replace the ACP transport or stream implementation. It is a thin routing layer that multiplexes existing per-session streams into one swarm-level view.

Ownership is divided as follows:

```
RuntimeDaemon
    owns swarm state and swarm-level status

NateOhaAcpClient / AcpAgentSession
    own per-agent ACP sessions and per-session update streams

AcpSessionUpdateStream + subscribe_acp_updates()  (Epic 008)
    own typed ACP SessionUpdate delivery, replay, ordering, overflow and closure semantics

SwarmACPMux (Epic 009)
    owns swarm-facing attachment and routing over typed updates

Swarm ACP server adapter
    owns ACP protocol decoding/encoding and reserved control dispatch
```

This design assumes Epic 008 has already delivered:

- `AcpSessionUpdateStream` and `ReceivedSessionUpdate`;
- a per-session, session-owned update stream on `AcpAgentSession`;
- the canonical `subscribe_acp_updates()` API;
- direct typed `SessionUpdate` publication from ACP callbacks; and
- ACP updates no longer routed through `AgentEvent` for transport (they may still be summarized into `AgentEvent` for observability).

------------------------------------------------------------------------

## Location

The class should live in:

```
src/nate_ntm/runtime/swarm_acp_mux.py
```

This places it beside the runtime components it coordinates:

```
src/nate_ntm/runtime/
├── acp_client.py
├── acp_protocol_client.py
├── agents.py
├── daemon.py
├── events.py
├── state.py
├── swarm_acp_mux.py
└── swarm_state.py
```

`NateOhaAcpClient` remains responsible for ACP connections to individual agents. `SwarmACPMux` represents the external connection into the swarm as a whole.

------------------------------------------------------------------------

## Architecture

The mux participates in two distinct paths.

### External control and request path

```
Customized external ACP client

        |
        | ACP requests and reserved sessionUpdate controls
        v
Swarm ACP server adapter

        |
        | explicit SwarmACPMux method calls
        v
SwarmACPMux

        |
        | ordinary attached-agent requests
        v
NateOhaAcpClient

        |
        v
nate-oha ACP process
```

The customized external client may be an `agent-shell` implementation that understands swarm-specific reserved updates.

Examples include:

```
_attach
_detach
_swarm_status
_agent_detail
```

These are incoming client-to-swarm control operations.

### Swarm session update path

At the update-stream boundary established by Epic 008, the architecture is:

```
AcpAgentSession
        ↓
subscribe_acp_updates()
        ↓
SwarmACPMux
        ↓
Swarm session stream
        ↓
Swarm runtime / external ACP client
```

More concretely, for a single attached agent:

- `AcpAgentSession` owns a per-session `AcpSessionUpdateStream`.
- `NateOhaAcpClient.subscribe_acp_updates(agent_id)` exposes that stream as an async iterator of `ReceivedSessionUpdate` values.
- `SwarmACPMux` consumes that iterator for the currently attached agent and forwards each typed `SessionUpdate` to the external ACP connection via `ExternalACPConnection.session_update(...)`.
- Over its lifetime, the mux may detach and reattach, thereby multiplexing multiple independent per-agent ACP sessions into one swarm-facing session stream.

`SwarmACPMux` does not reimplement replay, overflow, or subscriber semantics; those are provided by `AcpSessionUpdateStream` and `subscribe_acp_updates()` (Epic 008).

------------------------------------------------------------------------

## Connection scope

One `SwarmACPMux` instance should be created for each external ACP session.

Its state is connection-local:

```
@dataclass(slots=True)
class SwarmACPMux:
    daemon: RuntimeDaemon
    agent_client: SwarmAgentClient
    external_connection: ExternalACPConnection
    external_session_id: str

    attached_agent_id: str | None = None
    _forwarding_task: asyncio.Task[None] | None = None
    _closed: bool = False
```

The mux owns:

- the currently attached agent ID;
- the forwarding task for that attachment;
- the external ACP session ID;
- connection-local closed/open state.

The runtime services supplied to the mux retain ownership of swarm state, agent sessions, retained history, and subscriber queues.

------------------------------------------------------------------------
## Responsibilities and non-goals

Epic 009 (SwarmACPMux) owns:

- creating and managing one `SwarmACPMux` per external swarm ACP session;
- subscribing to per-agent typed ACP update streams via `subscribe_acp_updates()`;
- multiplexing those updates into a single swarm-facing session stream per external connection;
- preserving required ordering guarantees at the swarm boundary (for example, attach acknowledgments before replay, and per-agent in-order delivery as provided by Epic 008);
- coordinating attachment and detachment lifecycle for the external session;
- routing swarm-level control operations to `RuntimeDaemon` (for status and detail) and to the attached agent (for prompt/interrupt);
- exposing swarm-facing APIs used by the Swarm ACP server adapter.

Epic 009 explicitly does **not** own:

- ACP transport implementation or wire protocol details;
- implementation of per-session `AcpSessionUpdateStream` or its buffering policies;
- ACP replay, ordering, overflow, or closure semantics (these are specified in Epic 008);
- low-level subscriber management for ACP streams.

Those concerns are provided by the ACP integration layer and Epic 008; `SwarmACPMux` treats `subscribe_acp_updates()` as a stable, already-validated interface.

------------------------------------------------------------------------


## Interfaces

### SwarmAgentClient

The mux depends on the narrow, typed ACP interface it actually uses:

```
class SwarmAgentClient(Protocol):
    def subscribe_acp_updates(
        self,
        agent_id: str,
    ) -> AbstractAsyncContextManager[AsyncIterator[ReceivedSessionUpdate]]:
        “""Yield retained updates, followed by live updates.”""

    async def prompt(
        self,
        agent_id: str,
        prompt: str,
    ) -> str | None:
        …

    async def interrupt(self, agent_id: str) -> None:
        …
```

`NateOhaAcpClient` implements this protocol by delegating to the per-session `AcpSessionUpdateStream` via its `subscribe_acp_updates()` method from Epic 008. The mux does not depend on how that stream is implemented; it treats `subscribe_acp_updates()` as the stable boundary for consuming typed ACP updates.

### ExternalACPConnection

The outbound connection should accept the ACP session-update type expected by the outer server integration:

```
class ExternalACPConnection(Protocol):
    async def session_update(
        self,
        *,
        session_id: str,
        update: SessionUpdate,
    ) -> None:
        …
```

`SessionUpdate` represents the ACP SDK session-update union or the project's equivalent typed abstraction.

`SwarmACPMux` receives this type from `ReceivedSessionUpdate.update` values yielded by `subscribe_acp_updates()` (Epic 008) and forwards it directly. Any translation between ACP SDK types and the runtime's normalized `AgentEvent` telemetry remains the responsibility of the ACP integration and runtime event pipeline, not the mux.

Metadata on `ReceivedSessionUpdate` (for example `sequence` and `received_at`) are **not** forwarded over ACP. They are strictly runtime-internal diagnostics that may be used for logging, metrics, or to enrich `AgentEvent`-style observability, but the mux always forwards the underlying typed `SessionUpdate` object unchanged.


------------------------------------------------------------------------

## Constructor

```
def __init__(
    self,
    *,
    daemon: RuntimeDaemon,
    agent_client: SwarmAgentClient,
    external_connection: ExternalACPConnection,
    external_session_id: str,
) -> None:
    …
```

Construction initializes connection-local state and stores the runtime services.

The initial state is:

```
attached_agent_id = None
_forwarding_task = None
_closed = False
```

Agent attachment occurs explicitly through `attach()`.

------------------------------------------------------------------------

## Public methods

### attach

```
async def attach(self, agent_id: str) -> None:
    …
```

Attaches the external ACP session to an existing swarm agent.

Behavior:

1. verify that the mux is open;
2. validate the agent against durable swarm membership;
3. return immediately when the same healthy attachment already exists;
4. detach the previous event subscription;
5. establish a replay-capable subscription to the new agent;
6. record the new attachment.

Conceptually:

```
async def attach(self, agent_id: str) -> None:
    self._ensure_open()
    self._require_known_agent(agent_id)

    if (
        self.attached_agent_id == agent_id
        and self._forwarding_task is not None
        and not self._forwarding_task.done()
    ):
        return

    await self.detach()

    self.attached_agent_id = agent_id
    self._forwarding_task = asyncio.create_task(
        self._forward_session_updates(agent_id),
        name=f"swarm-acp-mux:{agent_id}”,
    )
```

The attachment acknowledgment returned by the outer ACP server should clearly identify the attached agent. This acknowledgment forms the visible boundary between events from the previous and new attachments.

Switching agents is a supported operation.

------------------------------------------------------------------------

### detach

```
async def detach(self) -> None:
    …
```

Detaches the external ACP session from its current agent.

Behavior:

- clear the connection-local attachment;
- cancel and await the forwarding task;
- leave the agent process and ACP session running.

```
async def detach(self) -> None:
    task = self._forwarding_task

    self._forwarding_task = None
    self.attached_agent_id = None

    if task is None:
        return

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass
```

Agent lifecycle remains under runtime ownership.

------------------------------------------------------------------------

### prompt

```
async def prompt(self, text: str) -> str | None:
    …
```

Forwards an ordinary prompt to the attached agent:

```
async def prompt(self, text: str) -> str | None:
    self._ensure_open()
    agent_id = self._require_attached_agent()
    return await self.agent_client.prompt(agent_id, text)
```

------------------------------------------------------------------------

### interrupt

```
async def interrupt(self) -> None:
    …
```

Forwards an interrupt to the attached agent:

```
async def interrupt(self) -> None:
    self._ensure_open()
    agent_id = self._require_attached_agent()
    await self.agent_client.interrupt(agent_id)
```

------------------------------------------------------------------------

### get_swarm_status

```
def get_swarm_status(self) -> dict[str, object]:
    …
```

Returns runtime-level swarm status plus connection-local attachment state.

`RuntimeDaemon` should expose a reusable status API:

```
def get_swarm_status(self) -> dict[str, object]:
    …
```

A representative daemon-level payload is:

```
{
  “swarm_id”: “swarm-123”,
  “status”: “running”,
  “agents”: [
    {
      “agent_id”: “agent-1”,
      “display_name”: “Planner”,
      “status”: “running”,
      “conversation_id”: “conversation-1”,
      “last_error”: null
    }
  ]
}
```

The mux adds only connection-local information:

```
def get_swarm_status(self) -> dict[str, object]:
    self._ensure_open()

    return {
        “attached_agent_id”: self.attached_agent_id,
        “swarm”: self.daemon.get_swarm_status(),
    }
```

------------------------------------------------------------------------

### get_agent_detail

```
def get_agent_detail(
    self,
    agent_id: str,
    *,
    max_events: int = 100,
) -> dict[str, object]:
    …
```

Returns the existing daemon-level agent detail plus mux-local attachment status:

```
def get_agent_detail(
    self,
    agent_id: str,
    *,
    max_events: int = 100,
) -> dict[str, object]:
    self._ensure_open()
    self._require_known_agent(agent_id)

    return {
        “attached”: agent_id == self.attached_agent_id,
        “agent”: self.daemon.get_agent_detail(
            agent_id=agent_id,
            max_events=max_events,
        ),
    }
```

The daemon remains the authoritative source for agent metadata and retained event history.

------------------------------------------------------------------------

### close

```
async def close(self) -> None:
    …
```

Closes the connection-scoped mux:

```
async def close(self) -> None:
    if self._closed:
        return

    self._closed = True
    await self.detach()
```

The mux should support async context-manager use:

```
async def __aenter__(self) -> “SwarmACPMux”:
    self._ensure_open()
    return self

async def __aexit__(
    self,
    exc_type,
    exc,
    traceback,
) -> None:
    await self.close()
```

------------------------------------------------------------------------

## Internal methods

### \_forward_session_updates


This coroutine implements the attached-agent output path over typed ACP updates.

The subscription yields retained history first, then live updates as defined by Epic 008:

```
async def _forward_session_updates(self, agent_id: str) -> None:
    current_task = asyncio.current_task()

    try:
        async with self.agent_client.subscribe_acp_updates(agent_id) as updates:
            async for received in updates:
                await self._forward_external_update(received)
    finally:
        if (
            self.attached_agent_id == agent_id
            and self._forwarding_task is current_task
        ):
            self.attached_agent_id = None
            self._forwarding_task = None
```

When the per-agent update stream closes normally, the mux remains open and becomes unattached.

A subsequent reserved `_attach` operation may attach it to another agent.

An exception while writing to the external ACP connection should terminate this forwarding task and propagate to the outer connection handler. The outer handler then closes the connection-scoped mux and transport.

------------------------------------------------------------------------

### \_forward_external_update


Forwards one typed ACP update to the external session:

```
async def _forward_external_update(
    self,
    received: ReceivedSessionUpdate,
) -> None:
    await self.external_connection.session_update(
        session_id=self.external_session_id,
        update=received.update,
    )
```

`SwarmACPMux` does not inspect or transform the `SessionUpdate`; it simply forwards the typed value obtained from the underlying `ReceivedSessionUpdate` objects.

The mux forwards the resulting update without interpreting ordinary agent output.

------------------------------------------------------------------------

### \_require_attached_agent

```
def _require_attached_agent(self) -> str:
    if self.attached_agent_id is None:
        raise NoAttachedAgentError(
            “No agent is attached to this ACP connection"
        )

    return self.attached_agent_id
```

------------------------------------------------------------------------

### \_require_known_agent

```
def _require_known_agent(self, agent_id: str) -> AgentState:
    try:
        return self.daemon.swarm_state.agents[agent_id]
    except KeyError as exc:
        raise UnknownAgentError(agent_id) from exc
```

Durable `SwarmState.agents` is the authority for swarm membership.

------------------------------------------------------------------------

### \_ensure_open

```
def _ensure_open(self) -> None:
    if self._closed:
        raise SwarmACPMuxClosedError()
```

------------------------------------------------------------------------

## Reserved swarm-control protocol

Reserved swarm-control operations are incoming ACP updates from the customized external client whose protocol-level `sessionUpdate` name begins with `_`.

Examples:

```
_attach
_detach
_swarm_status
_agent_detail
```

The outer swarm ACP server adapter owns detection and dispatch.

Conceptually:

```
async def handle_external_update(
    mux: SwarmACPMux,
    update: SessionUpdate,
) -> None:
    name = update.session_update

    if name.startswith(“_”):
        await dispatch_reserved_update(mux, update)
        return

    await proxy_ordinary_update(mux, update)
```

A representative dispatch table is:

|                          |                                  |
|--------------------------|----------------------------------|
| Reserved `sessionUpdate` | Mux operation                    |
| `_attach`                | `await mux.attach(agent_id)`     |
| `_detach`                | `await mux.detach()`             |
| `_swarm_status`          | `mux.get_swarm_status()`         |
| `_agent_detail`          | `mux.get_agent_detail(agent_id)` |

Unknown underscore-prefixed control updates produce a structured unsupported-operation error:

```
class UnsupportedReservedUpdateError(SwarmACPMuxError):
    pass
```

The outer ACP server adapter converts domain errors into the appropriate ACP error response.

### Agent-emitted custom updates

An attached agent may also emit a custom underscore-prefixed ACP update.

Such updates travel through the ordinary per-agent publication path:

```
agent
    -> NateOhaAcpClient
    -> retained event stream
    -> all internal subscribers
```

Their visibility to the external client is defined separately by the swarm ACP protocol.

The default mux behavior is transparent forwarding unless the protocol explicitly defines an agent-output filtering rule.

This preserves one simple attached-agent forwarding path.

------------------------------------------------------------------------

## Replay-capable session update delivery (Epic 008 dependency)

Attaching to an agent must produce one continuous, ordered stream of typed ACP session updates:

1. retained per-session updates from the bounded history; then
2. all subsequent live updates.

`SwarmACPMux` consumes this via the typed subscription API:

```
async with self.agent_client.subscribe_acp_updates(agent_id) as updates:
    async for received in updates:
        …
```

The replay and delivery semantics are owned entirely by the Epic 008 `AcpSessionUpdateStream` layer and its `subscribe()` / `subscribe_acp_updates()` helpers. In particular, that layer:

1. yields retained history followed by live updates on a single logical stream;
2. ensures that an update published during subscription establishment is delivered exactly once;
3. handles history truncation / overflow and backpressure, and multiplexes multiple subscribers.

`SwarmACPMux` treats these semantics as a given. Its responsibility is limited to consuming `ReceivedSessionUpdate` values and forwarding the embedded `SessionUpdate` objects to the external ACP connection.

------------------------------------------------------------------------

## Upstream dependencies

Epic 009 assumes several upstream capabilities that are primarily provided by Epic 008 and existing runtime components. This section summarizes those dependencies rather than re‑specifying their behavior.

### AcpSessionUpdateStream (Epic 008)

The runtime owns a per-agent, replay-capable stream of typed ACP session updates, implemented by `AcpSessionUpdateStream` (see `ACP_SESSION_UPDATE_STREAM.md`). For each agent/session, the stream:

- stores a bounded history of `ReceivedSessionUpdate` values;
- exposes a `subscribe()` async context manager that yields an `AsyncIterator[ReceivedSessionUpdate]`;
- is responsible for replay ordering, overflow policy, and multi-subscriber fan-out.

This stream is the single source of truth for `SessionUpdate` traffic inside the runtime.

### NateOhaAcpClient

`NateOhaAcpClient` bridges the ACP transport into the typed update stream. In particular it:

- accepts raw ACP protocol messages from the server adapter;
- converts them into typed `SessionUpdate` objects;
- publishes them into the agent's `AcpSessionUpdateStream` instance;
- exposes a mux-facing API:

```
def subscribe_acp_updates(
    self,
    agent_id: str,
) -> AbstractAsyncContextManager[AsyncIterator[ReceivedSessionUpdate]]:
    …
```

Other callers may use the same stream directly (for example via `iter_acp_updates()`), but `SwarmACPMux` only depends on `subscribe_acp_updates()`.

### RuntimeDaemon

Add or extend a helper:

```
def get_swarm_status(self) -> dict[str, object]:
    …
```

This method should serialize swarm-level runtime state once for reuse by:

- `SwarmACPMux`;
- CLI/status endpoints;
- diagnostics;
- future dashboards.

### ACP telemetry representation

The runtime's existing `AgentEvent` pipeline may continue to be used for logging and observability. When it projects ACP activity into events, it SHOULD:

- retain or embed the corresponding `SessionUpdate` (for example on an `acp_update` field); or
- capture enough normalized information to reconstruct the `SessionUpdate` if needed.

This is an observability concern only. `SwarmACPMux` never takes `AgentEvent` as input and does not call any `require_session_update()` helper; its only source of truth for ACP traffic is the typed stream of `ReceivedSessionUpdate` values.

### Swarm ACP server adapter

Add or extend the external ACP server integration so it:

- creates one `SwarmACPMux` per external session;
- detects underscore-prefixed incoming `sessionUpdate` names;
- dispatches reserved controls to mux methods;
- proxies ordinary ACP requests through the mux;
- translates mux domain errors into ACP errors;
- closes the mux when the external connection ends.

------------------------------------------------------------------------

## Error model

```
class SwarmACPMuxError(RuntimeError):
    pass

class SwarmACPMuxClosedError(SwarmACPMuxError):
    pass

class UnknownAgentError(SwarmACPMuxError):
    pass

class NoAttachedAgentError(SwarmACPMuxError):
    pass

class UnsupportedReservedUpdateError(SwarmACPMuxError):
    pass
```

The mux raises domain errors.

The outer ACP server adapter maps them to protocol responses.

External connection write failures propagate out of the forwarding task and terminate the connection-scoped mux.

------------------------------------------------------------------------

## Logging

Log mux lifecycle and failure boundaries:

- mux creation;
- attachment;
- detachment;
- normal agent-stream closure;
- unexpected forwarding-task termination;
- unsupported reserved update;
- external write failure;
- mux closure.

Useful fields include:

```
swarm_id
external_session_id
agent_id
update_name
event_id
```

Ordinary forwarded events may remain at debug or trace level.

------------------------------------------------------------------------

## Minimal class outline

```
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol

from nate_ntm.runtime.daemon import RuntimeDaemon
from nate_ntm.runtime.state import AgentState
from nate_ntm.runtime.acp_types import SessionUpdate
from nate_ntm.runtime.acp_update_stream import ReceivedSessionUpdate

class SwarmAgentClient(Protocol):
    def subscribe_acp_updates(
        self,
        agent_id: str,
    ) -> AbstractAsyncContextManager[AsyncIterator[ReceivedSessionUpdate]]:
        """Yield retained updates, followed by live updates."""

    async def prompt(
        self,
        agent_id: str,
        prompt: str,
    ) -> str | None:
        …

    async def interrupt(self, agent_id: str) -> None:
        …

class ExternalACPConnection(Protocol):
    async def session_update(
        self,
        *,
        session_id: str,
        update: SessionUpdate,
    ) -> None:
        …

@dataclass(slots=True)
class SwarmACPMux:
    daemon: RuntimeDaemon
    agent_client: SwarmAgentClient
    external_connection: ExternalACPConnection
    external_session_id: str

    attached_agent_id: str | None = None
    _forwarding_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _closed: bool = field(
        default=False,
        init=False,
        repr=False,
    )

    async def attach(self, agent_id: str) -> None:
        self._ensure_open()
        self._require_known_agent(agent_id)

        if (
            self.attached_agent_id == agent_id
            and self._forwarding_task is not None
            and not self._forwarding_task.done()
        ):
            return

        await self.detach()

        self.attached_agent_id = agent_id
        self._forwarding_task = asyncio.create_task(
            self._forward_session_updates(agent_id),
            name=f"swarm-acp-mux:{agent_id}”,
        )

    async def detach(self) -> None:
        task = self._forwarding_task

        self._forwarding_task = None
        self.attached_agent_id = None

        if task is None:
            return

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def prompt(self, text: str) -> str | None:
        self._ensure_open()
        return await self.agent_client.prompt(
            self._require_attached_agent(),
            text,
        )

    async def interrupt(self) -> None:
        self._ensure_open()
        await self.agent_client.interrupt(
            self._require_attached_agent()
        )

    def get_swarm_status(self) -> dict[str, object]:
        self._ensure_open()

        return {
            “attached_agent_id”: self.attached_agent_id,
            “swarm”: self.daemon.get_swarm_status(),
        }

    def get_agent_detail(
        self,
        agent_id: str,
        *,
        max_events: int = 100,
    ) -> dict[str, object]:
        self._ensure_open()
        self._require_known_agent(agent_id)

        return {
            “attached”: agent_id == self.attached_agent_id,
            “agent”: self.daemon.get_agent_detail(
                agent_id=agent_id,
                max_events=max_events,
            ),
        }

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        await self.detach()

    async def _forward_session_updates(self, agent_id: str) -> None:
        current_task = asyncio.current_task()

        try:
            async with self.agent_client.subscribe_acp_updates(
                agent_id
            ) as updates:
                async for received in updates:
                    await self._forward_external_update(received)
        finally:
            if (
                self.attached_agent_id == agent_id
                and self._forwarding_task is current_task
            ):
                self.attached_agent_id = None
                self._forwarding_task = None

    async def _forward_external_update(
        self,
        received: ReceivedSessionUpdate,
    ) -> None:
        await self.external_connection.session_update(
            session_id=self.external_session_id,
            update=received.update,
        )

    def _require_attached_agent(self) -> str:
        if self.attached_agent_id is None:
            raise NoAttachedAgentError(
                “No agent is attached to this ACP connection"
            )

        return self.attached_agent_id

    def _require_known_agent(self, agent_id: str) -> AgentState:
        try:
            return self.daemon.swarm_state.agents[agent_id]
        except KeyError as exc:
            raise UnknownAgentError(agent_id) from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise SwarmACPMuxClosedError()

    async def __aenter__(self) -> “SwarmACPMux”:
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        await self.close()
```

------------------------------------------------------------------------

## Tests

Tests should focus on complete routing and lifecycle behavior.

### Attachment and replay

- attaching subscribes to the selected agent;
- retained events are forwarded before later live events;
- an event published during attachment is delivered exactly once;
- switching attachment cancels the old subscription and replays the new agent's retained stream;
- the attachment acknowledgment identifies the new agent.

### Agent request forwarding

- `prompt()` delegates to the attached agent;
- `interrupt()` delegates to the attached agent;
- either operation without an attachment raises `NoAttachedAgentError`.

### External control routing

Test the swarm ACP server adapter together with the mux:

- `_attach` calls `mux.attach(agent_id)`;
- `_detach` calls `mux.detach()`;
- `_swarm_status` returns `mux.get_swarm_status()`;
- `_agent_detail` returns `mux.get_agent_detail(agent_id)`;
- an unknown underscore-prefixed update returns a structured error;
- reserved control updates are not proxied to `NateOhaAcpClient`.

### Multiple subscribers

Using the real event-stream implementation:

- the mux and an independent subscriber receive the same agent event;
- each receives retained history followed by live events;
- detaching the mux leaves the independent subscription active.

### Lifecycle

- `close()` is idempotent;
- detach removes only the mux subscription;
- normal agent-stream closure leaves the mux open and unattached;
- external write failure terminates the forwarding task;
- operations after close raise `SwarmACPMuxClosedError`.

### Macro integration test

Add one real-path async integration test that:

1. starts a real agent;
2. creates an external swarm ACP session and `SwarmACPMux`;
3. sends external `_attach`;
4. verifies that the mux attaches and the control update is not sent to the agent;
5. confirms that retained ACP session updates for the attached agent are replayed in order;
6. sends an ordinary prompt;
7. verifies that agent output reaches the external ACP connection;
8. confirms that an independent subscriber also receives the agent output;
9. sends external `_detach`;
10. verifies that the mux becomes unattached while the agent remains running.

------------------------------------------------------------------------

## Summary

`SwarmACPMux` is a small connection-scoped router with two clear paths:

```
# External client -> swarm or attached agent
if update.session_update.startswith(“_”):
    await dispatch_reserved_update(mux, update)
else:
    await proxy_ordinary_request(mux, update)

# Attached agent -> external client
async with agent_client.subscribe_acp_updates(agent_id) as updates:
    async for received in updates:
        await mux._forward_external_update(received)
```

The runtime supplies replay-capable per-agent subscriptions. The outer ACP server supplies reserved-update decoding. The mux owns only attachment and routing.

This yields one typed ACP update stream, one agent client, one mux implementation, and one authoritative place for each responsibility.
