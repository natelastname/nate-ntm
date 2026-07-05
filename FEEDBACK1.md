## 1. Remove the OpenHands terminology

I would avoid saying things like:

> “underlying OpenHands conversations"

or

> “OpenHands conversation linkage"

The runtime should not care whether `nate_OHA` is implemented on top of OpenHands today or something else in the future.

Instead I'd consistently use something like:

> ACP conversation

or

> agent execution session

That keeps the abstraction clean.

------------------------------------------------------------------------

## 2. FR-002 should say supervise, not just start

Current:

> start a dedicated nate_OHA ACP process

I'd strengthen it to something like:

> launch, supervise, and terminate a dedicated `nate_OHA` ACP process for each managed agent.

The process lifecycle is really the heart of this adapter.

------------------------------------------------------------------------

## 3. FR-004 should mention command line and environment

You now know exactly how `nate_OHA` works.

Instead of saying:

> pass runtime context into nate_OHA

I'd make it explicit:

> The adapter configures each `nate_OHA` instance using its supported command-line options and environment variables (including the Agent Mail configuration described in `NATE_OHA_GUIDE.md`).

That gives future implementers a much more concrete direction.

------------------------------------------------------------------------

## 4. FR-007 is probably too vague

It currently says

> expose agent events produced by nate_OHA

The important architectural question is:

**How?**

I would expect the spec to answer whether:

- the ACP stream is authoritative,
- stdout/stderr are parsed,
- the adapter subscribes to ACP events,
- etc.

Even if it doesn't pick one, it should define that there is **one canonical event source**.

------------------------------------------------------------------------

## 5. FR-009 doesn't belong in the adapter

This one sticks out:

> process status, restart time, failures

That's runtime supervisor metadata.

I'd move it into the runtime itself.

The adapter shouldn't know anything about restart history.

Instead:

> The runtime shall expose operational metadata for NateOhaAcpClient-managed agents.

------------------------------------------------------------------------

## 6. Missing: process launch contract

This is the one thing I think the spec is missing.

I would expect an explicit requirement like:

> The adapter shall define the command line, environment variables, working directory, and startup validation used to launch a `nate_OHA` instance.

Otherwise every implementation ends up inventing this.

------------------------------------------------------------------------

## 7. Biggest missing piece: ownership boundary

Right now the spec implies:

``` overflow-visible!
Runtime
    ↓
NateOhaAcpClient
    ↓
nate_OHA
```

But nowhere does it explicitly say:

> NateOhaAcpClient owns the lifetime of the subprocess.

I'd make that explicit.

Otherwise people will wonder whether systemd, tmux, Docker, Kubernetes, etc. own the process.

I think the spec should say:

> NateOhaAcpClient is responsible for creating, supervising, and terminating the `nate_OHA` process. The runtime interacts with `nate_OHA` exclusively through this adapter.

That single sentence clarifies the entire architecture.
