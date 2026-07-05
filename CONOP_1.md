Create a new feature specification for a production `NateOhaAcpClient` that becomes the runtime's production ACP adapter.

The goal of this feature is to integrate `nate_ntm` with `nate_OHA` as the managed coding-agent runtime. The new adapter should replace the current `OpenHandsAcpClient` as the production ACP implementation while preserving the existing runtime architecture and fake adapters used for development and testing.

Relevant reference material:

- `NATE_OHA_GUIDE.md` in this repository documents how `nate_OHA` integrates with Agent Mail.
- The `nate_OHA` executable is available on the system PATH.
- The `nate_OHA` source tree is available locally at `~/Projects/nate_OHA/` for reference if additional implementation details are needed.

The specification should describe a production adapter that is responsible for launching, supervising, and communicating with `nate_OHA` instances on behalf of the swarm runtime.

The feature should cover:

- Starting a `nate_OHA` ACP instance for each managed agent.
- Configuring `nate_OHA` with the Agent Mail integration described in `NATE_OHA_GUIDE.md`.
- Passing each agent's persisted Agent Mail identity, credentials, and other required runtime context into `nate_OHA`.
- Preserving agent identity and conversation continuity across runtime shutdown and resume.
- Managing the lifecycle of the underlying `nate_OHA` process, including startup, shutdown, restart, and failure handling.
- Receiving agent events from `nate_OHA` and integrating them into the existing runtime event pipeline so they appear through `AgentEventStream`, `agent.get_detail`, and the runtime event subscription APIs.
- Defining how this adapter fits into the existing adapter abstraction and runtime architecture introduced in Phase 6.

The specification should identify any additional capabilities that `nate_OHA` needs to expose in order to support this integration cleanly, and should clearly describe the responsibilities and interface of the new production adapter from the perspective of the `nate_ntm` runtime.
