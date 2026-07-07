I think this is **quite solid** now. I'd call it **9.5/10**. It's at the right level of abstraction and communicates the architecture without prescribing it.

There are only a handful of things I'd still tweak.

------------------------------------------------------------------------

## 1. User Story 2 isn't really about the overview

The title is

> Inspect an individual agent from the overview

But the important capability is **agent inspection**, not where it's launched from.

Since you've intentionally designed for multiple screens, I'd rename it to something like

> **Inspect an individual agent**

or

> **Inspect an agent while monitoring the swarm**

That way the story still holds if, six months from now, inspection becomes its own screen.

------------------------------------------------------------------------

## 2. I'd soften FR-006 slightly

Right now:

> latest known state, last activity time…

I would avoid enumerating fields unless they're actually part of the feature contract.

Maybe simply:

> When an agent is selected, the console MUST display additional information about that agent sufficient to support operator inspection and diagnosis.

That gives future implementations more flexibility.

------------------------------------------------------------------------

## 3. Runtime Session is excellent

I actually really like this now.

> owns the runtime connections
>
> maintains cached state
>
> provides common latest-known view

That's exactly how I'd describe it.

------------------------------------------------------------------------

## 4. FR-010 is much better

This:

> presenting the most recent known state

is exactly the right wording.

Much better than “reconnect automatically” or “display an error.”

------------------------------------------------------------------------

## 5. One requirement I'd still add

You currently have

> collection of reusable screens

I would explicitly require there to be **one shared runtime session**.

Maybe:

> **FR-002:** The console architecture MUST maintain exactly one Runtime Session for each connected runtime. All screens within the console MUST obtain runtime state through that shared session.

That sounds pedantic, but it prevents someone six months from now from writing

``` overflow-visible!
MonitorScreen
    JsonRpcHttpClient()

AgentScreen
    JsonRpcHttpClient()

MailScreen
    JsonRpcHttpClient()
```

which would be disastrous.

------------------------------------------------------------------------

## 6. SC-005

This is the only success criterion I don't love.

> 95%

How do you measure that?

I'd instead write something like

> Events that are successfully received from the runtime event stream are reflected in the console within 2 seconds under normal operating conditions.

Or even simpler,

> Runtime events are reflected in the console with low enough latency that operators can correlate visible state changes with the corresponding events.

The percentage makes it sound precise without actually being measurable.

------------------------------------------------------------------------

## 7. One assumption I'd remove

This:

> Operators are comfortable using keyboard-driven terminal applications

doesn't really matter.

Even if they're not, the software should still exist.

I'd remove that assumption entirely.

------------------------------------------------------------------------

## 8. I really like the opening paragraph

This is particularly good:

> Future features … are expected to be implemented as additional screens…

That's the sentence that communicates the long-term architecture.

Anyone reading the spec immediately understands:

> “We're building a console, not an htop clone.”

------------------------------------------------------------------------

## Overall

I think this is now one of the stronger specs in the repository.

The only substantive architectural thing I'd still add is making the **single shared Runtime Session** an explicit requirement rather than something implied by the Runtime Session entity. Everything else is mostly wording polish.
