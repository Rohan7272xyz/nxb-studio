# nxb-011: F-5 fixed by deleting the reason to forge, and the canary costed

Task: nxb-011. Author: Worker 3. Date: 2026-08-28.
74 tests passing. `contract/contract.json` **not modified** (nxb-009 still under
blind test); the one new refusal reason is an additive extension in
`nxb/contract.py`. No pattern kills. Tags: **[M]** measured, **[A]** assumption,
**[H]** hole.

## 1. Is forging still the easiest path past F-5?

**No, and not because forging got harder. Because forging stopped buying
anything.**

The observed failure in nxb-006 was an operator hand-writing `last_proven_at` to
get past a gate that refused 100 percent of dispatches. The instinct is to make
the proof tamper-evident. That is the wrong lever: it raises the cost of the
dishonest path while leaving the honest path impossible, and an operator with no
honest path will pay any price for the dishonest one.

So the fix has three parts, and only the third is about forgery at all.

**1.1 An unproven runtime is now ALLOWED.** `NEVER_PROVEN` maps to
`ALLOW_SPECULATIVE`. There is nothing to forge, because the state a forger would
be forging his way out of no longer refuses anything.

**1.2 A stale proof re-proves rather than refusing.** `PROVEN_STALE` maps to
`ALLOW_AND_REPROVE`. Stale because idle and stale because broken are different
conditions and only one deserves a refusal. This was my own draft-2 partial fix,
and contact confirmed it was necessary rather than merely nice.

**1.3 A proof is a pointer to an artefact the runtime wrote, re-verified on
every read**, not a timestamp in an editable file. For Codex it points at the
rollout file Codex itself created, and verification re-opens that file and looks
for the thread id. A forged proof is not rejected as a lie; it is simply **not
better than no proof at all**, which is the point.

Measured, end to end:

```
cold gate                : NEVER_PROVEN  -> ALLOW_SPECULATIVE
after a forged proof     : PROOF_INVALID -> ALLOW_SPECULATIVE  + alarm
```

Identical action. **The forger gains zero additional permission**, and the
attempt is not silent: `proof_invalid_discarded` is raised as an alarm, because
allowed is not the same as unnoticed.

### 1.4 The hole I demonstrated on myself while answering this question

The first version of this design still had a payoff for forging, and I found it
by writing the demonstration you asked for rather than by testing:

```
after failed canary : DISPROVEN     -> REFUSE
after FORGED proof  : PROOF_INVALID -> ALLOW_SPECULATIVE     <-- forging worked
```

`ProofStore.put()` cleared any disproof for that runtime, so writing a proof by
hand lifted `DISPROVEN`, **the one state that refuses**. Forging bought exactly
the thing the gate exists to prevent.

Fixed: writing a proof is now inert with respect to a disproof. Only a canary
that completed a full receipt chain, reached a terminal event, and produced a
verifiable artefact calls `clear_disproof`. Re-verified:

```
after failed canary : DISPROVEN -> REFUSE
after FORGED proof  : DISPROVEN -> REFUSE      <-- forging no longer lifts it
after REAL canary   : PROVEN_FRESH -> ALLOW
```

This is the first defect in my own work that my own process caught rather than
an accident, and it only surfaced because you asked the question in the
falsifiable form: not "is the proof tamper-evident" but "is forging still the
easiest path".

## 2. F-5 is substantially weakened, and that is the fix

Named plainly because it is a retreat from a rule the project has been carrying
since nxb-005.

**R-010 said liveness fails closed and UNKNOWN blocks dispatch. That is wrong,
and the corrected rule is asymmetric:**

> **Fail closed on DISPROVEN. Fail OPEN on UNPROVEN. Make proving cheap.**

| state | action | reason |
|---|---|---|
| `NEVER_PROVEN` | ALLOW_SPECULATIVE | nothing to forge; H2 is the real gate |
| `PROVEN_FRESH` | ALLOW | |
| `PROVEN_STALE` | ALLOW_AND_REPROVE | idle is not broken |
| `PROOF_INVALID` | ALLOW_SPECULATIVE **+ alarm** | a bad proof is not evidence of deadness |
| `DISPROVEN` | **REFUSE** | the only refusal, and it requires a canary that actually failed |

**Why this is safe now and was not safe when R-010 was written.** H2 has a real
start signal [M: nxb-010]. A speculative dispatch to a dead runtime fails at H2
in about five seconds **with a receipt**. The 2026-08-27 disaster was not that a
dispatch was allowed; it was that its failure was **silent**. Once the failure is
loud, F-5's pre-check stops being a safety property and becomes a cost
optimisation.

That reframing is the substantive result of this task. **F-5 was designed for a
world with no H2 receipt. H2 now exists, so most of F-5's job is done by
something cheaper and more direct.**

## 3. What the canary costs

Three real canaries, full path, H1 to H2 to drain to verified proof.

| run | wall | to start | input tokens | cached | output | reasoning |
|---|---|---|---|---|---|---|
| 0 (cold) | 4.152s | 0.796s | 15,044 | 9,984 | 6 | 0 |
| 1 | 3.827s | 0.100s | 12,894 | 9,984 | 6 | 0 |
| 2 | 6.257s | 0.109s | 12,894 | 9,984 | 6 | 0 |

**The finding that matters is the shape, not the size: the cost is dominated by
the runtime's own system prompt, not by the canary's payload.** The canary sends
a nine-word prompt and receives six output tokens, and still pays ~12.9k input
tokens per run because that is what a Codex turn costs before it does anything.
**A trivial canary is not a cheap canary**, and any design that assumed
"make the canary small" would control cost was wrong.

At the spec's assumed 15-minute interval, per runtime: 96 runs/day,
**~1.24M input tokens/day**, of which ~958k cached and **~279k uncached**.

**[H] I am not converting that to money.** This account authenticates by ChatGPT
OAuth, so consumption may be plan quota rather than per-token billing, and
inventing a dollar figure would be exactly the kind of confident fabrication this
project keeps catching. The token numbers are measured; the price is Rohan's to
apply.

## 4. Is the canary worth building? Yes, but not on a timer

You said dropping F-5 was an acceptable outcome. My answer is narrower: **keep
the canary, drop the schedule.**

Its detection value is now largely **redundant with H2**, which catches a dead
runtime at dispatch time in ~0.2s for free. Its remaining unique value is real
but narrow: producing a verifiable proof, and noticing a runtime that broke
*between* dispatches.

So run it **on demand**, not on an interval: when a proof is stale and something
is about to dispatch, and after a failure to re-prove. That is the
"stale-because-idle triggers a canary rather than a refusal" fix, and it
**eliminates your standing objection entirely**: an idle system costs nothing,
and cost becomes proportional to use rather than to wall-clock time. A 15-minute
timer spends 1.24M tokens a day whether or not anyone is working.

**[A]** `DEFAULT_FRESHNESS_BUDGET_S` is set to 1800 and is still a guess. The
staleness number, how often a runtime goes stale while idle, remains unmeasured
and **this task did not produce it either**: three canaries minutes apart cannot
observe a day of idleness. It needs the canary running over days, which is now
cheap to do because the instrument exists. It is still the project's oldest open
number.

## 5. What the hostile conditions broke

Five things, supplied deliberately rather than by accident. Fake runtimes as
shell scripts, so these cost no tokens and are deterministic.

**5.1 A missing binary RAISED instead of refusing**, and `SpawnHop.spawn`
propagated it. **H1's `dispatch()` never raises; H2 did not have that property
and nobody had noticed, because the friendly path never raises.** Now the
adapter returns `runtime_binary_unavailable`, and the hop additionally wraps the
adapter, because an adapter is third-party-shaped code by design and the hop
should assume nothing about its manners.

**5.2 A partial line then silence held a 3 second budget for 30 seconds. This is
the third appearance of the same bug class and my previous fix did not cover
it.** `selectors` reports readiness **per byte**; `readline()` still blocks until
it sees a **newline**. A child that writes `{"type":"thread.` and stops therefore
re-blocks the loop exactly as a bare `readline()` did. Fixed properly by owning
the buffering: `os.read` never waits for a newline, and an unterminated tail is
simply never a line.

**Your standing rule, "when you fix a class of bug, grep for the class", is
insufficient and this is the evidence.** I did grep. I found the twin in
`drain()` and fixed it. I still missed this, because grep finds **textual**
siblings and this was a **semantic** sibling: the property that matters is not
"does this call `readline`" but "can a peer block this loop past its deadline".
The rule should be: when you fix a class of bug, name the PROPERTY that was
violated and audit for the property.

**5.3 A start signal carrying no thread id was reported as a timeout.** It is
not one, and the misreport sends an operator to look at the clock instead of at
the runtime. Now `malformed_start_signal`.

**5.4 A failing canary recorded no disproof, so F-5's only refusal could never
fire.** The gate would have been decorative: `DISPROVEN` was reachable in theory
and unreachable in practice. Found by reading the code after the happy path
passed, which is the one review technique that has worked repeatedly here.

**5.5 The forgery hole in 1.4.**

**A hostile condition that did NOT break anything:** a canary failing while a
real dispatch is in flight. A `DISPROVEN` runtime refuses **new** work and does
not rewrite history; the in-flight dispatch remains resolvable by its
`dispatch_key` and its receipt is unchanged. That was the one I most expected to
break.

## 6. New vanish points

| # | vanish point | status |
|---|---|---|
| 23 | **Asymmetric error contracts across a seam.** One side promises never to raise, the adjacent side raises, and only a hostile input reveals it | **CLOSED here.** Open in general: nothing checks that a seam's two sides agree about failure |
| 24 | **Readiness mistaken for completeness.** `select()` says a byte is available; code assumes a line is | **CLOSED here** by owned buffering |
| 25 | **A refusal whose triggering condition is never recorded.** The gate refuses on DISPROVEN and nothing wrote DISPROVEN, so the refusal is decorative | **CLOSED here.** A general class worth a check: for every refusal, who writes the state it refuses on |
| 26 | **A write that implicitly clears a stronger fact.** Recording a proof silently lifted a disproof | **CLOSED here** |

## UNVERIFIED

- The staleness budget is still unmeasured. 1800s is a guess.
- Canary cost is n=3 on one machine with a warm cache and one prompt; the cold
  run cost 17 percent more input tokens than the warm ones and I have one cold
  sample.
- No dollar cost. Deliberately not estimated.
- The evidence verifier reads the first 40 lines of a rollout for a thread id. A
  rollout whose id appears later would verify as invalid. Not observed; the id
  is in the filename and the first record in every sample I looked at.
- `PROVEN_STALE -> ALLOW_AND_REPROVE` returns the action but **nothing in the
  broker yet acts on it**: no re-prove is triggered automatically. The gate is
  correct and the wiring is absent, which is a gap, not a design decision.
- Claude Code's path remains entirely unexercised. Everything here is Codex.
- 74 tests, still written by the author of the code, with the qualification you
  added to the handoff standing.

## 7. Where I think you may still be framing this wrongly

**1. The instruction "fix F-5 then build the canary" contained an assumption
that the work disproved.** It presumes F-5 is a safety property needing repair.
What contact showed is that F-5 was a **substitute for a receipt we did not have
yet**, and H2 now provides that receipt directly, more cheaply and more
truthfully. The right move was mostly deletion. I would generalise: when a
refusal predates the mechanism that makes it checkable, expect to delete most of
it once the mechanism exists, and budget the task as removal rather than repair.

**2. Two of this task's five findings came from reading code after the happy
path passed, not from tests or hostile inputs.** 5.4 and 1.4 were both "the
feature works, now who writes the state it depends on". That is a distinct
technique from testing and it has now found more defects here than my tests
have. It deserves to be a named step in build tasks rather than something I
happen to do.

**3. The project has one instrument and no baseline.** The canary exists now and
its only measurements are three runs taken minutes apart. Every remaining number
in the spec, the staleness budget, the freshness budget, the canary interval, is
a question about **behaviour over days**, and nothing in this project has ever
observed anything for longer than a few minutes. If those numbers matter, the
cheapest next step is not another build task: it is leaving the canary running
on a long interval and looking at it tomorrow. If nobody is going to do that,
then the honest move is to delete the freshness budget entirely and let H2 be the
only liveness check, which would be a simpler system than the one I just built.
