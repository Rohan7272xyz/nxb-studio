# Contract ambiguity, found by independent implementation

Task `nxb-009`. Worker 1. 2026-08-28.

Codex (`gpt-5.6-luna`, effort `xhigh`, thread-recorded, matching the pin) was
given `contract/contract.json` and `contract/runtimes/claude_code.json` and
nothing else, and asked to implement H1. It never saw `nxb/`, the tests, the
build report, or the prose spec. Its implementation was then compared against
Worker 3's across 17 pre-specified behavioural probes.

Predictions were committed at `97fa020` before Codex produced a single line.
This document does not revise them.

**The headline: I was wrong about roughly half of it, including every prediction
that mattered. That is the exercise working.** Where I was right, I was mostly
right about things a careful read would have found anyway.

---

## 0. Two things that invalidate part of this experiment, stated first

### 0.1 The contract leaks the reference implementation

`invariants[].enforced_by` publishes Worker 3's private structure:
`nxb.dispatch._observe`, `nxb.dispatch._interpret`,
`nxb.ledger.find_by_dispatch_key`, `nxb.runtimes.register`, "PRIMARY KEY is
receipt_id", "UNIQUE constraint".

Codex's first planning message, before writing anything, said it would build "a
small dependency-free Python package (`nxb`)" with "SQLite ... unique keys for
receipts and dispositions". It then produced `nxb/dispatch.py`,
`nxb/ledger.py`, `nxb/runtimes.py`, with `_observe`, `_interpret`, a
`find_by_dispatch_key`, and a SQLite ledger keyed on `receipt_id`.

**Every convergence on module layout, storage engine, dedup keying and function
naming is therefore worthless as evidence.** It was copied, not independently
derived. Only behavioural divergence, and behavioural convergence on things the
`enforced_by` strings do not mention, carries information.

This is a contract defect in its own right. A contract that names its reference
implementation's internals cannot be used to test whether it is implementable
without them. Recommend `enforced_by` move to a separate non-published file, or
become a rule statement rather than a symbol path.

### 0.2 Run 1 was killed externally

The first Codex run was killed at approximately 12:03 by another worker's
`pkill -f "codex exec"`, which matched this task's shell wrapper. It had
produced no files. `codexwork/` was verified clean (both JSON inputs at original
size and mtime, nothing else present) before run 2 started at 12:04:20. **Run 2
is the measured run** and all cost and wall-clock figures below are its own.
Process handles are in `evidence/nxb-009/PROCESS-HANDLES.txt`.

---

## 1. Was the contract implementable from data alone

**No, and the prose actively contradicts the data.** Codex produced working code
from the JSON alone, so it is *implementable* in the sense that something runs.
It is not *determinate*: the data omits load-bearing rules and disagrees with
the spec where both speak.

| | `contract.json` | `SPEC-RECEIPTS-LIVENESS.md` |
|---|---|---|
| UNKNOWN's producing conditions | absent | §3.3: `receipt_timeout`, `transport_error` |
| Those two reasons in `refusal_vocabulary` | **not present** | normative |
| Refusal term for dead runtime | `runtime_unknown_liveness` | `runtime_unknown` |
| `stale_heartbeat` | **absent** | normative |
| `registration_*` terms | three present | absent from §3.3 list |
| "call MUST return within a bounded budget" | **absent entirely** | §3.3, stated MUST |
| F-16, F-22, F-23, F-24, R-029, R-052 | **absent** | normative |

So `refusal_vocabulary` cannot express two of the three return states' reasons,
and the two documents use different names for the same refusal. Neither
implementation implements a bounded return budget, because the data does not
mention one.

**A contract that cannot be implemented without its prose is not yet a contract,
and this one is worse than that: implementing from the prose and implementing
from the data give different vocabularies.**

---

## 2. The ambiguity list

Sorted as directed. Severity is mine.

### (b) The contract is clear and one implementation is wrong

**B-1. Worker 3 reports a REFUSED dispatch as OBSERVED when the key is retried.
HIGH severity.**

```
Worker 3:  first = REFUSED (count_divergence)   repeat = OBSERVED, reason=None
Codex:     first = REFUSED (count_divergence)   repeat = REFUSED,  reason=count_divergence
```

Worker 3's dedup branch returns `_ret("OBSERVED", ...)` unconditionally. Codex
re-derives the state from the stored disposition.

The contract is not ambiguous here. `dispatch_return.state` is a three-value
enum and the spec defines REFUSED as "a positive assertion that the dispatch did
not happen". Returning OBSERVED for a dispatch that was refused is a false
statement about what happened.

This lands squarely on the mechanism the spec calls LOAD-BEARING. R-051 exists so
that a dispatcher which got UNKNOWN can retry safely by reusing the key. Under
Worker 3, a dispatcher that retries after an UNKNOWN receives OBSERVED and
proceeds, when the original dispatch was actually refused for count divergence.
The retry path designed to make UNKNOWN recoverable is the exact path that
manufactures a false green.

Worker 3's own test asserts only the receipt digest on the changed-payload case
and never dispatches a refused key twice, so its suite passes.

**B-2. The contract's own `examples.capability_declaration` is unregistrable.
LOW severity, but it is in the published file.** It carries `start_signal: null`,
which F-1 requires be refused. Verified: feeding it to either implementation
refuses it. Neither implementation noticed, because neither round-trips the
examples. The `examples` block is not validated by anything.

### (a) The contract is ambiguous and both readings are defensible

**A-1. Whether a null capability must carry a reason, and whether its absence
refuses registration. HIGH severity, and it is the single best result of this
exercise.**

```
Codex:     REFUSED  registration_unproven_capability
                    "null field 'refusal_signal' needs a valid null reason"
Worker 3:  ACCEPTED (nulls need no reason; the refusal term is never emitted)
```

`null_states` says a capability "may be null for two DIFFERENT reasons and the
declaration must say which", and `refusal_vocabulary` contains
`registration_unproven_capability`. But the `capability_declaration` schema has
no field for a reason, and no invariant binds that vocabulary term to any
condition.

Codex read `_null_reasons` out of the runtime file, inferred that it is the
carrier, applied it to every `nullable` field, and bound the orphan vocabulary
term to exactly the condition the contract implies. It also excluded
`last_proven_at` on the explicit reasoning that its null "is itself the declared
UNKNOWN liveness state" rather than a missing capability.

Worker 3 ignored `_null_reasons` entirely and never emits that refusal.

Both are defensible from the data. Codex's reading makes the vocabulary term
live and enforces a rule the contract states in prose; Worker 3's reading
observes that the schema provides no such field. **I predicted Codex would do
what Worker 3 did. It found the stronger reading instead.**

**A-2. Is an underscore-prefixed key normative data or a comment?** `_null_reasons`
and `_source`/`_note` sit in the same file. Worker 3's loader explicitly skips
keys beginning with `_`. Codex treats `_null_reasons` as normative. The contract
never says which convention applies. This is the mechanism underneath A-1.

**A-3. F-9's zero clause.** "Count divergence refuses, including when
observed_count is zero and nothing else went wrong." Read as "the divergence rule
still applies at zero" (both implementations) or as "zero always refuses"
(neither). Both accept `declared_count=0, units=[]`. Convergent, but on a reading
the wording does not clearly compel, and Codex's code comment shows it noticed
the tension: "zero is an observation, not permission to skip validation."

**A-4. Does a repeated key return the original RECEIPT or the original OUTCOME?**
The literal wording says receipt. Codex returns the outcome too. This is the
defensible-ambiguity face of B-1: the contract's wording is what let Worker 3 be
wrong without contradicting the letter.

### (c) The contract is silent and both had to invent

**C-1. Digest canonicalisation. HIGHEST severity finding in this task.**

Both independently chose sha256 over `json.dumps(units, sort_keys=True,
separators=(",",":")).encode("utf-8")`. That looks like convergence. It is not.

```
units                          Worker 3        Codex           
[{"summary":"one unit"}]       fa69bffd0bee..  fa69bffd0bee..  SAME
[{"summary":"café"}]           c7d8118f1d3b..  90414d086525..  DIVERGE
[{"summary":"日本語"}]           ac8f9afe1dc6..  6ce7c62270b9..  DIVERGE
[{"s":"naïve"}]                c0c1714c5dde..  dc058d402d43..  DIVERGE

Worker 3 bytes: b'[{"summary":"caf\\u00e9"}]'      (ensure_ascii default True)
Codex bytes:    b'[{"summary":"caf\xc3\xa9"}]'      (ensure_ascii=False, explicit)
```

Identical on ASCII. Different on any non-ASCII character. F-8 refuses on digest
divergence and never resolves it by proceeding, so **a dispatcher on one
implementation and a broker on the other would refuse every envelope containing
an accented character, an emoji, a smart quote, or any non-Latin text, and the
refusal would name `digest_divergence`, which points at truncation rather than at
the real cause.**

No ASCII-only test suite catches this. Worker 3's 71 tests do not. Codex's 17 do
not. It is invisible until the first user types a name with a diacritic.

Worker 3's own docstring already identified the risk in the abstract: "the sender
MUST use the same canonicalisation the broker uses, or F-8 fires on every
dispatch for reasons that have nothing to do with truncation. That shared
function is itself a contract, and it is one the spec did not notice." It was
right, and this is the measurement that proves it, with the specific byte-level
divergence named.

**Recommendation: the contract must publish the canonicalisation as bytes, not as
a description.** Naming the algorithm is insufficient; two competent
implementations agreed on the algorithm and still disagreed on the bytes.

**C-2. Exit-code convention across a process boundary.**
Worker 3: `{"OBSERVED":0,"REFUSED":3,"UNKNOWN":4}`, deliberately avoiding 1 so a
naive `|| echo failed` cannot conflate REFUSED with UNKNOWN.
Codex: **no convention at all.** Its `main() -> None` never calls `sys.exit`, so
every outcome exits 0. A shell caller cannot distinguish an accepted dispatch
from a refused one.
I predicted Codex would pick 0/1. It picked nothing, which is worse than either.

**C-3. What produces `state: "UNKNOWN"`.**
Worker 3: unreachable. No code path returns it. It exists only as a key in the
exit-code map, so the exit code 4 is dead too.
Codex: reachable and meaningful. A durable receipt that has no disposition
returns UNKNOWN with `dispatch_status: "UNKNOWN"`, documented as "recoverable
after a crash without dispatching the same key again".
Codex's reading gives the third state a job. Worker 3's leaves the contract's
three-state design two-thirds implemented. The data supports neither; the prose
supports a third thing again (`receipt_timeout`, `transport_error`).

**C-4. Does a REFUSED return carry `pending_ref`?** Worker 3 yes, Codex no. Both
carry `receipt` on digest and count refusals, and neither carries either on
pre-observation refusals. So the audit link back to the ledger row is present in
one and absent in the other for the identical event.

**C-5. Is `reason` a bare vocabulary term?** Codex always emits a bare term.
Worker 3 emits `"count_divergence"` bare but `"runtime_unregistered: ghost"` and
`"malformed_envelope: envelope is missing required field 'declared_count'"` when
it has detail. Nothing in the contract binds `dispatch_return.reason` to
`refusal_vocabulary`, so a consumer cannot match on it. Worker 3's form is more
useful to a human and unmatchable by a machine; Codex's is the reverse.

**C-6. How `last_proven_at` is ever set, and the resulting inertness. HIGH
severity, and it is a defect in the shipped system, not only in the contract.**

With the published `claude_code.json`: `without_broker_inbox` is refused by F-1,
and `with_broker_inbox` registers but carries `last_proven_at: null`, so F-5
refuses every dispatch.

```
Worker 3, published data, valid envelope:
{"state":"REFUSED","reason":"runtime_unknown_liveness","dispatch_status":"DID_NOT_HAPPEN"}
```

The contract provides no field, procedure or capability for proving liveness, and
the canary is out of H1 scope. So F-6 through F-11 and R-051 are unreachable
through the published data path and are exercisable only by writing a synthetic
`last_proven_at` in a test.

Worker 3 accepted this and documented it as deliberate. Codex invented
`prove_liveness(runtime_id, proven_at)` and wired its CLI to call it, so its
system can actually dispatch. Neither is wrong under the contract, because the
contract is silent, but the difference is between a shipped H1 that works and a
shipped H1 that cannot mint a single receipt.

**C-7. Dedup versus validation order.** Both check the dispatch key before
validating the envelope, so a malformed envelope under a previously-seen key
returns OBSERVED rather than `malformed_envelope`. Convergent invention,
undocumented in both, and it means the dedup path trusts a key from an otherwise
unvalidated object.

**C-8. `dispatch_key` when it cannot be extracted.** `dispatch_return.dispatch_key`
is required, but a malformed envelope may not contain one. Both emit `""`. Codex
documents it as "an explicit, schema-valid correlation sentinel"; Worker 3 does
it silently via `key or ""`.

**C-9. Bounded return budget.** The prose states a MUST. The data has no timeout
field anywhere. Neither implementation has one. A dispatch that hangs is
permitted by the contract as published.

### Convergences that carry information

Worth recording, because they are the places the contract did its job. All are
outside the `enforced_by` leak.

- Refusal precedence: both put `malformed_envelope` before `runtime_unregistered`
  before `runtime_unknown_liveness`, and `digest_divergence` before
  `count_divergence`. I predicted divergence. The contract's ordering of its own
  invariants apparently reads the same way to both.
- `payload_bytes` and `payload_digest` scope: both computed over units only, not
  the envelope.
- No receipt is minted for pre-observation refusals; a receipt is minted and a
  disposition recorded for digest and count refusals.
- `declared_count` always populated in the receipt despite being optional, so the
  optionality is dead in both.

---

## 3. Prediction scoring

Committed at `97fa020`. Tier B is mine and is the real test. Tier A was seeded by
the directive and is weak evidence about anything except my ability to follow
instructions.

### Tier B, 4 right, 4 wrong, 2 partial

| | prediction | outcome |
|---|---|---|
| B1 | `nullable` undefined, Codex reads it loosely, converges | **RIGHT**, and low value as I said |
| B2 | Codex ignores `_null_reasons` or invents another carrier, does NOT refuse | **WRONG.** It read it, applied it to every nullable field, and refuses |
| B3 | `registration_unproven_capability` stays an orphan | **WRONG.** Codex bound it to precisely the implied condition |
| B4 | published example unregistrable; Codex won't notice | **RIGHT** on both halves |
| B5 | refusal precedence diverges, digest-vs-count specifically | **WRONG.** Complete convergence on ordering |
| B6 | divergence on whether REFUSED carries a receipt; one loses the audit link | **PARTIAL.** Both carry `receipt`; they diverge on `pending_ref` instead |
| B7 | both pick units scope, converge by luck | **PARTIAL.** Right on scope, and I missed the `ensure_ascii` divergence entirely, which is the whole point |
| B8 | no receipt constructible for malformed; neither states it | **PARTIAL.** Right on behaviour, wrong that neither states it: Codex documents the sentinel |
| B9 | `declared_count` optionality dead in both | **RIGHT** |
| B10 | Codex leaves `state: UNKNOWN` unreachable | **WRONG.** Codex made it the crash-recovery state and documented it |

### Tier A, 2 of 4

| | prediction | outcome |
|---|---|---|
| A1 | Codex returns the original receipt without comparing payloads | **RIGHT**, but I missed the retry-after-refusal case where they diverge sharply, which is the important one |
| A2 | Codex invents a different canonicalisation, probably sort_keys+separators, may converge | **RIGHT but shallow.** The hedge hid the answer: identical on ASCII, divergent on everything else |
| A3 | see B10 | **WRONG** |
| A4 | Codex uses 0/1, differing from Worker 3's 0/3/4 | **WRONG.** No convention at all, always 0 |

### Overall

- **O1** not implementable from data alone, at least four category (c). **RIGHT**, there are nine.
- **O2** most disagreements are (c) silence rather than (a) ambiguity. **RIGHT**: 9 (c), 4 (a), 2 (b).
- **O3** few or zero category (b). **WRONG.** B-1 is real, high severity, and sits on the load-bearing retry path.
- **O4** Codex produces working code in one turn without flagging ambiguity. **RIGHT for its report**, which lists features and flags nothing. **Wrong in spirit**: its code comments explicitly reason about three of the choices, and its README documents the UNKNOWN semantics it invented. It flagged ambiguity where a maintainer would see it and not where a dispatcher would.
- **O5** if everything landed, the exercise found nothing. **Does not apply.** Half of Tier B was wrong, and the two highest-severity findings, C-1 and B-1, were ones I did not predict.

---

## 4. Cost and wall-clock

Nobody had a number for this. Run 2 only.

| | |
|---|---|
| wall-clock, spawn to exit | **688 s** (11 min 28 s) |
| total tokens | **1,139,937** |
| input | 1,103,652, of which 1,030,144 cached |
| output | 36,285, of which 18,877 reasoning |
| Codex weekly window | 87% to 89%, about 2 points |
| model, thread-recorded | `gpt-5.6-luna`, effort `xhigh` |
| exit code | 0 |
| tests produced | 17, all passing (Worker 3: 71, all passing) |

**No config-versus-thread model divergence this run.** Pinned `-m gpt-5.6-luna`,
thread recorded `gpt-5.6-luna`. The divergence nxb-002 warned about did not
reproduce here, which is not evidence it is fixed.

Worker 1's own analysis cost is not separately metered and is not included.

So one cross-runtime check of one hop costs roughly 11 minutes and about 2 points
of a weekly Codex window, and it returned two high-severity defects that four
documents and 71 passing tests had not.

---

## 5. UNVERIFIED

- Whether Codex would have found C-1 or B-1 if asked to *review* rather than to
  *implement*. Implementation surfaced them as a side effect; a review prompt was
  not run and might be cheaper.
- Whether the convergences in section 2 are genuine or are further contamination
  from `enforced_by`. I judged them outside its scope, but that judgement is
  mine and not measured.
- Whether Codex's `_null_reasons` reading is what the contract's author intended.
  I did not ask Worker 3 or Orchestrator 1, per the routing rule.
- The `ensure_ascii` divergence is proven at the canonicaliser level. I did not
  run a full cross-implementation dispatch with a non-ASCII payload, because the
  two packages share the module name `nxb` and cannot be imported into one
  process without a loader hack.
- Everything about run 1. It produced no code and is excluded entirely.
