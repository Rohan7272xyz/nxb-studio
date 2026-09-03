# nxb-015: the loop closes

Task: nxb-015. Author: Worker 3. Date: 2026-08-28. 99 tests passing.
`contract/contract.json` not modified. C-1 and B-1 left unfixed. H3 and H4 built
minimally, against Codex, so that for the first time a dispatch can return an
answer. **I did not evaluate whether it is usable**, per instruction; see
section 6.

## 1. What a round trip actually looks like

One real dispatch, live Codex, start to finish.

```
--- DISPATCH (H1 -> H2 -> H3) ---
H1 receipt : rcpt-6b7844eb...  digest 8f8498d4159f677a
H2 receipt : h2-de4148ea...    thread 01a0493c-e03a-7e42-8b5a-1cb4e324bcb8
             started in 0.377 s
H3 receipt : h3-2d15d6ae...    bytes 186
terminal   : exit 0, turn_completed True, out_present True

--- PENDING before collect (this list IS the alarm) ---
[{'dispatch_key': 'rt-001', 'recorded_at': '...', 'collect_count': 0}]

--- COLLECT (H4) ---
state: DELIVERED
{
  "dispatch_key": "rt-001",
  "delivery": "REPORT_PRESENT",
  "report": {"task_id": "rt-001", "status": "COMPLETE", "summary": "391",
             "evidence": "17 × 23 = 391.", "was_refused": false, ...},
  "provenance": {"runtime_id": "codex", "pinned_model": "gpt-5.6-luna",
                 "runtime_ref": "01a0493c-...", "recorded_at": "..."},
  "effect_unverified": true
}

--- PENDING after collect ---   []
--- collect again ---           DELIVERED   (nothing is consumed by reading)
--- unknown key ---             UNKNOWN_KEY
```

Two calls, each returning the thing rather than an acknowledgement that a thing
happened. `dispatch` blocks only on hops that can block, and both budgets are
the runtime's own measured numbers. `collect` never blocks at all.

**H4 has no timer.** The spec wanted an alarm when delivery has not happened
within a budget. No budget has been measured, and this project has twice found
that machinery justified by an unmeasured constant gets tuned until it stops
firing. So non-delivery is surfaced by a **queryable list that never clears
itself**. `pending()` is the alarm: inspectable at any moment, free when idle,
and unlike a timer it cannot be silenced by widening a number.

**Delivery means collected, not sent.** [M: nxb-006] a push whose return value
is a transmission ack proves nothing, so an outcome is `DELIVERED` only once the
dispatcher has collected it. Redelivery is on demand and idempotent: a
dispatcher that lost its context asks again and gets the same outcome.

## 2. What I had to invent, because the contract does not cover it

`contract.json` describes the dispatch half and stops. Everything about coming
back was missing. Added additively in `contract/h3.json`.

1. **A worker report schema.** There was none. The field set is **not** invented:
   it is the one from the old NEXUS codebase that survived seven tasks across
   three workers without amendment, which is nxb-004's reuse recommendation
   being taken.
2. **A two-layer outcome.** `delivery` is the broker's machinery;
   `report.status` is the **worker's claim**. Kept as separate fields on
   purpose. Merging them is precisely how a clean pipeline gets read as a clean
   result, which is the false-green this project keeps finding.
3. **`effect_unverified`.** The spec required the flag (F-20) but nothing
   carried it. It is true whenever the runtime's declared `refusal_signal` is
   null, which for Codex is always.
4. **`was_refused` as a required report field**, and directive text telling the
   worker why. [M: nxb-002] a sandbox denial produces no event at all, so the
   worker's own claim is the **only** channel that can carry it. The directive
   says so explicitly, because a worker that does not know the broker is blind
   has no reason to volunteer it.
5. **`UNKNOWN_KEY`.** Collecting a key that was never dispatched must be
   distinguishable from a key whose outcome is not ready. The old system had no
   equivalent and the difference is the whole "nothing came back versus nothing
   was sent" confusion.
6. **`peek` separate from `collect`.** An operator reading an outcome must not
   mark it delivered, or looking at the alarm silences it.
7. **Re-put preserves `delivered_at`.** Re-recording an outcome must not
   resurrect it into the pending list.

**And one thing I could not build, which is a finding about the spec.** The
four-hop model says every hop emits a receipt **to its sender**. H3's sender is
a one-shot `codex exec` child, and it is **dead by the time its report is
observed**. The H3 receipt exists, because it is what H4 delivers and what the
ledger records, but it is addressed to nobody. **For one-shot runtimes the
receipt-to-sender rule is vacuous at H3**, and the model quietly assumed all
four hops have living endpoints in both directions. It would not be vacuous for
a long-lived worker, which is exactly the case not built.

## 3. What closing the loop let me delete

`nxb/canary.py`: **138 lines to 78**. It hand-rolled H1, H2, the drain and its
own terminal check, because when it was written there was no round trip to
reuse. **The canary is no longer a special code path. It is the smallest
possible dispatch**, and what survives is only the part that was ever
canary-specific: recording a proof on success and a disproof on failure.

Deleted with it: `_usage_from_events` and its bounded-tail reader, which existed
to extract token usage from the event stream. **Honest note: that helper
produced the only cost number in the project** (nxb-011's ~12.9k input tokens
per canary). It is recoverable from git at `9ab3aab`. If cost tracking matters
going forward, it should not come back as a canary-only helper; it should be a
field in the outcome's `provenance`, measured on every dispatch rather than only
on canaries. I did not add that, because it was not asked for and this task was
scoped as removal.

## 4. Two things other people's tests caught in my work

Worth recording against the standing qualification that my own tests have never
caught my own defects.

**Worker 1's leak test caught `h3.json`.** It sweeps every published contract
file for implementation symbols, and my `enforced_by` fields named `nxb.*`
modules. The rule is right, the contract must stay implementable by someone who
has never seen `nxb/`, and I complied by moving the bindings to
`tests/enforcement_map.json`. **This is the first time another agent's test has
caught my work**, which is what the third arm was for.

**nxb-016 renamed the contract's example runtime and broke 26 of my tests.**
They hardcoded the old name while the fixtures derived everything else from the
contract. The fix is the general lesson: **a test fixture that restates a
contract value is a second copy of the contract**, and it drifts exactly like
prose does. Fixtures now derive the id. One file was correctly left alone,
because it tests the real measured Claude Code declaration where the name is a
runtime id rather than a contract example, and my first bulk edit got that wrong.

## UNVERIFIED

- **Only Codex.** The round trip has never run against Claude Code. See 6.2.
- One real end-to-end run, one trivial task. No failure path has been exercised
  live: `NO_REPORT`, `RUNTIME_FAILED` and an invalid report are covered by unit
  tests with fabricated files, not by a real worker producing them.
- A worker that ignores `--output-schema`, or returns a schema-valid report that
  is substantively false, is untested. The schema constrains shape, not truth.
- `was_refused` has never been observed set true by a real worker. Its value
  depends entirely on worker honesty and nothing measures whether workers are
  honest about it.
- The outbox has never held more than one outcome, and `pending()` has never
  been looked at with a backlog in it.
- No concurrency: two dispatches in flight at once is untested.
- 99 tests, same author, with the standing qualification.

## 5. Where I think you may still be framing this wrongly

**5.1 `effect_unverified` is about to become F-5 again, and I would rather flag
it now than discover it.** Every Codex outcome carries `effect_unverified: true`,
because Codex's `refusal_signal` is measured absent. Spec rule F-20 says such an
outcome **may not be ratified COMPLETE**. So the moment anything enforces F-20,
**it refuses to ratify one hundred percent of Codex results**, forever, for a
reason no operator can act on.

That is exactly F-5's failure shape: a refusal that always fires gets ignored or
switched off, and the second-order damage is that the one case it was meant to
catch becomes invisible among the noise. This is the third time this pattern has
appeared in this project. I am flagging it **before** it is wired rather than
after, and the fix is probably the same asymmetry that saved F-5: do not refuse
on "cannot verify", refuse on "verified false", and make verification cheap where
the effect is externally checkable.

**5.2 The loop is closed for the easy runtime, and the founding use case is
still half-open.** This works for spawn-shaped work on a one-shot child the
broker owns. It does not work at all for reaching a Claude Code session that
already exists, which has no content reply channel [M: nxb-001]. The project was
founded on an Opus orchestrator disagreeing with a GPT worker, and half of that
pairing is the half not built. **"A dispatch can return an answer" is true of
Codex and not yet true of the runtime this whole project runs inside.**

**5.3 I have opinions about the ergonomics and I am deliberately not writing them
down.** You were right that I am the worst available judge, and the specific risk
is not that I would judge badly but that I would **prime the person who judges
well**. A cold user who has read my opinion about the envelope is no longer cold.
So the report stops at "it works", and the shape of `dispatch(envelope, body=...)`,
which I do have views about, is left entirely to them. If that is not what you
wanted, ask and I will write the views down separately, where the cold user will
not see them before their run.
