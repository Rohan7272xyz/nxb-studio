# Sealed builder predictions, nxb-018

**SEALED. Worker 2 is barred from this file by name. Do not relay its contents
to whoever runs the cold-user pass, before or during their run.**

Author: Worker 3, who built every hop. Written 2026-08-28, before any cold use.
Purpose: turn a withheld opinion into evidence. **The value is entirely in the
places I am wrong**, so these are written to be falsifiable, not to look good
afterwards.

## How to score this

Each prediction has a confidence and an explicit falsifier. A prediction is
WRONG if its falsifier occurs, regardless of how reasonable it sounded. I have
included predictions about what will go *well*, because a builder who only
predicts problems is hedging.

Do not count "they were confused for a moment" as a hit. Count it only if the
falsifier fails.

---

## The one that is not a prediction: I found a real hole writing this

Stating it first because it is not about usability and it should not wait for a
cold user to find it.

**`units` never reaches the worker. Only `body` does.** The envelope carries
`units`, which is hashed into `declared_digest` and counted into
`declared_count`. `RoundTrip.dispatch(envelope, body=...)` sends `body` to the
runtime. `units` is never read again.

So **F-8 (digest divergence) and F-9 (count divergence), the two refusals I have
been calling the flagship closure of vanish points 5 and 6, currently guard a
field that carries no work.** They would detect truncation of a decoy. The
payload that actually reaches the worker is unguarded by either.

That is the most serious defect I know of in this system, it is mine, and I found
it by being made to write down what a stranger would trip over. I have **not**
fixed it: fixing it would make prediction P1 unfalsifiable, and that trade is the
orchestrator's to make, not mine. It is reported separately.

---

## Predictions, ranked by confidence

**P1 — 95%. They will put the task into `units` and get a worker that never
saw it.** The envelope's `units` field reads like the payload. Nothing warns,
nothing errors, and the dispatch succeeds. They will get a report about
whatever was in `body` (or an empty instruction) and be confused about why the
worker ignored them.
*Falsifier: they put the instruction in `body` on the first attempt without
asking or reading `roundtrip.py`.*

**P2 — 90%. They will compute `declared_digest` themselves and get
`digest_divergence`.** The obvious move is `hashlib.sha256(json.dumps(units))`,
which does not match `nxb.receipt.digest_units` because the canonicalisation
differs. I flagged this in nxb-006 as F-8's hidden dependency and never
published the canonicalisation.
*Falsifier: they find and use `digest_units` unprompted, or their first digest
matches.*

**P3 — 85%. Their first capability declaration will be refused for an omitted
field.** All ten fields are required, including ones they have no value for, and
the error names only the first one missing, so they will fix them one at a time.
*Falsifier: their first `register()` call succeeds.*

**P4 — 80%. They will read `state: "OBSERVED"` as success when the spawn
failed.** `RoundTrip.dispatch` returns `OBSERVED` even when H2 refused; the
failure is only visible in the nested `h2` key and in the stored outcome. **This
is a false green that I built**, in a project whose entire subject is false
greens.
*Falsifier: they notice the spawn failed without being told where to look.*

**P5 — 75%. They will look for a README or a CLI that runs the whole thing, find
neither, and have to read source to make one dispatch.** There is no README.
`python -m nxb` offers `dispatch`, `digest`, `contract`, and `dispatch` is
H1-only: **the CLI cannot produce an answer.** The round trip is Python API only.
*Falsifier: they complete a round trip without opening a file under `nxb/`.*

**P6 — 70%. They will hit `UNKNOWN_KEY` after a refused dispatch and read it as
a bug.** If H1 refuses, no outcome is stored, so `collect()` says `UNKNOWN_KEY`
for a key they believe they dispatched. The state is correct and the wording
will not feel correct.
*Falsifier: they never see `UNKNOWN_KEY`, or see it and correctly infer H1
refused.*

**P7 — 65%. They will confuse `run_root` and `work_dir`.** `work_dir` is the
worker's cwd; `run_root` is where broker artefacts land. The names say neither.
*Falsifier: they pass both correctly first time.*

**P8 — 60%. They will not notice `effect` or `refusal_signal_available` at all**,
or will read `effect: UNCHECKED` as something being wrong.
*Falsifier: they mention either field unprompted, correctly.*

**P9 — 55%. They will hit a `TypeError` from keyword-only arguments.** `Broker`
takes `ledger` positionally; `RoundTrip` takes everything keyword-only. The
inconsistency is mine and has no reason.
*Falsifier: no TypeError of this shape in their session.*

## Predictions that things will go WELL

**P10 — 80%. The three dispatch return states will read as unambiguous** once
seen, and they will not confuse `REFUSED` with `UNKNOWN`.
*Falsifier: they treat `REFUSED` and `UNKNOWN` as the same outcome.*

**P11 — 75%. `pending()` will make immediate sense as an alarm** without needing
the reasoning about timers.
*Falsifier: they ask what `pending()` is for, or never call it.*

**P12 — 70%. The report field set will feel natural**, because it is the one that
survived seven real tasks rather than one I designed.
*Falsifier: they propose changing the report fields.*

## A genuine coin-flip, stated as one

**The two-layer outcome** (`delivery` for the broker's machinery,
`report.status` for the worker's claim). I believe separating them is right and
load-bearing. I have no idea whether a cold reader will find it clarifying or
find it redundant bureaucracy and ask why there are two status fields. **50/50,
and I would like to know**, because if it reads as redundant then the
distinction this project cares most about is not being carried by the design.

## What I would change if nobody were watching

Ranked by how much I want it, not by size.

1. **Delete `units` from the envelope, or make `body` derive from it.** The dual
   payload is indefensible, and while it exists my two flagship guards protect a
   decoy. This is the change I want most and it is not an ergonomics change.
2. **Make `dispatch` return a state that reflects H2 failure.** Probably a
   fourth state, or `REFUSED` with the H2 reason promoted. I would not leave a
   false green in this codebase for a day longer than the experiment needs.
3. **Publish the canonicalisation** with the contract, so F-8 stops being a trap
   for anyone who computes a digest the obvious way.
4. **A README with one worked round trip**, twenty lines, copy-pasteable.
5. **`nxb run`** on the CLI, so the thing the project exists for is reachable
   without writing Python.
6. **Default `run_root` under the ledger's directory** and drop it from the
   constructor.
7. **Make `Broker` keyword-only** to match `RoundTrip`.

## Where I might be wrong about being wrong

I am likelier to be miscalibrated in these directions, and I would rather name
them than be caught by them:

- **I may be over-predicting confusion.** I know every sharp edge, so I may be
  scoring near-misses as certainties. If most of P1 to P9 miss, the honest
  conclusion is that I am a bad predictor of other people, not that the system
  is fine.
- **I have no prediction about the things I cannot see.** The most valuable
  finding from the cold pass will probably be something absent from this
  document entirely, and its absence here is the point.
- **I may be wrong that P1 is the worst problem.** It is the worst one *I can
  see*. A cold user may hit something structural about the envelope-plus-body
  shape that makes P1 look like a detail.
