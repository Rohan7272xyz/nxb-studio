# nxb-019: cold user report

Operator: Worker 2. I did not build any of this code. Active session
12:43:10 to 12:48:37, about **5.5 minutes**.

**I never opened a single `.py` file.** Everything below came from `--help`,
package and class docstrings, `inspect` signatures, error output, and the
contract. That is a real result and it belongs at the top: the system is
discoverable enough that a cold operator can drive it without reading it.

## Contamination declaration

I am not a clean cold user and pretending otherwise would be theatre.

- I audited `contract/contract.json` in nxb-013 and nxb-016, so I already knew
  the envelope, receipt, disposition and dispatch_return field names. A real
  operator would have spent time I did not spend.
- I was told in the nxb-013 brief that repeated-`dispatch_key`-after-refusal
  and repeated-key-with-different-payload are areas of interest. **Findings F1
  and F2 below are in that primed territory.** I did not go hunting for them,
  they fell out of ordinary use, and I say where each one surfaced. Score them
  accordingly.

## What I dispatched

| # | what | result |
|---|---|---|
| 1 | contract's own example envelope, unregistered runtime | REFUSED `runtime_unregistered`, exit 3 |
| 2 | same, registry guessed as a list | raw traceback, exit 1 |
| 3 | same, registry guessed as dict keyed by runtime_id | worked |
| 4 | placeholder digest left in place | REFUSED `digest_divergence`, exit 3 |
| 5 | **repeat of 4, identical, 2s later** | **OBSERVED, exit 0** |
| 6 | 3 units, non-ASCII (Chinese, accents, emoji), nested, correct digest | OBSERVED, exit 0, 250 bytes |
| 7 | **same key as 6, payload edited to fix a typo** | **original receipt returned, exit 0, no warning** |
| 8 | `declared_count: 9` against a 3-unit payload | REFUSED `count_divergence`, exit 3 |
| 9 | required field `dispatcher_id` deleted | REFUSED `malformed_envelope`, exit 3 |
| 10 | same envelope, run from a different working directory | REFUSED again, fresh state |

## Where I stalled, and for how long

1. **No README for the thing you are meant to use.** The only README in the
   repo is `harness/README.md`. ~8s to guess `python3 -m nxb --help`. Minor.
2. **`dispatch --help` documents nothing.** `envelope` is a bare positional
   with no help text; `--ledger` and `--registry` have none either. Nothing says
   whether `envelope` is a path or a JSON string. I guessed JSON string first,
   which is the natural guess, and got a traceback. ~30s.
3. **The registry format is undocumented.** Two guesses: a list of capability
   declarations (traceback) and a dict keyed by `runtime_id` (correct). ~20s.
   Nothing in `--help` or the contract says which.
4. **Finding where my state lived: ~90 seconds, the longest stall.** State
   persisted across separate processes with no `--ledger` given, and
   `find . -newermt` and `git status --untracked-files=all` both showed nothing.
   I eventually found it with `find -name "*.db"`. See F3.
5. **`pending()` and `peek` do not exist.** See F6.

## Findings, worst first

### F1. A changed payload under a repeated key returns the old receipt, silently. Exit 0.

I dispatched a real payload, then did the single most ordinary thing an
operator does: fixed a typo in one unit and re-ran the same command.

```
state OBSERVED, exit 0
receipt_id   rcpt-e2cb5603938a4b40b4032bab3a67e600   (the ORIGINAL)
observed_at  2026-08-28T16:47:06Z                    (the ORIGINAL)
payload_digest 6047852637c98db...                    (digest of the OLD units)
```

No `reason`. No warning. No field anywhere in the response indicating the
submitted payload differed from the one on record. **The operator walks away
believing the corrected work was dispatched. It was not.**

This is contract-compliant. `dispatch_key.doc` says "R-051: a repeated key
returns the ORIGINAL receipt rather than dispatching twice", and that is
exactly what happened. **So this is a gap in the contract, not a bug in the
code.** The contract's repeat rule is silent on payload divergence, and the
operator-visible consequence is a silent wrong success.

Primed: yes, I was told this area was interesting. Surfaced by: fixing a typo
and re-running.

### F2. Retrying a refused dispatch converts it into a success.

Same envelope, same key, two identical invocations 2 seconds apart in separate
processes:

```
call 1:  state REFUSED   reason digest_divergence   dispatch_status DID_NOT_HAPPEN   exit 3
call 2:  state OBSERVED  (no reason)                (no dispatch_status)             exit 0
         same receipt_id, same observed_at
```

The refusal is correct on call 1. On the repeat the stored receipt comes back
as `OBSERVED`, and **`reason` and `dispatch_status: DID_NOT_HAPPEN` are dropped
entirely while the exit code flips from 3 to 0.**

Retry is the most reflexive operator action there is. A system whose stated
purpose is that failures be loud turns a failure into a clean success on the
second press of the up arrow.

Primed: yes. Surfaced by: leaving the contract's own
`PLACEHOLDER_COMPUTED_AT_TEST_TIME` in the envelope and re-running.

### F3. Idempotency is silently scoped to your current directory.

The default ledger is `./.nxb/ledger.db`: a **hidden** directory, **gitignored**,
created relative to **wherever you happen to be standing**.

Consequence, measured: the same `dispatch_key` that returns a cached receipt in
one directory is refused and re-dispatched from another. Two operators in two
shells, or one operator who changed directory, get different answers to "has
this already been dispatched". The R-051 guarantee holds only within a cwd, and
nothing tells you that.

It is also invisible to ordinary inspection: `git status --untracked-files=all`
shows nothing because it is gitignored, and it took me 90 seconds of filesystem
searching to find state I had created myself.

### F4. The alarm cannot fire on the surface an operator has.

`Ledger.undisposed()` is documented "Receipts with no disposition. F-11
violations are visible here." After dispatching real work I called it and got
`[]`.

That is not a bug. H1 records a disposition at dispatch time, so in the only
workflow the CLI can drive **`undisposed()` is structurally always empty.** An
operator who checks the alarm gets a reassuring empty list that carries no
information, and cannot tell that from a genuine all-clear.

Worse for an operator: **the CLI has no command to see it at all.** `nxb --help`
offers `dispatch`, `digest`, `contract`. Reaching the alarm requires dropping
into Python, importing `nxb`, and knowing to construct a `Ledger` against a
path you first have to discover (F3).

Legibility, when you do reach it: `disposition_for()` returns a raw
`sqlite3.Row`, so an operator who prints it sees
`<sqlite3.Row object at 0x108c0f730>`. It is fine wrapped in `dict()`, but you
have to know.

### F5. The CLI raises where the API promises not to.

`Broker.dispatch` docstrings "Always returns one of three shapes, never raises",
and it honours that. The CLI wrapper around it does not. Passing the envelope as
inline JSON, the natural first guess given no help text, produces a raw Python
traceback with internal file paths and line numbers, and **echoes the entire
payload back as a filename**:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '{"dispatch_key":"op-0001","runtime_id":"runtime-a", ... }'
```

exit 1. A list-shaped registry produces a traceback too. Neither says
"envelope must be a path to a JSON file" or "registry must be an object keyed
by runtime_id", which is all either needed to say.

### F6. `pending()` and `peek` do not exist.

The brief instructed me to use them. Neither appears anywhere in the package's
public surface: not in `dir(nxb)`, not on `Ledger`, not on `Broker`, not in
`nxb.ledger`, `nxb.dispatch`, `nxb.receipt`, `nxb.proof`, `nxb.contract` or
`nxb.runtimes`. The nearest real thing is `Ledger.undisposed()`. Flagging it
because the person briefing operators is describing an interface that is not
there.

### F7. Minor: the implementation still emits a token the contract no longer uses.

Every receipt carries `"observer": "nxb-broker"`, hardcoded. `contract.json`'s
example was neutralised to `observer-1` in nxb-016. Not an operator problem,
noted only because it is operator-visible output.

## What was genuinely good, said plainly

- **The refusals are excellent.** `malformed_envelope: envelope is missing
  required field 'dispatcher_id'` names the field. `count_divergence`,
  `digest_divergence` and `runtime_unregistered: runtime-a` all say what is
  wrong in one line.
- **`dispatch_status: DID_NOT_HAPPEN` is exactly right.** It is unambiguous,
  it is the thing an operator most needs to know, and no other system I have
  used in this project states it that plainly.
- **Exit codes are meaningful and consistent**: 0 success, 2 usage error,
  3 refused, 1 crash. I could drive this from a shell script.
- **A malformed envelope recorded nothing in the ledger.** `find_by_dispatch_key`
  returns `None` for it. Refusing before writing is the right order.
- **Non-ASCII worked first time.** Chinese, accented Latin and an emoji in a
  nested payload digested and dispatched with no special handling.
- **`state: OBSERVED` with a `pending_ref` is honest naming.** It says observed,
  not delivered. Given that a transmission ack is not delivery, this vocabulary
  is doing real work.

## Judged against the three things I was told to judge it against

- *A transmission ack is not delivery.* The vocabulary respects this. `OBSERVED`
  and `pending_ref` do not overclaim. Good.
- *This project's failures have all been silent rather than loud.* F1 and F2 are
  silent failures reachable by the two most ordinary operator actions there are:
  press up-arrow and enter, or fix a typo and re-run. The system is loud exactly
  where it refuses and silent exactly where it repeats.
- *A sandbox denial produces no event, so the worker's own claim is the only
  refusal channel.* Not exercised at H1; no spawn happened in this session.

## Blunt verdict

**An operator who did not build this can run it, and can also be silently
lied to by it within two commands.**

The happy path took me under six minutes with no source reading, which is
better than I expected. The refusal path is genuinely well built: clear
reasons, correct exit codes, nothing written on malformed input, and
`DID_NOT_HAPPEN` stated in words.

The repeat path is the problem, and it is the whole point of the system. A
dispatcher that returns a stale success for a changed payload, and converts a
refusal into an `OBSERVED` with exit 0 on retry, fails in precisely the mode
this project was founded to eliminate. Neither failure is announced. Both are
reached by reflex, not by adversarial poking.

I would not hand this to an operator until a repeat that is not byte-identical
to the original says so, out loud, in the response.

## What I did not do

Per instruction I fixed nothing, reviewed no code, and did not open
`docs/SEALED-BUILDER-PREDICTIONS-nxb018.md`. I created and then removed a
`.nxb/` ledger in the repository root; all other artefacts are in scratch.
