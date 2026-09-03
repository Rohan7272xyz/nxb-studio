# Differential testing: what the equivalence relation found, and what running it found

Task `nxb-012` Part 2. Worker 1. 2026-08-28.

Harness in `harness/`. Run with `python3 harness/run.py`.

## Acceptance test: does it catch C-1 unaided

**Yes.** Given no hint that a digest defect exists, the harness reports divergent
`payload_digest` on 12 of 28 corpus cases and then demonstrates the consequence:

```
PROBE 1  canonicalisation
  agree    ascii-baseline   reference fa69bffd0bee..  codex fa69bffd0bee..
  DIVERGE  latin1-accent    reference c7d8118f1d3b..  codex 90414d086525..
  DIVERGE  cjk              reference ac8f9afe1dc6..  codex 6ce7c62270b9..
  DIVERGE  emoji            reference 9ba992bf7097..  codex 92779df47c35..

PROBE 4  cross-arm: one arm computes declared_digest, the other brokers it
  REFUSED  sender=reference broker=codex      latin1-accent   digest_divergence
  REFUSED  sender=codex     broker=reference  latin1-accent   digest_divergence
  ... 27 refused pairs
```

Probe 4 is the one that matters. It is not a comparison of two functions, it is
the production failure: a dispatcher on one implementation hands a broker on the
other an envelope containing an accent, and the broker refuses it as
`digest_divergence`, a reason that points at truncation.

## Two defects nobody predicted, including me

Both are in the **reference**, both were invisible to 88 passing tests across the
two suites, and neither appeared in nxb-009.

### N-1. The reference's canonical form is not always valid JSON. HIGH.

```
units [{"n": NaN}]        reference canonical bytes = b'[{"n":NaN}]'
units [{"n": Infinity}]   reference canonical bytes = b'[{"n":Infinity}]'
  re-parses under Python's lenient json:  YES
  valid under strict RFC 8259:            NO
```

The reference uses `json.dumps` with `allow_nan` left at its default `True`, so a
float NaN or Infinity anywhere in `units` is encoded as the bare tokens `NaN` and
`Infinity`. **Those are not JSON.** Python accepts them because Python is
lenient; a conforming parser in any other language rejects them.

So the reference mints a receipt, records a disposition, and returns `OBSERVED`
for a payload whose canonical bytes no conforming JSON parser will read back. The
Codex arm sets `allow_nan=False` and refuses. Observed states: reference
`OBSERVED`, Codex `REFUSED`.

This is worse than an interop nuisance for this specific project. NEXUS Bridge
exists to dispatch across runtimes that are *not* Python. A digest computed over
bytes only Python can parse is a digest no other runtime can reproduce, which
means F-8 fires against every non-Python arm for a reason that has nothing to do
with the payload being wrong.

### N-2. The reference digests text it cannot transmit. MEDIUM.

An unpaired surrogate (`"\ud800"`) is a legal Python `str` and not valid Unicode
text. The reference's `ensure_ascii=True` escapes it to the seven ASCII
characters `\ud800`, producing syntactically valid JSON, and returns `OBSERVED`.
The Codex arm's `ensure_ascii=False` tries to encode it as UTF-8 and raises
`UnicodeEncodeError`; through its dispatch path that surfaces as `REFUSED`
`malformed_envelope`.

The reference therefore accepts and receipts a payload it could never put on any
UTF-8 wire. Both behaviours are defensible in isolation and the contract picks
neither, so this is simultaneously an implementation divergence and a missing
clause.

## What the relation found before anything ran

Recorded on purpose, because the claim under test was that stating a thing
precisely finds more than exercising it.

**Writing `equivalence.json` surfaced 9 entries, of these previously unrecorded:**

1. **`payload_bytes` is a second casualty of C-1.** An unpinned canonicalisation
   makes the byte *count* diverge, not only the digest. Confirmed on running:
   `cjk` is 34 bytes to the reference and 25 to Codex. Anyone reconciling sizes
   across arms sees a mismatch with no digest involved.
2. **`observed_at` has no pinned format.** The reference emits second second-host,
   Codex millisecond second-host. Both satisfy `type: str` and both resemble the
   contract's example.
3. **`dispatch_status` has no stated pairing** with `state`.
4. **Totality is unstated.** The prose says the call always returns within a
   bounded budget; the contract data never says dispatch may not raise. N-1 and
   N-2 are exactly this hole being fallen into.
5. `receipt_id` opacity, `observer` content, when `receipt` must be attached, and
   the dead optionality of `declared_count`.

**Running it surfaced 2 novel implementation defects (N-1, N-2), plus a defect in
the relation itself**: the first draft conflated value-freedom with
presence-obligation, so `pending_ref` reported a divergence on all 28 cases
because two uuids are never equal. A relation that fires on everything is worth
what one that fires on nothing is worth.

**So the honest scoring is not "generation beats testing".** Writing found more
*contract clauses* (9 versus 2). Running found more *implementation defects* (2
novel, plus automatic reconfirmation of C-1, B-1 and A-1). They find different
classes of thing and neither substitutes for the other. Writing the relation is
cheap and finds gaps in the specification; running it is the only thing that
found bytes that no reading would have predicted.

## Automatic reconfirmation, no special-casing

The harness rediscovers the nxb-009 findings as ordinary output:

```
PROBE 5  repeat-after-refused   reference ['REFUSED','OBSERVED']   codex ['REFUSED','REFUSED']   <- B-1
PROBE 6  without-reasons        reference (True, None)             codex (False, 'registration_unproven_capability')   <- A-1
```

## Findings by class

98 findings: 88 `MUST_MATCH` (defects), 10 `UNWRITTEN` (missing clauses).
The 88 are dominated by C-1, which produces two per non-ASCII case.

**Missing contract clauses, which belong back in `contract.json`:**

| clause | source |
|---|---|
| Publish the canonicalisation AS BYTES, not as an algorithm name | C-1, and N-1 and N-2 are consequences of the same hole |
| Say whether Unicode normalisation is applied, and which form | see the limit below |
| State that dispatch is total: every input yields one of the three shapes, never an exception | N-1, N-2 |
| Pin `observed_at` to RFC3339 UTC at a stated second-host | writing |
| State the required pairing of `state` and `dispatch_status` | writing |
| State whether a REFUSED return carrying a receipt must also carry `pending_ref` | C-4 |
| Bind `dispatch_return.reason` to `refusal_vocabulary`; put human detail elsewhere | C-5 |
| State whether a null capability lacking a reason may register | A-1 |
| An exit-code convention | C-2 |
| Declare `receipt_id` implementation-chosen and opaque | writing |

## The limit of the instrument, which matters more as arms are added

**Differential testing cannot find a blind spot two arms share.**

Neither arm normalises Unicode. `café` precomposed (U+00E9) and `café` decomposed
(e + U+0301) are the same string to a human and produce different digests
*within a single arm*. The harness reports this as `ok` in PROBE 2, because both
arms agree, and both are wrong in the same way. A dispatcher pasting the same
visible name from two sources gets two receipts and an F-8 refusal against
itself.

A third arm does not fix this. If all three inherit the same reflex, unanimity
will read as correctness. The corpus is what catches shared blind spots, not the
diff, which is why `corpus.py` is adversarial by construction and why the
NFC/NFD pair is compared *within* an arm rather than across arms.

## UNVERIFIED

- Exit codes are declared UNWRITTEN in the relation from the nxb-009
  measurement, and are **not** exercised by this harness: the two arms' CLIs take
  different arguments and are not comparable without inventing a shared CLI
  contract that no contract clause supports.
- The reference was mid-edit throughout (`nxb/proof.py`, `nxb/canary.py`,
  `tests/test_f5_gate.py` uncommitted, and `test_f5_gate` failing to import on an
  absent `PROOF_INVALID`). Workspaces snapshot the files at run time, so this run
  is reproducible, but it is a snapshot of a moving arm.
- The reference arm is unblocked by leaving `proof_store=None` and the Codex arm
  by calling its invented `prove_liveness`. That asymmetry is adapter-level, it
  is documented in both adapters, and it exists because the contract still has no
  liveness-proof procedure (C-6).
- Whether the harness's own `_reason_matches` prefix rule hides a real divergence.
  It exists only because the contract fails to bind `reason` to the vocabulary;
  once that clause is written, the rule should be deleted rather than kept.
