# QUICKSTART: Running `nate_OHA` with Agent Mail (`mcp_agent_mail`)

This guide explains how to run the Nate OpenHands agent (`nate_OHA`) with the
optional Agent Mail integration, backed by an existing `mcp_agent_mail`
server.

The integration is intentionally **opt-in** and designed so that:

- When Agent Mail is **disabled**, `nate_OHA` behaves as it always has.
- When Agent Mail is **enabled**, a small, safe set of `agent_mail_*` tools
  becomes available to the coding agent, backed by your `mcp_agent_mail`
  instance.

There are two main ways to use this integration:

1. **Launcher-integrated mode** – `nate_OHA` exposes `agent_mail_*` tools
directly inside an OpenHands coding session.
2. **Standalone MCP facade** – a separate `nate_oha_agent_mail_mcp` CLI runs
   only the Agent Mail FastMCP facade over stdio, for use by other MCP clients.

Both modes use the same configuration, identity binding, and FastMCP
implementation.

---

## 1. Prerequisites

Before enabling Agent Mail, you need:

- A working Python environment (this repo uses `uv`).
- `nate_OHA` installed from this repository (editable install via `uv`
  happens automatically when you run tests or commands from the repo root).
- Access to a running `mcp_agent_mail` server with:
  - A project key (logical project identifier).
  - An agent identity name.
  - A token for that agent.
  - An HTTP(S) endpoint for the MCP server (used with Streamable HTTP).

The Agent Mail integration is configured via these environment variables:

- `AGENT_MAIL_PROJECT` – your Agent Mail project identifier.
- `AGENT_MAIL_AGENT` – the public agent name for this Nate/OpenHands agent.
- `AGENT_MAIL_TOKEN` – the token or secret associated with this agent.
- `AGENT_MAIL_UPSTREAM_URL` – the HTTP(S) URL for your `mcp_agent_mail`
  MCP endpoint (for example, `https://mail.example.com/mcp`).

> **Security note**
> 
> `AGENT_MAIL_TOKEN` and upstream details are secrets. The integration is
> designed so these values are **never** exposed to the model via tool
> arguments, tool docs, or prompt text. They should also not be printed in
> logs or error messages.

---

## 2. Launcher-integrated mode (inside `nate_OHA`)

In this mode, the OpenHands agent started by `nate_OHA` has direct access to
curated `agent_mail_*` tools during a coding session.

### 2.1 Disable Agent Mail (baseline)

To confirm that enabling this feature doesn\'t change baseline behavior when
it is turned off:

```bash
cd /path/to/this/repo

# Ensure Agent Mail variables are unset
unset AGENT_MAIL_PROJECT AGENT_MAIL_AGENT AGENT_MAIL_TOKEN AGENT_MAIL_UPSTREAM_URL || true

# Start nate_OHA without Agent Mail enabled
uv run nate_OHA acp
```

**Expected behavior**:

- The ACP server starts normally.
- No tools with the `agent_mail_` prefix are registered.
- No Agent Mail-specific annex appears in the system prompt.

### 2.2 Enable Agent Mail

To enable Agent Mail, set the required environment variables and pass the
`--enable-agent-mail` flag to the `acp` subcommand.

1. Export environment variables for your `mcp_agent_mail` instance (replace
   with real values):

   ```bash
   export AGENT_MAIL_PROJECT="your-project-id"
   export AGENT_MAIL_AGENT="your-public-agent-name"
   export AGENT_MAIL_TOKEN="your-secret-token"
   export AGENT_MAIL_UPSTREAM_URL="https://your-mcp-agent-mail.example.com/mcp"
   ```

2. Start `nate_OHA` with Agent Mail enabled:

   ```bash
   uv run nate_OHA acp --enable-agent-mail
   ```

   You may also pass other options, e.g.:

   ```bash
   uv run nate_OHA acp \
     --enable-agent-mail \
     --confirmation-mode llm-approve \
     --streaming
   ```

**What happens on startup**:

- The launcher loads `AgentMailConfig` from `AGENT_MAIL_*` env vars.
- It validates that all required variables are present and non-empty.
- It performs a minimal connectivity check to `AGENT_MAIL_UPSTREAM_URL`.
- If configuration and connectivity are valid, it wires an Agent Mail
  FastMCP facade into the OpenHands MCP configuration.

**Expected behavior in the coding session**:

- The system prompt includes an Agent Mail annex that:
  - Explains the available `agent_mail_*` tools.
  - Clarifies that the agent is bound to a single identity.
  - States that identity and token are not exposed as tool parameters.
- The tool list includes only the curated Agent Mail tools, for example:
  - `agent_mail_fetch_inbox`
  - `agent_mail_send_message`
  - `agent_mail_reply_message`
  - `agent_mail_acknowledge_message`
  - `agent_mail_mark_message_read`
  - `agent_mail_search_messages`
  - `agent_mail_summarize_thread`
  - `agent_mail_reserve_files`
  - `agent_mail_release_file_reservations`
  - `agent_mail_renew_file_reservations`
- No raw `mcp_agent_mail` tool names or admin/destructive actions are visible.

### 2.3 Failure modes (misconfiguration or unreachable upstream)

If configuration is incomplete or the upstream is unreachable, startup fails
**before** any OpenHands conversation is created.

Examples:

- Missing variables:
  - If, for example, `AGENT_MAIL_TOKEN` is unset, startup fails with a clear
    error naming the missing variable(s) (but never their values).
- Unreachable upstream:
  - If `AGENT_MAIL_UPSTREAM_URL` is syntactically valid but unreachable,
    startup fails early with a message such as:
    `Could not connect to Agent Mail upstream at 'https://…'`.
  - The agent does **not** silently disable Agent Mail or continue in a
    degraded mode.

---

## 3. Standalone Agent Mail MCP facade

In some scenarios you may want to run only the Agent Mail facade as a standalone
MCP server (for testing, or for use by another MCP-capable agent). For this,
use the `nate_oha_agent_mail_mcp` CLI.

### 3.1 Configure environment

Set the same `AGENT_MAIL_*` variables you would use with the launcher:

```bash
export AGENT_MAIL_PROJECT="your-project-id"
export AGENT_MAIL_AGENT="your-public-agent-name"
export AGENT_MAIL_TOKEN="your-secret-token"
export AGENT_MAIL_UPSTREAM_URL="https://your-mcp-agent-mail.example.com/mcp"
```

### 3.2 Start the standalone facade

From the project root (or any environment where `nate_oha_agent_mail_mcp` is
installed):

```bash
uv run nate_oha_agent_mail_mcp
```

This starts a FastMCP server over stdio that exposes the same curated
`agent_mail_*` tools as the launcher-integrated path, with identical
configuration and identity binding rules.

Under the hood, `nate_oha_agent_mail_mcp` delegates to the same
`nate_oha.agent_mail_facade.main()` entrypoint used by the launcher.

### 3.3 Connecting another MCP client

If you have another MCP-capable client that uses an `mcpServers` configuration
(e.g. `mcp_config.json`), you can point it at the standalone facade. A minimal
config might look like:

```jsonc
{
  "mcpServers": {
    "agent-mail": {
      "transport": "stdio",
      "command": "nate_oha_agent_mail_mcp",
      "args": [],
      "env": {
        "AGENT_MAIL_PROJECT": "your-project-id",
        "AGENT_MAIL_AGENT": "your-public-agent-name",
        "AGENT_MAIL_TOKEN": "your-secret-token",
        "AGENT_MAIL_UPSTREAM_URL": "https://your-mcp-agent-mail.example.com/mcp"
      }
    }
  }
}
```

If you prefer to run via `uv` explicitly, you can use:

```jsonc
{
  "mcpServers": {
    "agent-mail": {
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "nate_oha_agent_mail_mcp"],
      "env": { /* AGENT_MAIL_* as above */ }
    }
  }
}
```

Once configured, your MCP client should see the same `agent_mail_*` tools and
semantics described in Section 2.

---

## 4. Verifying behavior end-to-end

To quickly verify that everything is wired correctly:

1. **Launcher-integrated path**:
   - Start `uv run nate_OHA acp --enable-agent-mail` with valid env.
   - Inspect tools and confirm only `agent_mail_*` are present.
   - Use `agent_mail_fetch_inbox` / `agent_mail_reply_message` /
     `agent_mail_acknowledge_message` against your test `mcp_agent_mail`.

2. **Standalone facade**:
   - Start `uv run nate_oha_agent_mail_mcp` with the same env.
   - Connect with another MCP client using the `mcpServers` snippet above.
   - Run the same basic inbox/reply/acknowledge flow.

In both cases, you should see:

- Successful end-to-end calls against your `mcp_agent_mail` server.
- No exposure of `AGENT_MAIL_TOKEN` or other secrets in tool signatures,
  prompt text, or error messages.
- A consistent, single identity (project + agent name) bound for the entire
  process lifetime.
