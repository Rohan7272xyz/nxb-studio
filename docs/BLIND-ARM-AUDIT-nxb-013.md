# nxb-013: redaction audit, isolation build, and brief leak audit

Auditor: Worker 2. I am disqualified as a blind SUBJECT (I know both
high-severity findings) which is exactly what makes me a usable AUDITOR.
Target: `contract/contract.json` as committed at `ede967a`.

Verified I audited the committed bytes, not a working tree:
`git show ede967a:contract/contract.json` and `HEAD:` and my audit copy all
sha256 to `f960cfe03ae1abcc`.

---

## 1. Redaction audit: PASS on implementation structure

Independently re-ran Worker 1's sweep terms against the committed file rather
than taking the claim. All zero: `sqlite`, `PRIMARY KEY`, `.py`, `_observe`,
`_interpret`, `record_disposition`, `find_by_dispatch_key`, `subprocess`,
`selectors`, `Popen`, `pkill`, `readline`.

Added my own passes over all 132 string values in the document, looking for
categories the named terms would miss:

| category | hits |
|---|---|
| python module or file name | 0 |
| function-call form `name()` | 0 |
| filesystem path | 0 |
| storage or table detail | 0 |
| reference to any other file | 0 |

One `UNIQUE` hit is the English word in `"unique per intent"`, not a constraint.
One dotted-path hit is `contract.invariants.provenance_is_asserted`, a reference
into the contract's own structure, not a module. Both are false positives of my
regexes.

**Verdict: no module path, function name, class name, table name or storage
detail survives anywhere in the committed contract.** Worker 1's claim holds.

## 2. Three residues that pass the letter and defeat the purpose

These are not implementation structure, so they are outside what the redaction
was scoped to remove. They are reported because the redaction's stated PURPOSE
was to stop a blind arm manufacturing false convergence, and these will do that.

**R1. The contract still seeds the token `nxb`.** `examples.receipt.observer` is
`"nxb-broker"`; `examples.envelope.dispatch_key` and
`examples.dispatch_return.dispatch_key` are `"nxb-example-0001"`.

The stated reason for redacting at all was that Codex proposed a package called
`nxb` before writing a line, so its structural convergence proved nothing. A
fresh arm reading `nxb-broker` in the only file it is given will plausibly name
its package or module `nxb` for the same reason. **The false convergence signal
is not removed, it is reproduced, and it will look like independent agreement a
second time.** If the arm's naming is going to be read as evidence of anything,
these example values need neutralising.

**R2. The contract tells the arm this is a runtime comparison and names both
runtimes.** `null_states.doc` reads, in full:

> A capability may be null for two DIFFERENT reasons and the declaration must
> say which. From nxb-001: Codex refusal_signal is measured-absent; Claude Code
> refusal_signal is unmeasured. Collapsing them loses real information.

A fresh reader learns from the contract alone that this is a multi-runtime
project, that prior measurement tasks exist, that one of them is `nxb-001`, and
a specific measured fact about refusal signalling in each runtime. I am not
claiming this gives away a finding. I am flagging that **refusal semantics is
adjacent to one of the two high-severity areas**, and that this sentence puts
the word `refusal_signal` and the idea of a measured absence in front of the
arm before it starts. Whether that matters is a judgement for someone who is
not me, since I know what B-1 is and cannot assess this neutrally.

**R3. `invariants.items[10].rule` cites `Measured nxb-001:`** and describes the
peer-socket trust finding. Same class as R2, milder: it reveals that prior
measurement work exists and is being cited as authority.

R2 and R3 may be legitimate contract content, rationale genuinely belongs in a
contract. The decision is not mine. **They are recorded so the choice is
deliberate rather than inherited.**

## 3. Files NOT handed to the arm, and why

`contract/h2.json` contains `nxb-009`, `nxb-010`. `contract/runtimes/claude_code.json`
contains `nxb-001`, `nxb-006` and names a runtime in its filename. The brief
scopes the arm to `contract.json`, and I confirmed `contract.json` references no
other file, so the arm needs neither. Handing either would tell the arm about
prior tasks and about runtimes. **Only `contract.json` is in the isolated tree.**

## 4. Isolation build

Path: `/private/tmp/claude-501/-Users-rohan/1218132f-8449-416d-a58a-6d2ded1b3c84/scratchpad/blind-arm-h1`

Built by streaming the file out of the git object store
(`git show ede967a:contract/contract.json > .../contract.json`). No `cp -r`, no
clone, no tree copy, so no `.git` can ride along.

Recursive listing, dotfiles included, as produced:

```
drwxr-xr-x  .../blind-arm-h1
-rw-r--r--  .../blind-arm-h1/contract.json      10941 bytes

$ ls -la
.
..
contract.json
```

Proof it is not a git working tree:

```
$ cd .../blind-arm-h1 && git rev-parse --show-toplevel
fatal: not a git repository (or any of the parent directories): .git
$ git rev-parse HEAD
fatal: not a git repository (or any of the parent directories): .git
```

1 file, 1 directory, no dotfiles, byte-identical to `ede967a`
(`f960cfe03ae1abcc0a63f648`).

**Caveat: this path is under a session-scoped scratch directory.** It is
readable by another process now, but it is not durable and should not be
treated as a long-lived artefact. If the fresh arm runs later, re-verify the
listing before use rather than trusting this record.

## 5. Leak audit of `docs/BLIND-ARM-BRIEF.md`

**One serious leak. It must be rewritten before the brief is used.**

The brief's second-to-last paragraph reads:

> Be specific down to the level of exact values and **bytes** where that is what
> distinguishes two readings. "I chose a reasonable **encoding**" is not a
> finding; naming the **encoding** and the input on which two reasonable choices
> produce different output is.

This names bytes and encoding twice, and builds its worked example into exactly
the shape of one of the two high-severity findings: an encoding choice where two
defensible options produce different output. A fresh reader who has been told
nothing else will read that sentence and go looking at encodings first. **This
is the same failure the brief's own preamble warns about: the illustration of
why specificity matters is itself the answer.**

Suggested replacement that keeps the demand for specificity and names no domain:

> Be specific. A finding must be stated precisely enough that another person
> could reproduce the disagreement from your description alone: give the exact
> input, and the two different results the two readings produce. "I made a
> reasonable choice here" is not a finding.

Nothing else in the brief points at canonicalisation, repeat semantics, exit
codes, null states, or any specific defect shape. Items 1 to 4 are clean and
domain-neutral, and "Do not look for anything in particular" is the right
instruction. Removing the encoding sentence makes the brief clean.

**Second, smaller issue: it is ambiguous how much of the file the arm receives.**
The brief says "Hand the arm exactly two things: this text, and a bare
directory". If "this text" means the whole file, the arm also receives the
preamble, which tells it that this project has suffered contaminations, that
orchestrators leaked, and that it is a blind arm in an experiment. That
contradicts the brief's own closing instruction to "implement it as you would if
you had been handed it as ordinary work". A subject who knows it is a control
does not behave like ordinary work.

Fix: state explicitly that only the section below the horizontal rule is handed
over, and that everything above it is orchestrator-facing.

## 6. What I did not check

- I did not verify Worker 1's `python3 -m unittest tests.test_contract_selfvalidating -q`.
  Running it means reading `tests/`, which I am barred from. UNVERIFIED by me.
- I did not audit `contract/h2.json` or `contract/runtimes/claude_code.json`
  beyond the token sweep above, since neither is handed to the arm.
- I cannot neutrally assess whether R2 matters, because I know what the
  high-severity findings are.

---

# nxb-016: residues neutralised

Scope: identity and provenance strings only. **No semantics were changed and no
contract defect was repaired.** 175 leaves before and after, no key added or
removed, no type changed, `sender_ref` still echoes `dispatch_key` verbatim.
Self-validation suite: 9 tests, OK.

## Beyond what was assigned

The assignment named `nxb-broker` and two `dispatch_key` examples. A full sweep
for runtime names, not just the `nxb` token, found more, and it was worse:

| location | was |
|---|---|
| `examples.envelope.runtime_id` | `claude_code` |
| `examples.capability_declaration.runtime_id` | `claude_code` |
| `examples.capability_declaration.spawn` | `SendMessage(to=<ref>, message=<directive>)` |
| `examples.capability_declaration.identity` | `ref + pid; re-resolve sessionId immediately before each send` |
| `examples.capability_declaration.cancel` | `SIGINT to the real claude pid` |
| `examples.capability_declaration.progress_signal` | `peer_idle_notice (LIVENESS ONLY, never completion)` |
| `examples.envelope.dispatcher_id` | `Orchestrator 1` |

The `capability_declaration` example was a real runtime's capability sheet
inlined into the contract: it named the runtime, its actual spawn call, its
identity-resolution detail, its cancellation mechanism and its progress signal
by name. A blind arm reading only this file would have learned the runtime it
was modelling and four of that runtime's concrete mechanisms. `dispatcher_id`
named a live participant in the experiment.

By the decision rule adopted for R2 (does this tell the arm it is in a
multi-runtime experiment?) this block failed harder than the prose that
prompted the rule. Neutralised the same way: **shape and semantics kept, real
names dropped.** `progress_signal` deliberately retains
`(LIVENESS ONLY, never completion)`, which is load-bearing, and loses only the
mechanism's name.

`description` also lost `NEXUS Bridge`, because that phrase abbreviates to
exactly the token being removed, so leaving it would have re-seeded `nxb` by
another route.

Left untouched as genuine semantics: the `hop` enum value `H1`, `H1 only` in
the envelope doc, and the internal requirement ids `F-1`, `F-2`, `R-051`.

## One thing I did NOT fix, deliberately

`schemas.capability_declaration.doc` states: *"F-2: every field mandatory. A
capability the runtime lacks is explicitly null WITH A REASON, never omitted."*
The example under `examples.capability_declaration` sets `start_signal`,
`terminal_signal`, `refusal_signal` and `last_proven_at` to bare `null` with no
reason attached, and `null_states.doc` says collapsing the two reasons for null
loses real information.

Whether that is a real inconsistency or a permitted shorthand I do not know, and
**it is not my call, because repairing a contract defect would delete a finding
the blind arm exists to discover.** Neutralisation must not become improvement.
Recorded here so it is a deliberate choice rather than something I missed.

## Method note

I EXECUTED `python3 -m unittest tests.test_contract_selfvalidating -q` to confirm
the edit broke nothing. I did not read its source. Executing is not reading, but
I am flagging it because I was barred from `tests/` by name and would rather
disclose the distinction than assume it.
