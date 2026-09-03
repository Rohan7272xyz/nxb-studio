# What a deep liveness signal actually is, and whether we need one

Task `nxb-022`. Worker 1. 2026-08-28. Research, nothing implemented, H2 untouched.

Probes in `evidence/nxb-022/`.

---

## 0. First, a correction to my own ratified finding

In nxb-017 I wrote that "a canary keyed on `thread.started` stays green through
exactly the outage it exists to catch", and that was ratified and propagated into
this brief. **The claim is true about H2's start signal and false about the
canary.** I did not read `nxb/canary.py` before saying it.

The canary as built is **already deep**. It runs a full round trip and refuses
anything less: `delivery != "REPORT_PRESENT"` fails, and a pass additionally
requires `evidence_for(thread_id)` to resolve to a rollout file Codex wrote and
the broker did not. Its own comment says so: "A canary that started but did not
come back is NOT a pass."

Measured, running the real `run_canary` against a dead endpoint:

```
HEALTHY          ok=True   reason=None            wall=6.3s
API UNREACHABLE  ok=False  reason=no_output_file  wall=25.6s
```

So the outage this task was commissioned to catch **is already caught**.

What is genuinely shallow is narrower: H2's `STARTED` state, its
`elapsed_to_start` field, and any consumer that reads "H2 STARTED" as evidence a
runtime is healthy. That is a real hazard and it is the thing to fix. It is not
the canary.

I should have checked before making the claim, and the brief inherited my error.

---

## 1. The deep signal, measured rather than read

Timing separates local events from post-round-trip ones with no documentation
involved. A 108KB prompt moving the start signal 11ms (nxb-017) already proved
`thread.started` contains no API call; here is the whole sequence.

### Codex

```
   t(s)   event
  0.255   thread.started                 <- LOCAL
  0.260   turn.started                   <- LOCAL (5ms later; cannot be a round trip)
  3.293   item.completed:agent_message   <- FIRST POST-ROUND-TRIP EVENT
  3.499   turn.completed
  4.343   <process exit>
```

**The deep signal for Codex is the first `item.*` event.** `turn.completed` is
0.2s later and is the stronger form, since it also asserts the turn finished.

### Claude Code

```
   t(s)   event
  0.857   system:init                    <- LOCAL
  2.255   assistant                      <- FIRST POST-ROUND-TRIP EVENT
  2.277   result:success/is_error=False
```

**The same question has the same answer.** `system/init` is Claude Code's
`thread.started`: emitted before any model call, carrying the resolved model,
permission mode and socket path. The deep signal is the first `assistant`
message, and `result` is the stronger form.

The two runtimes are structurally identical here: one local "I launched" event,
then a gap, then the first event that cannot exist without a completed round
trip.

---

## 2. The acceptance test

Simulated per invocation, with nothing written to any config file: for Codex a
custom provider pointed at `http://127.0.0.1:9` (the discard port), for Claude
Code `ANTHROPIC_BASE_URL` at the same. The binary launches normally in both
cases; only the API is unreachable.

### Codex, API unreachable

```
events: ['thread.started', 'turn.started', 'error', 'error', 'error', 'error']
wall=60.0s exit=-9 killed_at_budget=True

SHALLOW  thread.started : True    <-- stays GREEN through the outage
SHALLOW  turn.started   : True    <-- also green
DEEP     any item.*     : False
DEEP     turn.completed : False
```

### Claude Code, API unreachable

```
  0.584  system:init      <-- stays GREEN
  0.596  system:api_retry
  1.153  system:api_retry
  2.267  system:api_retry
  ... doubling ...
 69.402  system:api_retry
DEEP    assistant present : False
result                     : []
```

**Acceptance test passes on both runtimes.** The shallow signal is present
throughout the outage; the deep candidate is absent. And the canary as built
fails correctly, with `no_output_file`.

### Two things the outage test found that were not asked for

**Neither runtime fails fast, and neither self-terminates.** Codex emitted
`error` events reading "Reconnecting... waiting for network" and was still
retrying when I killed it at 60s. Claude Code retried 8 times on a doubling
backoff and was still going at 69s (its `api_retry` frames declare
`max_retries: 10`, so it is bounded but slow). **Any canary must carry its own
deadline; neither runtime will return one.** A canary that inherits a generous
`drain_budget` and no separate cap will sit through the entire outage on every
interval.

**Both runtimes emit a usable NEGATIVE signal, and Claude Code's is much
better.** Codex gives `{"type":"error","message":"Reconnecting... waiting for
network (...)"}`, which is prose. Claude Code gives a structured frame:

```json
{"type":"system","subtype":"api_retry","attempt":1,"max_retries":10,
 "retry_delay_ms":556,"error_status":null,"error":"unknown"}
```

Either lets a canary conclude DISPROVEN in about 0.6s instead of burning a full
drain budget. That is worth more than the depth question itself: it turns a
25.6s failure into a sub-second one.

---

## 3. What it costs

### Codex, one trivial canary

```
input_tokens         12,884   (of which 9,984 cached)
output_tokens             5
total_tokens         12,889
wall, spawn to exit    3.73s
wall, full canary      6.3s
```

That is the ~12.9k figure in the brief, reproduced exactly.

### Claude Code, one trivial canary

```
input_tokens              10
cache_read            13,595
cache_creation         7,058
output_tokens             54
total_cost_usd        $0.0167
duration               1.44s
```

### The finding that settles the cost question

**The deep signal costs nothing extra.** The 12,889 tokens are spent the instant
you dispatch at all: the base context is the cost, and the model has already been
called by the time `turn.started` fires. Waiting for `turn.completed` rather than
`thread.started` costs **3.5 seconds of wall clock and zero additional tokens**.

There is no depth-versus-cost trade here. A shallow canary pays the full price of
a deep one and then discards the evidence.

---

## 4. Recommendation

**Do not delete the liveness claim, because the deep signal already exists, is
already paid for, and is already what the canary asserts.** Deleting it would
remove a check that measurably catches the outage in exchange for saving nothing.

Three narrower changes, in order of value:

1. **Add the negative signal.** Key DISPROVEN on Codex `error` or Claude Code
   `system:api_retry`. Turns a 25.6s canary failure into roughly 0.6s and removes
   the need to sit out the drain budget. Highest value, lowest cost.
2. **Give the canary its own deadline, separate from `drain_budget`.** Measured:
   neither runtime returns on an unreachable API. This is not optional.
3. **Delete the shallow artefacts that invited my own error.** `elapsed_to_start`
   in the H2 receipt reads like a health metric and is a process-startup timing.
   Either rename it to say so or drop it. Nothing should be able to read H2
   `STARTED` as liveness.

**Where deletion IS the honest answer, and it is not where the brief looked.**

The canary is not competing with nothing, it is competing with **the next real
dispatch**, which proves the same property better because it is the real payload.
`canary.py` already says a canary is "the smallest possible dispatch". So the
canary's entire marginal value is *early detection during idle periods*, and that
value falls to zero as dispatch frequency rises.

Nobody has measured dispatch frequency. If the broker dispatches several times an
hour, a 15-minute canary is mostly re-proving what a dispatch proved minutes ago,
at 12.9k tokens each, forever, to detect a condition that has occurred once. That
is the same shape as the freshness budget that was deleted.

**So the deletable thing is the canary INTERVAL, not the liveness claim.** Run the
canary only after a measured idle gap, rather than on a fixed schedule. It costs
nothing to specify, it preserves every property the canary has, and it deletes
most of the spend. I did not measure the dispatch-frequency distribution, so I
cannot say what the gap should be, and that is the number to get before anyone
picks one.

---

## 5. Where I think the framing is wrong

**1. The brief inherited an error of mine and nobody caught it, including me
until I read the file.** "A canary keyed on `thread.started`" describes a canary
that does not exist. The general lesson is the one the project already has and
keeps paying for: I asserted a property of a component I had not read, it was
ratified, and it became the premise of the next task. A ratified finding is not a
verified one, and the cheapest guard is that the worker who makes a claim about a
file names the file.

**2. "Is a deep signal worth its cost" was unanswerable as posed, because it
presumes the deep signal has a marginal cost.** It has none. The right question
is the one in section 4: what is the canary's marginal value over the next real
dispatch, which is a question about dispatch frequency and not about signal
depth.

**3. The negative signal matters more than the deep signal and was not asked
about.** Both runtimes announce their own failure within a second, in a
machine-readable frame, and nothing in the design consumes it. The deep signal
tells you a runtime is healthy in 3.5s. The negative signal tells you it is not
in 0.6s, and the second is the case you care about.

**4. A caution on my own acceptance test.** I simulated an unreachable endpoint,
which is the friendly outage: connection refused, fast and unambiguous. The
outage that actually hurts is the SLOW one, where the API accepts connections and
answers late or never, because that is indistinguishable from a hard task and
every timeout becomes a guess. My test does not cover it, and I would not claim
the canary is proven against it.
