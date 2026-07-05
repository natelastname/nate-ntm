I think this is in very good shape. It now has a clear architectural story, and it's much less likely that the implementer will accidentally preserve the old `OpenHandsAcpClient`.

I have a few remaining suggestions.

### 1. Make the ownership boundary explicit in the requirements

Right now it's only in the entity description. I'd promote it to a functional requirement because it's a key architectural constraint.

For example:

> **FR-012:** The runtime MUST interact with managed `nate_OHA` instances exclusively through `NateOhaAcpClient`. `NateOhaAcpClient` owns the complete lifecycle of each managed subprocess, including creation, supervision, and termination.

That makes it impossible for someone to later justify “just call nate_OHA directly from RuntimeDaemon.”

------------------------------------------------------------------------

### 2. Make the launch contract more concrete

FR-011 currently says:

> define and document the process launch contract

I would strengthen it slightly:

> **FR-011:** The adapter MUST define and document the complete process launch contract for `nate_OHA`, including:
>
> - executable name
>
> - command-line arguments
>
> - required environment variables
>
> - working directory
>
> - startup readiness detection
>
> - shutdown procedure
>
> - timeout behavior
>
> - restart behavior

Those last three are important because they're exactly the kinds of things that drift over time if they aren't specified.

------------------------------------------------------------------------

### 3. Tie FR-004 to NATE_OHA_GUIDE.md

Right now it says

> using its supported command-line options and environment variables

Since you've already written the guide, I'd make it normative.

For example:

> …using the supported command-line interface and environment variables defined in `NATE_OHA_GUIDE.md`…

That gives one canonical document instead of two evolving separately.

------------------------------------------------------------------------

### 4. Add a requirement for version compatibility

This is the only thing I think is genuinely missing.

You're now coupling two independently-developed repositories.

I'd add something like

> **FR-013:** `NateOhaAcpClient` MUST verify that the installed `nate_OHA` executable satisfies the minimum supported interface version before attempting to launch managed agents, and MUST fail with a clear diagnostic if the version is incompatible.

Otherwise six months from now you'll eventually change `nate_OHA`'s CLI and spend an afternoon wondering why `nate_ntm` mysteriously stopped working.

------------------------------------------------------------------------

### 5. Rename “Retired Experimental Adapter"

I'd actually remove it from the entities section.

Entities should describe concepts that exist in the finished architecture.

`OpenHandsAcpClient` is no longer part of the architecture.

Instead I'd simply mention its removal in FR-008.

I'd keep only:

- BaseAcpClient
- FakeAcpClient
- NateOhaAcpClient
- nate_OHA Instance
- Agent Mail Identity
- Swarm Runtime
- Runtime Event Pipeline

That keeps the conceptual model cleaner.

------------------------------------------------------------------------

## The biggest thing I like

The specification now makes the layering very clear:

``` overflow-visible!
RuntimeDaemon
        │
        ▼
 BaseAcpClient
        │
        ▼
 NateOhaAcpClient
        │
 launches/supervises
        ▼
    nate_OHA process
        │
        ▼
   OpenHands SDK
```

That separation wasn't obvious in the earlier drafts, but now it's the central architectural idea.

I think this is a strong spec to implement from. The only substantive addition I'd make is the version/interface compatibility requirement (FR-013); the other suggestions are refinements rather than missing functionality.
