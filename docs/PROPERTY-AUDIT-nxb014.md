# nxb-014: the budget deleted, and one property audited across every read path

Task: nxb-014. Author: Worker 3. Date: 2026-08-28. 79 tests passing.
`contract/contract.json` untouched. C-1 and B-1 left unfixed, deliberately, so
Worker 1's differential harness must catch them unaided.

## 1. Items 1 and 2 collided, and item 2 won

You asked me to wire `PROVEN_STALE` to trigger an on-demand canary, then delete
the freshness budget. **Deleting the budget deletes `PROVEN_STALE`**, because
staleness is defined by nothing else. There is no other signal that ages a proof.

So the wiring survives only in the form the deletion leaves standing: **an
on-demand canary attached to `DISPROVEN`, the only state that still refuses.**

- It is **opt-in**: a `prover` callable passed to the broker. Absent, `DISPROVEN`
  simply refuses.
- Opt-in rather than automatic, because an automatic retry against a
  permanently dead runtime needs a backoff, a backoff needs a number, and a
  number nobody has is exactly what this task deletes. I was not going to
  delete one invented constant and introduce another.
- Measured end to end: healthy runtime allows and **never calls the prover**; a
  failed canary sets `DISPROVEN` and dispatch refuses; the same dispatch with a
  prover runs one real canary (4.2s), the runtime recovers, and the gate reads
  `PROVEN -> ALLOW`. An idle system costs nothing, which was the whole objection.

## 2. What deleting the budget simplified

More than the budget. Once a proof no longer *grants* anything, everything that
existed to decide whether to trust one becomes dead weight.

**Deleted:** `PROVEN_FRESH`, `PROVEN_STALE`, `PROOF_INVALID`, `verify()` and its
age arithmetic, `FUTURE_SKEW_TOLERANCE_S`, the future-dated-proof rule, the
`proof_invalid_discarded` alarm and the broker's `alarms` list,
`DEFAULT_FRESHNESS_BUDGET_S`, `freshness_budget_s` on the broker and on
`gate_state`, the `verifier` parameter on the gate, and a `datetime` import.

**The gate is now three lines of data:**

```python
GATE = {DISPROVEN: "REFUSE", NEVER_PROVEN: "ALLOW", PROVEN: "ALLOW"}
```

`proof.py` went from 216 lines to 173, and roughly half of the F-5 test file was
deleted with the states it covered. That is not lost coverage; those tests
proved things about machinery that no longer exists.

**Verification survives in exactly one place**, and moving it there is the
cleanest part of this. A proof no longer grants permission, so forging one grants
nothing and there is nothing to alarm about. But a disproof may still only be
lifted by evidence, so `clear_disproof` takes a proof and a verifier and refuses
an unverifiable one. **Verification moved off the hot path, where it ran on every
dispatch, onto the rare path, where it runs when a failure is being cleared.**

One thing I did **not** delete, and the reason matters. `clear_disproof` with no
proof at all is still allowed as an explicit operator override. Refusing it would
send the operator to edit the JSON by hand, which is the forging failure wearing
a different costume. **Leaving an honest override is part of not incentivising a
dishonest one.**

## 3. The property audit

Property: **can a peer block this loop past its deadline, or make it do
unbounded work?** Applied to every read path in `nxb/`, including the two
already fixed.

| site | peer-controlled input | verdict |
|---|---|---|
| `CodexAdapter.spawn` read loop | child's stdout | **fixed nxb-011.** selectors + owned line buffer, bounded by `start_timeout` |
| `CodexAdapter.drain` read loop | child's stdout | **fixed nxb-011.** Same |
| `_LineReader.drain_ready` | child's stdout | safe. `os.read` runs only after `select` reports readable, and there is a single reader |
| `CodexAdapter._kill` | child | bounded, two `wait(timeout=3)` |
| `codex_evidence_verifier` | **yes, `evidence_path` comes from a proof** | **near miss, see 3.1** |
| `ProofStore._load` | store path | **near miss, same shape.** Now explicit |
| `canary._usage_from_events` | **yes, the child writes the events file** | **unbounded work. Fixed, see 3.2** |
| `CodexAdapter.evidence_for` | session tree Codex writes | unbounded work, currently trivial. See 3.3 |
| `Ledger` sqlite connect | another process holding a lock | bounded by sqlite's 5s busy timeout |
| `__main__` file opens | operator argv | operator-visible; out of the property's scope |
| `contract` / `h2` module load | repo files at import | not peer-controlled |

**No fourth blocking instance was found.** Two near misses, one real
unbounded-work instance, one slow-growing concern.

### 3.1 The predicted fourth instance was already safe, by accident

I predicted `codex_evidence_verifier` would block forever on a proof pointing at
a FIFO, since `open()` on a FIFO with no writer never returns and this ran inside
the dispatch gate. **I tested it before claiming it, and it returned `False` in
milliseconds.**

The reason is instructive: the guard was `os.path.isfile(path)`, and
`os.path.isfile` means `S_ISREG`, which excludes a FIFO. **I wrote it meaning
"exists".** The protection was real and entirely accidental, and a later
refactor to `os.path.exists`, which is what someone would write if they thought
the check meant what I thought it meant, would have opened the hole.

It is now an explicit `stat.S_ISREG` check with a comment saying why, and a test
that runs the verifier against a real FIFO in a subprocess with a 10-second
timeout, so the test's own termination is the assertion. `ProofStore._load` had
the same accidental protection and now has the same explicit one.

**This is the audit's most useful output and it is not a bug fix.** It converted
a property that happened to hold into one that is guaranteed to.

### 3.2 One real unbounded-work instance

`_usage_from_events` scanned the whole events file forward. **That file is
written by the child, so its size is peer-controlled**, and a chatty or hostile
child makes the scan unbounded. `turn.completed` is the last event of a turn, so
reading a bounded 256KB **tail** is both safe and more likely to find it. Fixed.

Reading bounded, but **writing is still not**: the adapter streams every byte the
child emits into `events.jsonl` with no cap, so a child can still fill the disk.
That is a real remaining hole of the same family and I did not fix it, because a
cap needs a size number and picking one unmeasured is the thing this task
deleted. It wants a measurement of real event-stream sizes first.

### 3.3 A slow-growing concern

`evidence_for` walks `~/.codex/sessions` in full on a miss. Measured today: 304
files, 0.001s. Codex never prunes that tree, so this grows without bound over the
life of the machine. Not a defect now; worth knowing before it is one.

### 3.4 What the audit says about the rule

Your replaced rule, name the property and audit for it, worked, and it worked in
a way grep could not have: **the two sites it flagged contain no `readline` and
no loop.** They are `open()` calls. Grepping for the class would have found
neither. The property found both.

It also produced a false positive, which is the honest cost: I predicted a
blocking bug that was not there. **Predicting and then testing is the correct
shape**, and the alternative, claiming it from reading, would have put a
fabricated vulnerability in a report.

## UNVERIFIED

- The events-file write cap (3.2) is unfixed and needs a size measurement.
- `evidence_for`'s walk is fine at 304 files. I have not measured it at 100k.
- The on-demand prover is exercised with the real canary once and by fakes in
  tests. It has never run against a runtime that is genuinely, permanently dead;
  the disproof in the live run was produced by a missing binary.
- Deleting the budget is a bet that staleness does not matter. It is a bet, made
  on the absence of evidence rather than on evidence of absence, and it is
  reversible: the disproof machinery it leaves behind is what a future budget
  would attach to.
- 79 tests, same author, your standing qualification applies.

## Where I think you may still be framing this wrongly

**1. "No new hops until the third arm lands" may be holding the wrong thing
still.** The reason to wait is independence, and the third arm supplies it for
H1. But H2 has never been independently implemented or reviewed by anything, and
it now carries the adapter, the kill discipline, three bug classes I introduced
myself, and the only measured numbers in the project. **If independence is the
scarce good, H2 is where it is scarcest**, and waiting for an H1 differential
does not buy any of it.

**2. The deletion in this task was larger than the wiring, and that is now twice
in a row.** nxb-011 was scoped as "fix F-5" and was mostly deletion. nxb-014 was
scoped as "wire, then delete" and the wiring turned out to be one optional
callback while the deletion took out five states, three functions and a
parameter. Two data points is not a trend, but if the third build task also
deletes more than it adds, **the project's default assumption should invert**:
scope a task as removal and treat any addition as the thing needing
justification.

**3. Nobody has run the whole thing as a user would.** Every measurement here
comes from a script I wrote to exercise a component I wrote. There is still no
moment where someone dispatches real work through H1 and H2 and gets a result
back, because H3 does not exist. **The system currently cannot return an
answer.** That is fine as a build order, but it means every claim about
ergonomics, envelope shape and operator experience is untested, and the first
real use will find things that none of these audits can.
