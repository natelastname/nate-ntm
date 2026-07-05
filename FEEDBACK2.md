I actually disagree with OpenHands' agreement on point \#1, for the reason you gave earlier.

The purpose of a spec is not only to hide implementation details — it is also to capture **architecturally significant dependencies**. In this case, **OpenHands is architecturally significant because it provides durable conversation state and resume semantics**. That isn't an incidental implementation detail.

I'd phrase it like this:

- The **production adapter** is `NateOhaAcpClient`.
- The **managed process** is `nate_OHA`.
- `nate_OHA` is built on **OpenHands**, and therefore the adapter is responsible for preserving the OpenHands conversation across restarts.

That's an important invariant.

I'd even strengthen FR-005 to say something like:

> The adapter MUST relaunch each `nate_OHA` instance using the same persisted OpenHands conversation identifier so that the underlying OpenHands session resumes rather than creating a new conversation.

That's much stronger than saying “conversation continuity” in the abstract.

------------------------------------------------------------------------

The other six comments I think are spot-on.

In particular, I think \#7 (ownership boundary) is the biggest improvement. One sentence like:

> `NateOhaAcpClient` owns the complete lifecycle of the managed `nate_OHA` subprocess. The runtime interacts with `nate_OHA` exclusively through this adapter.

eliminates a huge amount of ambiguity.

I'd rank the improvements:

1. **\#7 Ownership boundary** ⭐⭐⭐⭐⭐ (most important)
2. **\#6 Process launch contract** ⭐⭐⭐⭐⭐
3. **\#2 Supervise, not just start** ⭐⭐⭐⭐
4. **\#4 Canonical event source** ⭐⭐⭐⭐
5. **\#5 Move operational metadata to the runtime** ⭐⭐⭐
6. **\#3 Explicit CLI/environment contract** ⭐⭐⭐
7. **\#1 OpenHands terminology** — **keep it**, but be precise about *why* it's there.

So my only substantive disagreement with OpenHands' assessment is that I would **not** scrub OpenHands from the spec. Instead, I'd make the dependency explicit:

> `NateOhaAcpClient` manages `nate_OHA` processes, which in turn use OpenHands as their execution engine. The adapter is responsible for preserving the underlying OpenHands conversation identifiers required for resume semantics.

That tells future readers *why* OpenHands appears in the specification, instead of making it look like an accidental leakage of implementation details.
