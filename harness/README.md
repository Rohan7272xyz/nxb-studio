# Differential harness

`python3 harness/run.py [--json out.json]`

Generates hostile envelopes, runs every declared implementation in its own
process, and diffs receipts and returns **modulo a declared equivalence
relation**. Adding an arm is one entry in `arms.json` plus an adapter.

## The equivalence relation is the deliverable

A naive diff of two receipts reports 100 percent divergence: `receipt_id` is a
fresh uuid and `observed_at` is a wall clock. So a differential harness cannot
exist until someone states which fields may legitimately differ. That statement
is `equivalence.json`. It is not a test fixture. **Every entry in it is either a
contract clause nobody has written yet, or a defect in an implementation**, and
it is sorted that way:

- `MUST_MATCH` divergence is a **defect**. Two conforming implementations must agree.
- `UNWRITTEN` divergence is a **missing contract clause**. It belongs in `contract.json`.
- `FREE` is nondeterminism. A field may be FREE in value and still bound in
  presence: `pending_ref` echoes the free `receipt_id`, so its value is free
  while whether it appears at all is a real contract question.

That last distinction was missing from the first draft and every single case
reported a false `pending_ref` divergence, because two uuids are never equal. A
relation that fires on everything is worth exactly as much as one that fires on
nothing.

## Why a process boundary rather than a vendored rename

Every implementation is a package named `nxb`; two cannot co-import. The
alternative to a subprocess is rewriting one arm's imports, which edits the
artefact under test, so the thing measured stops being the thing that was built.
A subprocess also yields exit codes, which are per-process by definition and
which the contract does not specify, and it is the only approach that survives an
arm written in another language.

## Why isolated workspaces

Each arm is copied **file by file** into its own directory outside the
repository, with a byte-identical copy of the redacted contract. Copying the
tree would carry `.git`, and git history still holds the pre-redaction contract
in full, so a directory made by cloning is not bare. `prove_isolation()` walks
the result including dotfiles and re-scans each arm's contract copy for leaks; it
reports rather than asserts.

## Why the wire is ASCII

Jobs and results cross the boundary as JSON with `ensure_ascii=True`. If the
harness's own transport re-encoded the payload it would mask or manufacture the
exact encoding divergence being hunted. `corpus.py` is pure ASCII source for the
same reason.

## Acceptance test

The harness must find C-1 unaided. It does: `PROBE 1` reports divergent
`payload_digest` for every non-ASCII case, and `PROBE 4` demonstrates the
consequence by having one arm compute `declared_digest` and the other broker it,
which refuses with `digest_divergence`.

## The limit you must not forget

**Differential testing cannot find a blind spot two arms share.** Neither arm
applies Unicode normalisation, so `café` composed (U+00E9) and `café` decomposed
(e + U+0301) produce different digests *within a single arm*. The harness marks
this "ok" because the arms agree. A dispatcher pasting the same visible string
from two sources gets two receipts. Unanimity is not correctness, and a third
arm does not fix this if it shares the assumption.
