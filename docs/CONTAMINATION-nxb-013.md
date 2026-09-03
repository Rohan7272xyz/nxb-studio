# nxb-013 contamination declaration

Task: nxb-013. Author: Worker 2. **Written and committed BEFORE reading the
redacted contract and before writing a line of implementation.**

I am the control arm: a Claude instance implementing H1 blind, to test whether
what Codex found in nxb-009 came from model diversity or merely from being a
fresh careful reader. That test is only meaningful if my prior knowledge is on
the record first. This is that record. It is deliberately unflattering.

I have spent this entire session inside this project. I am not a fresh reader
and it would be dishonest to present my results as if I were. **Read every
finding I produce against this list.**

## A. What I know from documents I read in full this session

**`HANDOFF.md`** (read completely):

- The directive contract: `task_id`, `target_agent`, `action: spawn`,
  `repo_path`, `summary`, and a self-contained `DIRECTIVE:` body whose first
  line names the HOST.
- The report contract: `task_id`, `status` with the enum
  `COMPLETE | BLOCKED | FAILED`, `summary`, `files_changed`, `commands_run`,
  `evidence`, `risks`, `next_action`.
- That task ids are unique, never reused, and that revisions get `.1`.
- **Rule 1: verify the dispatch landed. The ack is the single most important
  thing this project builds, and the old adapter failed silently 7 out of 7.**
- **Rule 8: watch for false greens. A harness that silently does nothing
  reports a clean pass. Assert the intended action happened, not just that a
  counter incremented.**
- Rule 4: if a stop condition's literal terms do not match what is observed,
  STOP AND ASK rather than judging equivalence.
- Phase 1 is "the ack and the message bus".

**`docs/ADAPTER-AUTOPSY.md`** (read roughly the first 80 lines):

- The old implementation's module list: `parser.py`, `validation.py`,
  `state.py`, `errors.py`, `runtime.py`, `report.py`, `collector.py`,
  `waiter.py`, `runner.py`, `orchestrator.py`, `web_adapter.py`,
  `registry.py`, `routing.py`, `dashboard.py`, `launcher.py`, `cli.py`.
- **`DirectiveDedup.add()`, described as in-memory, per-session, keyed on block
  text.** This is a deduplication concept sitting directly next to the
  `dispatch_key` repeat-handling I am about to be asked to implement, and I saw
  it today.
- The pipeline `execute_directive -> state.check -> create_task ->
  state.register -> spawn_task`.
- That the old design polled a `status.json` file and validated a
  `final_report.md`.

## B. What the nxb-013 brief itself told me before I started

The task message names, in advance, the four areas to exercise hardest. So I am
not discovering that these are the interesting areas:

- a repeated `dispatch_key` whose original dispatch was REFUSED
- a repeated `dispatch_key` carrying a DIFFERENT payload
- digest canonicalisation, including exact bytes for non-ASCII
- what produces state `UNKNOWN`, and the exit-code convention across a process
  boundary

It also told me the reference package is called `nxb`, that H1 concerns
receipts and liveness, that Codex found 15 contract defects of which 2 were
high severity, and the shape of Codex's two wins: binding an orphan vocabulary
term, giving an unreachable state a job, and inventing a missing procedure.
**Knowing the SHAPE of the other arm's wins is the single worst piece of
contamination I carry**, because the cheapest way for me to look impressive is
to go hunting for exactly those three shapes.

## C. Contamination from a source nobody has counted yet

**The nxb-007 amendment handed me this project's real defects as worked
examples.** When Orchestrator 1 asked me to construct planted defects, it
listed archetypes to use, and those archetypes were drawn from this project's
own findings. Two of them matter here:

- "a gate whose condition can never fire (a per-device hourly cap of 30 against
  a table whose rows are bounded by a 7-item catalogue)"
- "an acceptance criterion that a harness can pass without exercising anything"

I then spent an hour building artefacts around exactly those shapes and writing
a key describing precisely how to recognise them.

Set against the git log, which I read while checking the gate and which
contains `F-15 was incapable of firing` and `nxb-009 ratified: the blind test
was not blind`, the conclusion is unavoidable: **I have been trained, this
afternoon, to spot unreachable gates and vacuous acceptance criteria in this
specific contract.** If I now report an unreachable state in H1, that is not
independent discovery and must not be scored as convergent with Codex.

## D. Identifiers I already hold from commit subject lines

Read from `git log --oneline` while verifying the gate, before any contract
access: `F-5` (something about forgery, "fixed by removing the reason to
forge"), `F-15` ("incapable of firing"), `R-050` ("sharpened"). I know these
identifiers exist and I know a one-line characterisation of each. I do not know
their text.

## E. Contamination from my own prior tasks today

- nxb-002: `thread.started` as an ack primitive; the exit-code convention
  0 success / 1 failed / 2 usage error; that a sandbox denial is invisible in
  an event stream; that a queue `exit 0` does not mean delivered. **The
  exit-code convention across a process boundary is one of the four areas I am
  asked to exercise, and I formed strong views on it hours ago.**
- nxb-007: I authored five defect artefacts and their key, including an
  unreachable gate and a vacuously-passing acceptance criterion.

## F. What I do NOT know, to the best of my knowledge

- I have not read `contract/contract.json`, `contract/h2.json`, or anything
  under `contract/runtimes/`.
- I have not read anything under `nxb/` or `tests/`.
- I have not read `docs/SPEC-RECEIPTS-LIVENESS.md`,
  `docs/H1-BUILD-REPORT.md`, `docs/H2-BUILD-REPORT.md`,
  `docs/CONTRACT-AMBIGUITY-nxb-009.md`, `docs/JUDGE-BRIEF.md`,
  `docs/F5-AND-CANARY-REPORT.md`, `docs/RUNTIME-CLAUDE-CODE.md`, or
  `docs/REUSE-ASSESSMENT.md`.
- I have not seen Codex's implementation, its 15 defects, or the reference
  implementation's structure beyond the package name `nxb`.
- I have read `docs/RUNTIME-CODEX.md` because I wrote it, and
  `docs/ADAPTER-AUTOPSY.md` in part.

## G. How I think this should be scored

If my findings overlap Codex's, the honest default is that the overlap is
explained by this list rather than by convergent reasoning, **unless the
finding is in an area section C did not prime me for**. The areas where a hit
would still mean something are digest canonicalisation and the exact byte
handling of non-ASCII input, and the two repeated-`dispatch_key` cases. The
areas where a hit means little are unreachable states and vacuous
verification, because I was handed both this afternoon.

I would rather this task return "the control arm found the same things and here
is why that proves nothing" than have my results quietly inflate a thesis that
has already survived one false validation.

---

## ADDENDUM, added before implementation and before the gate opened

**The two unprimed zones named in section G were disclosed to me in full,
by Orchestrator 1, after this document was first committed.**

The message ruling on my gate report contained this:

> BOTH of Codex's high-severity findings landed in your unprimed territory.
> C-1 is the digest canonicalisation diverging on non-ASCII bytes; B-1 is a
> repeated dispatch_key whose original was REFUSED. [...] I am NOT telling you
> what they are.

The second sentence names both findings by content. The disclaimer that follows
it does not undo the two clauses before it.

Section G designated exactly four areas where a hit by this arm would still
count as independent: digest canonicalisation, non-ASCII byte handling, and the
two repeated-`dispatch_key` cases. **C-1 and B-1 are those areas.** Every zone
this arm could have answered cleanly is now primed:

- the shapes from the nxb-007 archetypes, excluded already
- the shapes of Codex's three wins, disclosed in the nxb-013 brief
- and now the specific content of both high-severity findings

**Consequently this arm can no longer answer the question it was built to
answer.** If I implement H1 now and report a canonicalisation divergence on
non-ASCII input, or a defect in the refused-original repeat case, neither is
evidence of anything. I would be recalling, not discovering, and a reader
comparing the arms later would have no way to tell the difference from the
output alone.

I am recording this rather than proceeding quietly, because proceeding quietly
is the failure mode this whole task exists to catch. The nxb-009 result was
ratified once before anyone noticed the blind was not blind.

I have no view on whether the disclosure was deliberate. It does not matter to
the conclusion.
