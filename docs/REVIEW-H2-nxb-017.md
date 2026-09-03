# Independent review of H2

Task `nxb-017`. Worker 1. 2026-08-28. Review only, nothing fixed.

Subjects: `nxb/adapters/codex.py`, `nxb/h2.py`, `contract/h2.json`.

Method: name the property, audit for the property, predict, then TEST before
claiming. Every finding below was executed, not reasoned. Two predictions of mine
failed and both are reported as failures.

Evidence and probes: `evidence/nxb-017/`.

---

## The headline

**There is a fourth instance of the blocking bug class, and it is on the WRITE
path.** The author found three on the read path and fixed all three. Every read
is now correctly bounded by the remaining budget. Sitting inside those same
bounded loops, in both `spawn()` and `drain()`, is:

```python
events.write(line)
events.flush()
```

a write with no deadline, on a sink the peer controls the volume of. Measured:

```
budget=2.0s   ACTUAL: still blocked after 15.0s   >>> OVERRUN, unbounded
```

The author's own sentence about reads applies verbatim: a budget checked around
a blocking operation is not a budget.

**This unifies two of the four things I was asked to weigh separately.** The
uncapped write and the fourth blocking instance are one defect. The uncapped
write is what fills the disk; a full disk is what makes the write block. Each
causes the other.

Demonstrated with a pipe as the sink rather than by filling a real disk on a
shared machine. A full pipe blocks a writer exactly as a full or slow disk does.

### Why the class keeps recurring

Four instances of one bug in one file is not four mistakes, it is one wrong
pattern. The pattern is **enforcing a deadline by checking the clock between
operations**. That works only if every operation between two checks is bounded,
which is a property of the whole file that has to be re-proved after every edit,
and it has now been violated on three read paths and one write path.

The bug class is also stated too narrowly in the code comments, which say *read*.
That framing is why three read fixes did not catch the write. The property that
actually needs auditing is: **can the peer make ANY operation in this loop block,
or make it do unbounded work.**

The fix that ends the class is not a fifth audit. It is a mechanism that can
interrupt a blocked operation from outside the loop.

---

## Findings

### H2-1. Unbounded, deadline-defeating WRITE. HIGH.

Above. `spawn()` and `drain()` both. `stderr.txt` is equally uncapped and is not
mentioned in the author's note, which named only `events.jsonl`.

**Was leaving it the right call? No, and the stated reason is wrong.** The author
left it because "a cap needs a number". Two fixes need no number at all:

1. **Stop writing once you have what you are waiting for.** `spawn()` needs
   exactly one fact, `thread.started`. It does not need to persist every byte the
   child emits before it. `drain()` needs the terminal event. Bounding by
   *purpose* requires no constant.
2. **Make the sink non-blocking**, so the deadline holds regardless of what the
   sink does. This is the same fix the read paths already received.

And if a byte cap is genuinely wanted, the number is not arbitrary either: take
it from the free space on `run_dir` at spawn time. Measured at runtime, not
guessed. "It needs a number" was the wrong reason to stop.

### H2-2. A peer can make the broker burn a core for the whole budget. HIGH.

`spawn()` exits its loop on `reader.eof and proc.poll() is not None`. A child
that **closes stdout but stays alive** gives `eof=True` and `poll()=None`
forever. `select()` reports a closed pipe as permanently readable, so every
iteration returns immediately, reads zero bytes, and loops with no sleep.

```
wall=3.02s  budget=3.0s  deadline honoured: True
CPU burned in the broker process during the wait: 2.97s
CPU/wall ratio: 98%
```

The deadline holds, which is why the existing tests pass. But the peer controls
whether the broker sleeps or spins, and N concurrent spawns cost N cores. This is
the "unbounded work" half of the property, and it is the half nobody has audited.

### H2-3. `_kill` can raise, and the raise escapes. MEDIUM.

```python
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait(timeout=3)      # TimeoutExpired here is NOT caught
```

The outer handler catches only `OSError`. A child that does not reap within 3s of
`SIGKILL` (uninterruptible sleep on a stalled disk or network mount) makes the
second wait raise, and it propagates out of `_kill`. Confirmed:

```
_kill RAISED TimeoutExpired  -> escapes to the caller
```

Two consequences, both on paths that exist today:

- `spawn()`: `killed = self._kill(proc)` is unguarded, so `events` and `errs` are
  never closed (**FD leak**), and the hop converts the true
  `no_start_signal_within_timeout` into `adapter_raised: TimeoutExpired`. The
  operator is sent to look at the adapter instead of at the runtime, which is
  precisely the failure mode the author fixed for `malformed_start_signal`.
- `drain()`: the `events.close()` / `errs.close()` after the kill never run, and
  `drain()` raises despite its docstring promising it "returns the terminal
  facts, never a verdict".

`h2.py` contains the blast radius, since it wraps `adapter.spawn` in
`except Exception`. `drain()` is not wrapped anywhere.

### H2-4. The 5s number: sound for what was measured, under-justified as an extrapolation. MEDIUM.

I re-measured, n=20 rather than n=7, and varied the one input the author names as
unvaried.

```
small prompt   n=20  min=0.103  med=0.117  p90=0.123  max=0.140   failures=0
big prompt     n=8   min=0.112  med=0.128  p90=0.144  max=0.174   failures=0
                     (big = 108,059 bytes, 770x the small prompt)
cold spawn observed separately: 0.662s   (author measured 0.685s)
```

**The author's numbers reproduce.** Warm median 0.117 against their 0.112, and
their 0.167 max sits inside my range. Prompt size is **not** a driver: 770x more
prompt moves the median 11ms. That is a real result in the number's favour and it
removes the variable the author was most worried about.

**The extrapolation is still under-justified, in one specific way.** A timeout is
a question about the TAIL, and the author extrapolated from a MEDIAN and a MAX
taken on an IDLE machine with n=7. n=7 cannot estimate a tail at all. Under
bounded load (5 busy processes on 10 cores, half the machine):

```
under load: n=10  min=0.139  med=0.192  max=0.655
median degrades 1.6x   ***  tail degrades 4.7x  ***
margin at 5s: 28.7x idle  ->  7.6x at half load
```

**The tail degrades three times faster than the median.** That is the whole
answer: the statistic the author extrapolated from is the one that moves least.

**What would falsify the 5s number:** sustained machine load, especially combined
with a cold start, which is the one combination nobody has tested. Cold (0.685)
scaled by the measured load-tail factor (0.655/0.140 = 4.7x) lands around 3.2s,
inside 1.6x of the timeout. This machine routinely runs several agents at once;
during nxb-009 it was running two Codex processes and multiple Claude sessions.
That is the condition to measure, and it has not been.

I would not change the number on this evidence. I would stop calling it
extrapolated from measurement, because the measurement does not cover the regime
where it fails.

### H2-5. `thread.started` proves local startup, not capability. MEDIUM, and it lands on the liveness design.

Not a defect in H2, but H2 is where the fact lives and the liveness design
depends on it.

A 0.117s median and a 108KB prompt that moves it 11ms together say
`thread.started` is emitted **before and independently of any network round
trip**. It is a local process-startup signal.

So a canary keyed on `thread.started` proves that a binary launched on this
machine. It does not prove the runtime can reach its model, that credentials are
valid, or that the API is up. **R-012 requires "an end-to-end capability
assertion through the real path", and the start signal is not one.** A liveness
proof built on it would have gone green throughout an outage that made every
actual dispatch fail. Worth stating explicitly in `h2.json`, because the number
being fast is exactly the evidence that it is shallow.

### H2-6. The live child is the one piece of state not correlated to a receipt. LOW, latent.

`SpawnHop.last_handle` is a single unkeyed slot, overwritten by every spawn.
`roundtrip.py` reads `hop.last_handle` to drain, and `hop.last_handle["out_path"]`
to collect the report.

This system is otherwise obsessive about correlating by receipt: F-10 keys dedup
on `receipt_id`, F-11 enforces one disposition per receipt, R-051 resolves a
repeated key to the original receipt. The running child, the one piece of state
that actually maps to work in flight, is stored in a slot with no key at all.

**Latent, not active**: `roundtrip.py` constructs a fresh `SpawnHop` per call, so
nothing hits it today. It is a trap for the next caller, and `SpawnHop` takes a
ledger and an adapter, which is the signature of an object meant to be reused
across spawns. `already_spawned` refuses per parent, so reuse across different
parents is the intended pattern.

### H2-7. `events.jsonl` is silently corrupted at 64KiB boundaries. LOW today.

`_LineReader.drain_ready` decodes each `os.read(fd, 65536)` chunk independently
with `chunk.decode("utf-8", "replace")`. A multi-byte character straddling the
boundary is decoded as two halves and each is replaced with U+FFFD. Confirmed:

```
bytes at the 65536 boundary: b'\xe6\x97'  (mid-character: True)
contains U+FFFD replacement char: True
```

**My prediction was that this would lose the start signal. It does not**, and I
was wrong: the corruption lands inside JSON string values, U+FFFD is legal there,
and `json.loads` still succeeds. Reported as a failed prediction.

Actual severity is low **today**, and I checked rather than assumed: nothing in
the repository reads `events.jsonl`. It is a write-only evidence artefact, so the
damage is silently corrupted evidence for a human reader.

It becomes real if a runtime ever emits a non-ASCII `runtime_ref`: a corrupted
`thread_id` is recorded in the H2 receipt, and `canary.py` calls
`adapter.evidence_for(thread_id)`, which then finds nothing. Verified that
`evidence_for(corrupted_id)` returns `None`. Codex thread ids are ASCII UUIDs, so
this is unreachable with Codex and reachable for the next runtime.

The fix is an incremental decoder, which costs one line and removes the class.

---

## The kill discipline

**The guard holds.** There is no pattern killing anywhere in `nxb/`, `tests/` or
`harness/`. The only two occurrences of `pkill` in the tree are the docstring
explaining the ban and a test asserting its absence. `_kill` takes a `Popen` and
uses only `send_signal`/`kill`/`wait` on that handle. I could not find a bypass.

**But it kills one process, and the runtime is a tree.** There is no
`start_new_session`, no `preexec_fn`, no process group, no `killpg`. `Popen.kill`
signals exactly one pid. Proven on a synthetic tree:

```
synthetic: parent=27826 grandchild=27827
  after _kill: parent alive=False  grandchild alive=True   >>> ORPHANED
```

**My prediction that this orphans real Codex children FAILED.** Two attempts:
killing at 0.05s reaped cleanly because the tree had not formed yet, and killing
after a 6s run found no surviving descendants. Reported as a failed prediction,
not softened.

It remains a live risk rather than a confirmed defect, for one reason: during
nxb-009 I observed a real three-deep Codex tree (`node` 76404 to
`codex-darwin-arm64` 76405 to 76574) on a run that lasted minutes. My review runs
were short. The regime where the tree exists is the regime where a timeout kill
happens, and I did not manage to test that combination.

**The part that matters for policy:** if a direct-handle kill can leave orphans
for some runtime, then banning the pattern kill removes the remedy without
removing the cause, and the next person with a stray will reach for `pkill`
again. F-15b is correct and incomplete. The completion is process-group
isolation, which makes the direct-handle kill actually reap the tree and makes
the ban costless.

---

## Predictions I got wrong

Recorded because a review that only reports its hits is not a review.

1. UTF-8 boundary corruption would lose the start signal. It does not; the event
   still parses.
2. Real Codex children would be orphaned by `_kill`. Not reproduced in two
   attempts.
3. I expected the timing numbers to be shaky. The author's warm figures reproduce
   closely and prompt size turned out not to matter. The weakness is narrower and
   more specific than I assumed: the tail, not the central estimate.

---

## Where I think the framing is wrong

**1. "Fourth blocking instance" and "unbounded write" are the same finding.** You
listed them as separate things to weigh. The uncapped write is the mechanism that
fills the disk and a full disk is what makes the write block. Treating them
separately is what let the author look straight at the uncapped write, classify
it as a disk-space question, and not see that it was the fourth instance of the
bug he had already fixed three times.

**2. The recurring bug is being described as a series of bugs, and it is one
wrong pattern.** Enforcing a deadline by checking the clock between operations
requires proving that every operation between two checks is bounded, forever,
after every edit. Three fixes and a grep did not hold, and you correctly told me
to assume a fourth. I would stop assuming a fifth and change the pattern: a
deadline enforced by something that can interrupt a blocked operation, rather
than by a check that a blocked operation prevents from running. Otherwise the
right prediction is not "assume a fourth", it is "assume one per new I/O call
site, forever".

**3. "The only measured numbers in the project" is the strongest reason to
distrust them, not to trust them.** They are the only numbers, so they get reused
as anchors. n=7 on one idle machine cannot support a timeout, because a timeout
is a tail question and n=7 has no tail. The measurement is good; it is being
asked to carry more than it can. The cheap fix is not more careful extrapolation,
it is 200 samples under contention, which costs about ten minutes.

**4. One thing you did not ask about and I think matters more than three of the
four you did.** H2-5: the start signal is local. Everything downstream treats
`thread.started` as the runtime being alive, and it only proves a binary
launched. The liveness design asks for an end-to-end capability assertion and
this is not one. A canary on it stays green through exactly the outage it exists
to catch.
