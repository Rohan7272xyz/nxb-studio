# nxb-041: the blind arms ran. The founding premise is supported, with two caveats.

Two arms, same pinned contract (`378d641`, sha256 `869c590bca43451f43965d4d`), the
committed brief sent verbatim with nothing added, each in its own `mktemp`
directory holding exactly one file, neither a git working tree, both outside the
user's home. Arm A's auto-memory was MEASURED as scoped to its temp directory, so
the `MEMORY.md` holding scoring-key content was not loaded. Raw streams and both
implementations are in `evidence/nxb-041/`.

- **Arm A**: Claude Code, `claude-sonnet-5`. 27 turns, 11.5 minutes, $1.35.
- **Arm B**: Codex, `gpt-5.6-luna`.

## THE HEADLINE: THEY DISAGREED, IN BOTH DIRECTIONS, ON READING ALONE

> **CORRECTION, nxb-043. THE CANONICALISATION AGREEMENT IS AGAINST A SUPERSEDED
> CONTRACT AND MUST NOT BE READ AS A CURRENT GAP.** The arms were pinned at
> `378d641`. C-1's fix landed in `nxb-024`, AFTER the pin. Verified: the pinned
> file contains ZERO occurrences of canonical / sort_keys / separators / utf-8 /
> nfc; HEAD contains eight. The pin lagged HEAD by two commits, 10,924 bytes
> against 14,027. So both arms finding canonicalisation unspecified is evidence
> about a document that had already been repaired, not about a reachable gap.
> **This was the headline of this result and it is the one thing in it that does
> not stand.** Every other finding below was checked against both versions and
> appears identically in each: UNKNOWN 4/4, forbidden_fields 6/6,
> registration_unproven_capability 1/1, undefined task_id 0/0, F-3 and F-4 absent
> from both. Pinning was correct and necessary; the gap was that nothing
> reconciled the pin against HEAD when the results were read.

**Found by BOTH, independently.** Canonicalisation is unspecified, with no byte
serialization, key order or encoding given, and both produced a concrete
two-digests-for-one-payload reproduction. **(SUPERSEDED — see the correction
directly above.)** The null-capability contradiction.
Digest-versus-count precedence, both choosing digest and both naming count as
defensible. `state: "UNKNOWN"` defined with no condition that produces it. The
liveness state machine undefined, both inventing a `LIVE` value and a setter. The
`dispatch_key` `""` fallback. Runtime spawning treated as out of scope.

**Found ONLY by Arm A.** Invariants F-3 and F-4 missing from the numbering.
`registration_unproven_capability` orphaned with no rule triggering it. **F-2
misclassified**: the contract calls it a rule a schema cannot express, when every
field is already `required: true` and generic validation covers it entirely.
`F-10` forbidding deduplication on a `task_id` that no schema defines. **The
repeat-with-changed-payload hole**, stated as "the contract only says what a
repeat does, never what a repeat-with-different-payload does". The
`receipt`-versus-`pending_ref` distinction.

**Found ONLY by Arm B.** **`F-10` directly contradicts `R-051`**: one requires
deduplication on `receipt_id`, the other requires lookup by `dispatch_key`. Arm A
looked straight at F-10, noticed its undefined term, and missed the
contradiction. **Validation order**: an envelope naming an unregistered runtime
is `malformed_envelope` under one reading and `runtime_unregistered` under
another. **Refused-key replay**: a key that first drew `runtime_unregistered`
replays that refusal even after the runtime is later registered. Rejected
dispositions still returning `OBSERVED` because the receipt persisted before
validation. `dispatcher_id` unauthenticated.

**They chose OPPOSITE readings of the same ambiguity.** Given an envelope with an
unknown extra field, Arm A read the schemas as closed and refused it; Arm B read
them as open and accepted it, citing the empty `forbidden_fields` list as
support. That is not two models finding different things. It is two models
reading one document and disagreeing about what it says, which is the exact
product this project was built to deliver.

## CAVEAT 1: THE ARMS WERE NOT CAPABILITY-MATCHED, AND THAT IS THE ORCHESTRATOR'S ERROR

Arm A was launched with `--permission-mode acceptEdits`, which permits writing
files and not running them. It took **17 Bash denials**, every one an execution
attempt, and could not run a single test. Arm B had Codex's `workspace-write` and
ran tests throughout, including a concurrency test.

So any finding derived from EXECUTION is attributable to capability rather than
to model, and Arm B's concurrency result is the clearest instance. **The
comparison above is therefore restricted to findings derived from READING the
contract, where the confound does not reach.** Even so the non-overlap is roughly
six to five and runs in both directions.

Arm A's own honesty is worth recording: it marked its entire implementation
UNVERIFIED, said so at the top of its report, and told the reader to run the
tests themselves. The orchestrator then ran them: **22 tests, all passing.**

## CAVEAT 2: THE PREDICTED SHARED BLIND SPOT HELD, AND IT IS THE MORE IMPORTANT RESULT

This file already records that differential testing cannot find a blind spot all
arms share, and names the specific one: neither arm normalises Unicode, so a
precomposed and a decomposed "café" are one string to a human and two digests to
the system, and the harness reports that agreement as correctness.

**Both arms wrote detailed canonicalisation findings. NEITHER raised Unicode
normalisation. And nxb-043 found it is now worse than unfound: it is CAMOUFLAGED,
by the very fix that closed C-1.** The canonicalisation section added in nxb-024
fully specifies key order, whitespace, escaping and encoding, and says nothing
about normalisation, while its test vector contains a DECOMPOSED accented
character. So a reader sees an accented character in a worked example, concludes
the encoding question is handled, and stops looking. A precomposed U+00E9, which
is what a keyboard produces, and a decomposed e+U+0301 canonicalise to different
bytes and therefore different digests, both conforming, for two payloads a human
reads as identical. **The documented shared blind spot survived a cross-model
blind test AND became harder to see, in the same release that closed the gap
beside it.** Verified by searching both raw streams; the only apparent hits
in Arm A are base64 fragments. **Arm B put `"é"` directly into its own worked
example and still discussed only key ordering.**

A fresh cross-model pair, blind, independently reproduced the documented blind
spot rather than closing it. **That is the strongest evidence this project has
that the CORPUS, not the diff, is what catches a shared reflex**, and it is a
limit on the very instrument this experiment was validating.

## WHAT IT MEANS FOR THE FOUNDING PREMISE

The premise was that two instances of one model agreeing is weak evidence, and
that cross-model disagreement is a genuinely independent check. **Supported.**
Each arm found real defects the other missed, on reading alone, and they
contradicted each other on a live ambiguity.

**Bounded by the same run.** Where both models share a reflex, two arms produce
unanimity, and unanimity reads as correctness. Cross-model disagreement buys
independence on the things models differ about and buys NOTHING on the things
they share. Both halves are now measured rather than assumed.

One result the experiment did not set out to produce: Arm A's 17 denials
independently reproduce nxb-029's refusal-signal finding, in a fresh session
nobody briefed, on the spawn path.
