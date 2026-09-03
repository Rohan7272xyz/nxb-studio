# nxb-006: H1 built, and what building it broke

Task: nxb-006. Author: Worker 3. Date: 2026-08-28.
Scope built: H1 only. H2, H3, H4, the canary, provenance and the permission
boundary were not built, per instruction. Nothing outside this repo was
modified. Tags as before: **[M]** measured, **[A]** assumption, **[H]** hole.

## What runs

```
nxb/          contract.py  dispatch.py  ledger.py  receipt.py  runtimes.py  __main__.py
contract/     contract.json                    the published contract, as DATA
contract/runtimes/claude_code.json             nxb-001's measurements, as DATA
tests/        34 tests, all passing, 0.024s
```

The dispatch is a call. `python -m nxb dispatch <envelope> --ledger <db>
--registry <decls>` returns one of three shapes on stdout and exits 0 for
OBSERVED, **3** for REFUSED, **4** for UNKNOWN. Not 1, deliberately: at a
process boundary a naive `|| echo failed` would otherwise merge REFUSED with
UNKNOWN, which F-24 forbids. **The spec's F-24 is unimplementable across a
process boundary without an exit-code convention, and the spec does not have
one.** First thing building added.

## 1. The R-050 experiment, which sharpened the rule rather than confirming it

You asked for the experiment I proposed: emit into a transport **with** a return
value while nobody watches, and see whether the return value alone accounts for
the difference. Here is what I could measure and what I could not.

### 1.1 What was measured [M]

Two sends from this session, 2026-08-28.

**Unresolvable address.** `SendMessage` to a name that does not exist:

```
{"success":false,"message":"No agent named '...' is reachable."}
```

Truthful. The return value carries the failure.

**Resolvable but offline.** `ListAgents` displays five Remote Control peers as
`offline`. `SendMessage` to one of them:

```
{"success":true,"message":"... → WAVE 2 (a Claude session on another machine,
 over Remote Control)","msg_id":"9e37db2a-..."}
```

**`success: true`, with a message id, to a peer the same tool surface has just
finished telling me is offline.**

### 1.2 What that means for R-050

**R-050 as written is insufficient, and the fix is one turn of the screw
tighter, not a reversal.**

The call-versus-emit diagnosis is *right*: a call has somewhere to put the
truth and an emission does not. But having somewhere to put it is not the same
as putting it there. The `SendMessage` return value is a **transmission ack**:
it reports that an address resolved and a write was accepted. It is silent
about whether anything observed the message.

**Amended R-050: a dispatch must be a call that returns THE RECEIPT. A call
that returns an acknowledgement of transmission is an emission with extra
steps.** That is now the property the H1 code satisfies by construction, and
there is a test named for it.

This also explains the 0-for-7 more precisely than either of us had. Had the
2026-08-27 directives been emitted into a channel with a *transmission* ack,
the orchestrator would have received seven `success:true` responses and
proceeded exactly as it did. **The return value would not have caught it.** What
would have caught it is a return value correlated with observation, which is
what nxb-001 measured living on `peer_message_status`, on the sender's own
socket, and not in the return value at all.

### 1.3 The honest limits of this experiment

- **[A]** I cannot distinguish "false success" from "accepted for later
  delivery". Remote Control may queue. Either reading leaves the dispatcher
  knowing nothing about observation, and "accepted for delivery" is precisely
  the semantics that produced 0-for-7, so the conclusion holds under both. But
  it is not a clean disproof of the offline case being *honestly* reported.
- **The attention half is untested and I cannot test it.** I am the dispatcher.
  I cannot un-attend. Isolating attention needs a dispatcher that is not the
  experimenter: two runs of the same agent on the same task, one where the
  dispatch returns a truthful failure and one where it returns nothing, with
  nobody reading either transcript until both finish. That is a real experiment
  and it is nxb-00N, not this task.
- So R-050 remains **[A]**, better supported than before and still not proven.

## 2. The finding that inverted my own reasoning

Before running the experiment I had a conclusion ready, and it was wrong in an
instructive way. I was going to report that **the inbox is an H2 component and
H1 does not need it**, on the grounds that if the broker is something the
dispatcher calls, the return value *is* the receipt and no socket is involved.

The experiment says that reasoning is sound only for one of two architectures,
and the second is the one you were pointing at.

| | **(a) broker as library** | **(b) broker as peer** |
|---|---|---|
| dispatch is | an in-process call | a message across the peer mesh |
| the return value is | the receipt itself | a transmission ack [M] |
| truthful about observation | **by construction** | **no** |
| needs an inbox | **no** | **yes, mandatory** |
| F-25 (dispatcher can block) | satisfied trivially | must be established |

**I built (a).** It satisfies amended R-050 by construction and it is the
narrowest thing that can fail instructively, which is what you asked for.

**Your instinct about the inbox was right and my objection was right, about
different architectures.** The inbox is not a precondition for *a* receipt; it
is a precondition for a receipt **on any transport where the return value is
not the receipt**, which is every cross-process transport measured so far. That
is a sharper statement than either of us had and it belongs in the handoff.

## 3. Refusals that survived contact

Implemented and tested. 34 tests.

| refusal | survived | evidence |
|---|---|---|
| **F-1** null `start_signal` refuses registration | **yes, and it caught the real defect** | `contract/runtimes/claude_code.json` carries nxb-001's two declarations differing in one field; the broker refuses the one without an inbox |
| **F-2** omitted field refuses registration | yes | explicit null accepted, omission refused |
| **F-6** no interpretation before a receipt exists | **yes, structurally** | `_interpret` needs a token only `_observe` mints, and re-checks it against the ledger, so a forged token still cannot unlock interpretation |
| **F-7** receipt carries no verdict | yes | forbidden-field list is data in the contract; every entry tested |
| **F-8** digest divergence refuses | yes, with a caveat, see 4.3 | |
| **F-9** count divergence refuses, including zero | yes | a rejected dispatch still gets a receipt, which is the flagship |
| **F-10** dedup on `receipt_id` | yes | `receipts.receipt_id` is the primary key |
| **F-11** exactly one disposition per receipt | yes | UNIQUE constraint; a second insert raises |
| **R-051** repeated key returns the original receipt | yes, with a problem, see 4.4 | |
| three return shapes, REFUSED ≠ UNKNOWN | yes | `dispatch_status: DID_NOT_HAPPEN` only on REFUSED |
| `dispatch` never raises | yes | tested against `None`, `{}`, `[]`, partial dicts |

**F-1 is the one to keep.** Run A of the demo is the whole project in six lines:
the broker read the real measured declaration for Claude Code, saw a null
`start_signal`, and refused to register the runtime. That is nxb-003's defect
being caught on the real runtime by the rule written to catch it, before any
work was dispatched.

## 4. Refusals that did NOT survive, or had to be weakened

You said to treat these as the most valuable result. There are four, and the
first one is yours.

### 4.1 F-5 is intolerable as written, and it failed in the first hour

**F-5 refuses to dispatch to a runtime whose liveness is UNKNOWN. The canary is
out of H1 scope. Therefore every runtime is UNKNOWN forever and F-5 refuses
100 percent of dispatches.** Demo run A shows it. To get a single dispatch
through I had to hand-write `last_proven_at` into the registry, which is the
operator reaching past the safety rail on day one.

**This is my muting objection, arriving on schedule, one hour in rather than
one week in.** The predicted end state was an operator widening a budget until
the refusal stops biting. The observed end state was an operator forging a
proof, which is worse.

Weakening required, and I do not have the number for it:

- F-5 must distinguish **never proven** from **proven and stale** [my draft-2
  partial fix, now confirmed necessary by contact].
- It probably must let a **first dispatch serve as its own proof**, rather than
  requiring a prior one. That is a real design change: it means the first
  dispatch to a cold runtime is speculative and its receipt doubles as the
  liveness assertion.
- **[H]** The number that decides this is how often a runtime goes stale while
  idle, and nobody has it. It cannot be got from H1 alone.

### 4.2 R-041 assertion 2 is unnecessary as specified

The spec demanded a test that every field the validator requires appears in the
published contract. **I generated the validator from the contract instead, so
schema drift is impossible rather than detectable, and assertion 2 is vacuously
true.**

**Generation beats testing.** The spec should say so: generate the validator
from the published contract wherever the contract is expressible as data, and
test only what cannot be generated.

What cannot be generated is the **invariant list**: rules a schema cannot
express, like "no interpretation before a receipt" or "dedup keys on
receipt_id". I repointed assertion 2 at those, and the test now asserts that
every claimed invariant names code that enforces it, that the named module
actually imports, and that any invariant enforced by **nothing** says so out
loud. One invariant does: `provenance_is_asserted`, whose `enforced_by` reads
`NOTHING. Declared open.` That is nxb-001's unauthenticated-peer finding
recorded where a consumer cannot mistake it for a solved problem.

### 4.3 F-8 has a hidden dependency the spec did not notice

A digest comparison requires the sender and the receiver to agree on a
**canonicalisation**. I had to export `nxb.receipt.digest_units` so the
dispatcher hashes exactly what the broker will hash.

**That shared function is itself an undocumented contract, and if it drifts,
F-8 fires on every dispatch for reasons that have nothing to do with
truncation.** Another always-fires alarm, which is the failure mode we spent
draft 2 designing out of the identity check. The canonicalisation must be part
of the published contract, versioned with it. It currently is not.

### 4.4 R-051 as specified creates a new vanish point

The spec says a repeated `dispatch_key` returns the original receipt. It does
not say what to do when the repeated key arrives with a **different payload**.

I built the literal behaviour and wrote a test that documents it:
`test_a_changed_payload_under_a_repeated_key_returns_the_original`. It passes,
and **I think the specified behaviour is wrong.** A dispatcher that reuses a key
by accident receives a stale receipt for someone else's payload and a
`state: OBSERVED` that is true about the wrong thing. That is a silent loss of
the new work, which is a vanish point the spec created while closing others.

Recommended change: a repeated key whose payload digest differs from the
original MUST refuse with a new reason, `dispatch_key_reuse_divergence`. I did
not make the change unilaterally because it is a contract change and the
contract is now published.

### 4.5 Not built, for want of a number

**F-12** (no record non-terminal past its budget) needs a budget. There is no
measured one. The ledger exposes `undisposed()` so the condition is visible;
nothing acts on it.

## 5. New vanish points, found by building

Added to the fifteen in `ADAPTER-AUTOPSY.md`.

| # | vanish point | status |
|---|---|---|
| 16 | **Stale session identity.** [M: nxb-001] `/clear` rotates `sessionId` while ref, pid, socket and name stay intact, and a send carrying a cached `sessionId` is dropped **silently** with `session_id mismatch`. A broker that caches identity at dispatch time goes 0-for-N against every worker cleared since. Rohan clears panes by hand, so this is live | **OPEN.** Mitigation is a rule, not a mechanism: re-resolve immediately before every send. A changed ref means the process restarted |
| 17 | **Unauthenticated sender.** [M: nxb-001] Anything local that can write to the peer socket is received as a trusted peer. Provenance is asserted, never authenticated | **OPEN.** Recorded in the contract as an invariant `enforced_by: NOTHING. Declared open.` |
| 18 | **`dispatch_key` reuse with a divergent payload** returns a stale receipt and a true-but-misleading OBSERVED | **OPEN, created by R-051.** Fix proposed in 4.4 |
| 19 | **Canonicalisation drift** turns F-8 into a false-positive generator | **OPEN.** Fix is to publish the canonicalisation with the contract |

## 6. Two things from the nxb-001 feed that were about to be lost

You closed specification before the nxb-001 feed reached the spec, so its
measured facts existed only in a chat message. `HANDOFF.md` says a durable fact
goes in a file in the same turn it is learned. **This is the project's own
failure mode recurring on the project itself**, and it is worth naming.

I captured the capability facts in `contract/runtimes/claude_code.json` as data,
including the `MEASURED_ABSENT` versus `UNMEASURED` distinction you flagged,
with a test asserting the two are not collapsed. Two more need the ledger:

**6.1 `peer_idle_notice` is liveness, not completion.** It fired at 10.8s on a
task still running a 25-second backgrounded command [M: nxb-001]. This is
`HANDOFF.md` rule 8 exactly: a harness that silently does nothing reports a
clean pass. It is recorded in the declaration as
`progress_signal: "peer_idle_notice — LIVENESS ONLY"`, and the spec needs a
refusal: **the broker MUST REFUSE to treat a liveness signal as a completion
signal.** That refusal does not currently exist in draft 2.

**6.2 The two runtime probes disagree about MCP, and both are right.** nxb-001
measured `claude mcp serve` advertising tools only, no sampling, with
`prompts/list` and `resources/list` returning -32601: **an MCP client cannot ask
Claude Code to think.** nxb-002 measured `codex mcp-server` exposing `codex` and
`codex-reply`, both returning `{threadId, content}` synchronously, and concluded
MCP is "a genuine common substrate, the strongest cross-runtime candidate found
here."

Both are correct about their own runtime. **MCP is an agent layer for Codex and
a tool layer for Claude Code.** The ledger currently carries nxb-002's
conclusion unqualified and it needs the qualification, because it decides
adapter shape: for Codex, content returns over MCP or app-server; for Claude
Code there is **no content reply channel at all**, so a broker must own the
worker's stdout or read its transcript. That converges with your fourth point
and it is a Phase 2 constraint that is already decided by measurement rather
than open for design.

## 7. What I did not need

Per instruction I stopped rather than reaching for the next hop, and I did not
need to reach. H1 required no H2, no H3, no H4, no canary, no provenance and no
second runtime. The one thing I was told to build first and did not need is the
inbox, for the architecture reason in section 2, and that is a finding about the
spec rather than a shortcut.

## UNVERIFIED

- R-050 remains **[A]**. Section 1.3 states the two limits.
- The offline-peer result may be "accepted for later delivery" rather than a
  false success. Not distinguishable without observing arrival.
- Every capability fact about Claude Code is nxb-001's measurement relayed
  through the orchestrator. I did not re-measure any of it; I recorded it.
- The H1 code has never been driven by a real dispatcher. The demo envelopes
  were written by me, so the ergonomics of the envelope are untested.
- No number exists for F-5's staleness budget, F-12's budget, or the canary
  interval. Building H1 did not produce them and cannot.
- 34 tests written by the same author as the code they test. See section 8.

## 8. Where I think you may still be framing this wrongly

**1. The build-to-spec ratio is the result, and it should change the order of
the remaining work.** One hour of building produced two new vanish points,
invalidated one spec assertion, exposed a hidden contract dependency, and killed
one refusal outright. Five documents produced zero of those. F-5 in particular
failed in the first hour, not the first week, which should update the priors on
the other refusals: several are probably in the same state and only contact will
say which. **Build H2 before specifying it further, and let the spec follow the
code for the rest of this project rather than leading it.**

**2. I am now both the spec's author and its implementer, which is the least
independent check available.** Every refusal I report as surviving contact is
one I wrote the test for. The project's own thesis is that two instances of the
same model agreeing is weak evidence, and this is a stronger version of that
problem: it is one instance agreeing with itself across two tasks. **The
contract is now data, which makes the fix cheap: have Codex implement H1 against
`contract/contract.json` without seeing `nxb/`, and compare.** Where the two
implementations disagree is where the contract is ambiguous, and that is a real
test of the artifact rather than of me. It is also the first time this project
would actually use the disagreement it was built to produce.

**3. The disagreement test you dispatched in parallel is measuring the wrong
thing if it only measures answers.** Worker 2 collecting both runtimes' answers
and Worker 1 judging blind tests whether the two models *differ*. What the
project needs to know is whether they differ **in ways that catch errors**. Two
models can disagree substantively and both be wrong, or agree and both be right,
and neither outcome tells you the broker is worth building. The sharper test is
to give both runtimes a task with a **known planted defect** and see which finds
it, because that measures catching rather than variance. If the current test
comes back "substantive", I would not treat the thesis as validated without
that second version.
