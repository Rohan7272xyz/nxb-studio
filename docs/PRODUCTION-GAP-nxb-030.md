# What stands between this and production use

Orchestrator 2, 2026-08-28. Written against `a1ad578` plus whatever nxb-027,
nxb-028 and nxb-029 had landed uncommitted at the time; re-check the tree.

Two measurements, then the gap list. Both measurements were taken because the
question "how close are we" cannot be answered from the handoff, which is a
record of what was BUILT rather than of what is REACHABLE.

## MEASURED 1: the round trip has no operator surface, and one caller

`python3 -m nxb --help` offers `dispatch`, `pending`, `collect`, `digest`,
`contract`. Its own help text for `dispatch` reads "H1 only: observe an
envelope, no work is run", and that is accurate: `nxb/__main__.py` constructs a
`Broker` and calls `Broker.dispatch`, which records a receipt and stops.

`RoundTrip`, in `nxb/roundtrip.py`, is the only code path that spawns a runtime
and returns an answer. Its own docstring calls it "the first time in this
project that a dispatch can return an answer."

`grep -rn "RoundTrip" nxb tests harness --include="*.py"` returns three lines:
its definition, and two references in `nxb/canary.py`. It is **not referenced in
`nxb/__main__.py` at all**, and no test imports it.

So the only executable route to a real answer is `run_canary`, whose payload is
the hardcoded `CANARY_UNIT` in `nxb/canary.py`: "Reply with status COMPLETE and
a one-word summary. Do nothing else."

**A broker that can only dispatch its own canary is a library with a
demonstration, not a product.** This is not a defect in any component. Every
piece works. Nothing joins them to a user.

Note the shape: this is the never-read guard's finding class pointed at the
package instead of at a field. A field validated and never read, and a module
built and never reachable, are the same failure.

## MEASURED 2: concurrency is unproven, and one shape of it raises

`evidence/nxb-030/concurrency-probe.py`, output in `evidence/nxb-030/result.txt`.

- **Four dispatchers, separate `Ledger` objects, one database file, 15 dispatches
  each: 60 of 60 receipts written, no errors.** `busy_timeout` is 5000ms, which
  absorbs the contention at this volume. Two shells or two orchestrators against
  one ledger is fine at this scale. Untested above it.
- **Four dispatchers sharing ONE `Ledger` object across threads: 0 of 60 written.**
  Every thread raised `sqlite3.ProgrammingError: SQLite objects created in a
  thread can only be used in that same thread.` `nxb/ledger.py` calls
  `sqlite3.connect(db_path)` without `check_same_thread=False` and without WAL;
  `journal_mode` is `delete`.

**`nxb/dispatch.py:90` documents `dispatch` as "Always returns one of three
shapes, never raises."** Under the second shape it raises. The totality claim is
scoped to inputs and this is a threading misuse, so this is not that clause being
violated on its own terms. It is worse in one respect and better in another:
better because no input can trigger it, worse because the caller who triggers it
is the broker's own intended use. HANDOFF.md's opening sentence is that this
project exists to let ONE orchestrator dispatch to agents across different
runtimes **at once**.

Nothing in `FINDINGS.json` covers this. A search for thread / concurren /
parallel / lock / simultane across the whole findings file returned seven
matches, all of them incidental (`thread.started`, "the blocking class").

## The gap list, ordered by what actually blocks use

1. **No product surface.** MEASURED 1. The round trip needs to be reachable by an
   operator and by another program, with a real payload.
2. **The second runtime.** In flight as nxb-027. Until it lands, the broker
   cannot dispatch to the runtime it runs inside, and every worker on this
   project is that runtime.
3. **Concurrency.** MEASURED 2. Decide whether the broker is single-threaded by
   contract, in which case say so and refuse cross-thread use loudly instead of
   raising a sqlite internal, or make it safe.
4. **Nothing is deployed and nothing consumes it.** The stated downstream user is
   Hokie Transit. There is no integration point, no service, and no run outside
   a developer shell.
5. **Two high-severity findings need a human ruling, not code** (W3-9, W3-11).
   They bound what work may safely be dispatched at all.
6. **One cold-user pass exists** and it was silently misled within two commands.
   Ergonomics beyond that 5.5 minutes is unmeasured.

## What is genuinely solid, stated without hedging

The contract validates itself. The receipt and ledger discipline is real and
enforced by tests rather than by prose. The deadline breaker in `nxb/deadline.py`
ended a bug class that had survived three fixes, a grep and a property audit. The
findings ledger binds its own author and has already turned the suite red to stop
a stale record. A Codex round trip is proven live end to end. The suite was 156
passed / 281 subtests at `a1ad578`.

**The engineering is ahead of the product.** That is an unusual and recoverable
position, and it is the opposite of the one this project was founded to fix,
where a document claimed a capability nothing possessed.
