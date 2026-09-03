# NEXUS Bridge — Orchestrator Handoff

**Read this first if you are a new orchestrator taking over.** This file plus
`ledger/LEDGER.md` is everything you need. Nothing important lives only in an
orchestrator's context. If you learn something durable, it goes in a file in
this repo in the same turn you learn it, not later.

Owner: Rohan. Started 2026-08-28.

## What we are building

A broker that lets ONE orchestrator dispatch work to agents across DIFFERENT
runtimes at once: Claude Code sessions, Codex sessions, and local agents. Today
each runtime can only orchestrate its own kind.

The goal is NOT throughput. It is **disagreement**. Two Opus instances agreeing
is weak evidence because they share blind spots. An Opus orchestrator and a
GPT-5.5 worker disagreeing is a genuinely independent check. Every design
decision should be weighed against whether it preserves that.

Downstream user: Hokie Transit (`~/downstream-project`, canonical copy on
`ssh second-host`). If this works it replaces the current NEXUS adapter there.

## Standing rules from Rohan

- No em dashes in anything written for him.
- Lead with the artifact. Keep commentary short.
- Ratify or challenge every worker report explicitly.
- He adjudicates anything irreversible or outward-facing. Restrictive rulings
  relayed through a worker may be acted on; permissive ones must come from him
  directly, in his own words.
- Efficiency matters. Do not over-engineer.

## The contract (proven, do not redesign)

This survived 7 tasks across 3 workers on 2026-08-27 without amendment. Reuse it.

Directive fields: `task_id` (unique, never reused; revisions get `.1`),
`target_agent`, `action: spawn`, `repo_path` (absolute, must exist),
`summary`, and a self-contained `DIRECTIVE:` body whose first line names the
HOST. The worker cannot see the orchestrator's conversation. Every path,
precondition and acceptance criterion goes inside the directive.

Report fields: `task_id`, `status` (COMPLETE | BLOCKED | FAILED), `summary`,
`files_changed`, `commands_run`, `evidence`, `risks`, `next_action`.

## Hard-won rules. Each one cost something real.

1. **LIVENESS, NOT ERROR REPORTING, IS THE HOLE.** The existing adapter
   dispatched nothing on 2026-08-27 because it reads a browser DOM and the
   directives were in a terminal, and because it had not run since 2026-06-14.
   Its error paths all work. What is missing is that **no component of NEXUS
   ever asserts that a counterpart exists.** Build a RECEIPT (a signal at the
   moment of observation, before validation, addressed to the dispatcher in the
   dispatcher's own runtime) AND a HEARTBEAT. An ack alone rebuilds the same
   hole with better naming. See `docs/ADAPTER-AUTOPSY.md` for 14 concrete
   vanish points; write the spec against that list, not against a general
   notion of silent failure.
1b. **A CAPABILITY CLAIM IN A MARKDOWN FILE IS NOT A CAPABILITY.**
   `NEXUS PROTOCOL.md` told every orchestrator "the user's local NEXUS adapter,
   watching this chat, detects and validates it". That sentence was false for
   over two months and nothing was positioned to notice. "Runtime X can receive
   a dispatch" must be a MEASUREMENT the broker takes, not a sentence someone
   wrote. This is the strongest argument for the Phase 0 discipline.
2. **READ BEFORE YOU SPECIFY.** The orchestrator's error rate is driven almost
   entirely by writing acceptance criteria against systems it has not read.
   Seven wrong facts went into directives on 2026-08-27. A 30-second `grep`
   prevents an hour of worker time.
3. **"A worker caught it" and "a worker propagated it and reported honestly"
   are different reliability properties.** The second is far more common and is
   NOT a safety net. Log them separately or you will believe your specs are
   being reviewed when they are mostly being executed.
4. **If a stop condition's literal terms do not match what a worker observes,
   it must STOP AND ASK, not judge equivalence.** The mismatch is itself the
   signal that the plan's model is wrong.
5. **Source-label every fact handed to a worker**: read directly, claimed by a
   named worker, or stated by the user. Facts degrade across orchestrator
   generations otherwise.
6. **Ask for the disproof, not the confirmation.** Write criteria a worker can
   fail. "Prove it in the simulator, not by reasoning." "Mark anything you
   could not verify UNVERIFIED rather than omitting it." A worker that cannot
   fail your criteria has not tested anything.
7. **Confirm scope is frozen before spending an unrecoverable resource.** A
   build number was burned on 2026-08-27 by pre-staging a binary while scope
   was still open.
8. **Watch for false greens.** A harness that silently does nothing reports a
   clean pass. Assert that the intended action actually happened, not just that
   a counter incremented. This caught real problems four times in one day.

## Worker roster

`Worker 1`, `Worker 2`, `Worker 3` are standing panes, addressed by name via
`ListAgents` / `SendMessage`. They persist across tasks and keep context.
A pane CANNOT clear itself; `/clear` is typed by Rohan. Ask him, and say why.

Use a second or third pane only when work is genuinely independent. Leaving a
pane idle is a valid outcome.

## Phase plan

**Phase 0 (current): discovery, not specification.** The orchestrator's weakest
position is specifying against systems it has never observed, and this project
is exactly that. So workers establish ground truth empirically FIRST and the
orchestrator writes directives only against measured facts.

Phase 1: **receipts and liveness across THREE transports** (see below), plus a
message bus. Phase 2: adapters per runtime.
Phase 3: identity and provenance. Phase 4: permission boundary (Rohan designs
this, not the orchestrator — a broker that routes between sandboxes can launder
a refusal).

## Files

- `HANDOFF.md` — this file. Successor orchestrator brief.
- `ledger/LEDGER.md` — live task ledger. Updated on every dispatch and ratify.
- `docs/` — findings that outlive a task.
- `evidence/` — worker-produced proof.

## THERE ARE THREE TRANSPORTS, NOT ONE

The word "transport" hid two of three from both the orchestrator and the worker
who first used it. They fail in completely different ways, so **a receipt is
required at each one separately.** A design that acks only the first rebuilds
the hole. SOURCE: nxb-004, measured; corrects nxb-003's own earlier claim.

| | transport | mechanism | how it fails |
|---|---|---|---|
| A | orchestrator ingress/egress | browser DOM (`web_adapter.py`) | **silently** — nobody listens |
| B | worker spawn | local process + tmux + `$PATH` (`runner.py`) | loudly, at tmux |
| C | report return | filesystem shared with the worker (`runtime/collector/waiter`) | polls a directory forever |

Layers 1-4 and 9 are genuinely independent of all three. Layers 5-6 ARE
transport B. Layers 2, 7, 8 assume the worker writes files to a path the broker
can read, which is transport C and which nobody had named.

**The seam is already a process boundary with a JSON contract.** The browser
transport does not import the core, it subprocesses it: `python -m nexus
execute-directive` and `python -m nexus collect-report`, each returning one JSON
object on stdout. Measured: exactly one Playwright import exists, inside a
function body; the whole tree imports clean on a machine without Playwright.

**Trap in the spawn seam:** `spawn_task` runs `which(agent_command)` ABOVE the
adapter (`runner.py:475-486`), so any remote-runtime adapter is rejected because
the binary is not on the broker's PATH. ~10 lines, but do not plan as if the
seam is finished.

**No orchestrator, origin or host field exists anywhere in the task model.**
Multi-orchestrator isolation is only "hand each adapter a different --tasks-dir".
Two orchestrators sharing a tasks root collide on task_id.

## A PUBLISHED CONTRACT MUST VALIDATE ITSELF

The single most reusable thing in the old codebase is not code. Their CLAUDE.md
rule 3 requires a test that renders the PRODUCTION prompt template and validates
it with the PRODUCTION validator, so the two cannot drift.

Generalize it: **a broker that publishes a contract must have a test that runs
its own published contract through its own validator.** One cheap test. It
closes the exact class of failure that started this project, where
`NEXUS PROTOCOL.md` asserted a capability for two months after it stopped being
true. SOURCE: nxb-004.

## FOUR HOPS, AND DISPATCH MUST BE A CALL THAT RETURNS

nxb-005 refined the three transports into four hops: **H1 dispatch** (dispatcher
to broker), **H2 spawn** (broker to runtime), **H3 report** (worker to broker),
**H4 deliver** (broker to dispatcher). H1 and H4 shared one channel in the old
design, so a failure to READ suppressed the failure REPORT. They must be
separable.

**Three signals, never one.** RECEIPT (at observation, BEFORE any parsing, no
verdict) then DISPOSITION (after validation) then OUTCOME. The receipt's
defining property is negative: **it must be emittable for a payload the receiver
cannot understand.** If emitting it requires parsing, it is a disposition
wearing a receipt's name.

**THE MECHANISM, and this is the thing that actually closes the hole.** A
receipt you can ignore is a log line. On 2026-08-27 the protocol already said
"verify the dispatch landed", the orchestrator followed it, and it still took
40 minutes. So blocking must be MECHANICAL, and the evidence for how is already
in that day: **hand-delivery succeeded 7 of 7 while the adapter failed 7 of 7,
and the difference was call-versus-emit.** `SendMessage` is a tool call that
returns a result into the dispatcher's context. Emitting a directive as text
into a chat has NO return value at all, so there is nothing to check and no
moment at which checking is forced.

Therefore: **dispatch MUST be a call that returns, never an emission that
hopes.** The receipt belongs in the return value, so the dispatcher physically
cannot proceed without it entering context. This does not depend on anyone
remembering to look. (Caveat from nxb-005: `SendMessage`'s ack is generated
sender-side and may not prove observation. The lesson is the SHAPE, not that
particular signal.)

## THE PRODUCT IS ATTRIBUTABLE DISAGREEMENT, SO PROVENANCE IS PHASE 1

A broker that reliably delivers a dissent you cannot attribute to a known model
that demonstrably did the work has delivered nothing bankable, however good its
receipts are. Two measured findings attack the evidentiary value of a dissent
rather than its delivery: the model a thread RECORDS can diverge from what
config sets, and a sandbox refusal is invisible in the event stream.

**A dissent counts as independent evidence only if pinned == reported AND
reported differs from the dispatcher's own model.** Two instances of the same
model disagreeing is variance, not independence, and the broker must be able to
tell mechanically.

**Vanish point 15, OPEN and unclosable on the measured Codex surface:** a
sandbox-refused action narrated as done. Never infer refusal from prose or from
a clean event stream. Where an effect is externally checkable, check it
independently. Where it is not, the outcome carries `effect_unverified` and
cannot be ratified COMPLETE. **Since this project's product is largely
judgements, that is a significant constraint and it is Rohan's to weigh.**

## SPEC WHAT THE BROKER MUST REFUSE, NOT WHAT IT MUST EMIT

Obligations to emit erode. Refusals do not. The 2026-08-27 failure was not a
missing emission, it was **work proceeding when it should have stopped.**
Two refusal rules already carry most of the weight:
- The broker MUST REFUSE to register a runtime whose start signal is null. Had
  this existed, the browser adapter could not have been registered and the seven
  dispatches would have failed loudly at dispatch time instead of vanishing.
- The broker MUST REFUSE to dispatch when liveness is UNKNOWN. Absence of a
  heartbeat is UNKNOWN, and UNKNOWN blocks. The old failure was fail-OPEN.
**Process liveness is BANNED as a signal.** Two independent proofs: the adapter
was not a process at all, and a hung `codex exec` was alive with zero bytes out.

## CORRECTIONS TO THINGS THIS FILE OR THE ORCHESTRATOR PREVIOUSLY ASSERTED

**1. MCP is a shared TOOL layer, not a shared AGENT layer.** `claude mcp serve`
advertises tools only, no sampling; `prompts/list` and `resources/list` both
return -32601. **An MCP client cannot ask Claude Code to think.** Any plan that
assumed MCP was the cross-runtime agent substrate needs replacing now, not in
Phase 2. It is not useless: `SendMessage` and `ListAgents` are exposed over MCP
and work, so an external MCP client can reach the session mesh indirectly.
SOURCE: nxb-001, measured. This corrects an orchestrator assumption.

**2. `/clear` does NOT change a session's short [ref].** It rotates the
sessionId underneath while ref, pid, socket and name all stay intact.
**A CHANGED REF MEANS THE PROCESS RESTARTED, not that it was cleared.** The
orchestrator inferred the opposite on 2026-08-27 and stated it to Rohan as fact.
Measured on one pid held constant: session 93395b11 became 367f4e3d across a
`/clear` while ref stayed 9be3bf.
**Broker consequence:** a cached sessionId sent after a clear is dropped with
"session_id mismatch", silently. A broker that caches sessionId at dispatch time
will silently 0-for-N every worker cleared since. **Address by ref plus pid and
re-resolve sessionId immediately before each send.** SOURCE: nxb-001, measured.

## THE ACK ALREADY EXISTS. THE BROKER MUST OWN AN INBOX TO RECEIVE IT.

Claude Code's UDS protocol already carries real delivery receipts
(`peer_message_status`: held / denied / expired / delivered / refused / dropped)
and a completion callback (`peer_idle_notice`), both correlated by `msg_id`.

**But the recipient only emits them if the sender's `from` field is a
well-shaped socket path inside its own socket namespace.** A probe sending from
`uds:probe` got nothing, and the recipient logged "hold-receipt skipped: reply
address unshaped or outside our socket namespace".

**A sender that does not bind and listen on its own `/tmp/cc-socks/<name>.sock`
CANNOT BE TOLD THAT ITS MESSAGE FAILED.** That is very likely the exact shape of
the 0-for-7 silence. **Build the broker's own inbox FIRST. It is a precondition
for the ack, not a feature of it.** SOURCE: nxb-001, measured.

Two traps on top of it:
- **`peer_idle_notice` is LIVENESS, not COMPLETION.** `state:"idle"` means the
  recipient's turn ended. It fired at 10.8s on a task still running a 25s
  backgrounded command. Treating idle as done is HANDOFF rule 8 exactly.
- **Getting a message IN is solved; getting output OUT is the hard half —
  BUT ONLY FOR SESSIONS THE BROKER DID NOT SPAWN.** (Qualified by nxb-010.)
  The socket carries control frames only, so reaching an EXISTING session gives
  no content reply channel. A broker that SPAWNS its own `claude -p` child owns
  that child's stdout exactly as it owns a Codex child's. The asymmetry is a
  property of peer-messaging, not of the runtime, and for spawn-shaped work both
  runtimes look the same.

**Diagnostics:** run any session with `--debug-file <path>` and grep
`uds-messaging`. The runtime prints its own socket path, a copy-pasteable socat
injection recipe, and the reason for every drop or hold.

**Socket existence is NOT liveness.** Socket files outlive their processes after
any `-p` run. `connect()` is liveness; a dead one gives ECONNREFUSED.

## PROVENANCE IS ASSERTED, NEVER AUTHENTICATED

A bare Python script with no relationship to Claude Code was received as
"Another Claude session sent a message" with the full peer-trust preamble.
**Anything local that can write to the socket inherits peer trust.** The broker
will be trusted as a peer by every recipient, so **the broker must establish
sender identity itself.** SOURCE: nxb-001, measured.

## FOR ROHAN, PHASE 4: A MEASURED LAUNDERING PATH

`claude mcp serve` executes Bash UNPROMPTED with no permission-mode gate.
`tools/call Bash {"command":"echo ...; id -un"}` returned real stdout as the
user. Verified to be the surface and not local config: settings.json has no
defaultMode and an empty allow list; settings.local.json's 59 entries match
nothing relevant. There is no interactive client, so nothing can prompt.
**Work refused inside a restricted or prompting session can be completed by
shelling out to `mcp serve`.**
The contrast matters: the UDS path DOES enforce permission-mode parity and held
a message into a bypassPermissions session with `cause=no-mode-asserted` pending
human approval. The parity gate is well designed and does not cover this route.
SOURCE: nxb-001, measured. Rohan's to rule on, not the orchestrator's.

## STANDING RULE: NEVER PATTERN-KILL ON A SHARED MACHINE

**Kill only PIDs you hold a direct handle to, from processes you started.
NEVER `pkill -f`, `killall`, or any pattern match against a shared binary name.**

This machine runs several agents at once. On 2026-08-28 a worker cleaning up its
own hung child ran `pkill -f "codex exec"` and reaped ANOTHER worker's blind
cross-check run, because that worker's shell wrapper contained the same string.
Self-reported in two minutes, damage bounded, experiment uncontaminated, but the
cost was real and the mechanism is silent: the victim learns nothing.

**This is also a BROKER requirement, not just worker hygiene.** The refusal that
says "kill a child that misses its start signal" has an obvious implementation
that is a pattern kill, and a pattern kill on a multi-agent host reaps other
tenants' work. F-15 needs the clause: **a broker may only kill processes it
holds a direct handle to, never by command-line pattern.**

## A TIMEOUT THAT CANNOT FIRE IS NOT A TIMEOUT

The same worker's F-15 implementation checked elapsed time between reads and
then called a BLOCKING `readline()` on the child's stdout. Against the measured
Codex stdin trap the child produces zero bytes, so `readline()` blocks forever
and the timeout check never runs again. **The refusal was structurally incapable
of firing against the exact trap it was written for.**

Generalise it: any guard whose check sits after a blocking call in the same loop
is decorative. Guards must run on a clock that the thing being guarded cannot
stop. Use non-blocking IO or a separate timer, never "check, then block".

## A SANDBOX ARGUMENT IS NOT EVIDENCE OF A SANDBOX

Measured on Codex: `--yolo --sandbox read-only` still resolves to
`danger-full-access`. A restricting flag was silently overridden by a hidden
permissive one. **The broker must verify the RESOLVED policy a runtime reports,
never the flags it was handed.** Combined with the measured fact that a sandbox
denial is invisible in Codex's event stream, this means permission posture must
be read back from the runtime and recorded in provenance, or it is unknown.

## MEASURED PROPERTY OF THIS WORKFLOW: THE AUTHOR'S TESTS DO NOT TEST THE AUTHOR

Across nxb-006 and nxb-010, seven refusals "survived contact" and five died.
**Every survivor survived a test written by the same agent that wrote the code.
Every death was found by something else: a hung process, a harness timeout, and
a mistake that damaged another worker's run.** As of nxb-010 the author's own
tests had never once caught one of the author's own refusal defects.

Read "refusals that survived contact" accordingly. Those tests DEMONSTRATE the
refusals; they do not TEST them. Independent implementation (nxb-009) and
hostile conditions are the only checks that have actually worked.

**So scope build tasks to include deliberately hostile conditions.** The two most
valuable findings in nxb-010 came from a hang nobody predicted and from breaking
another worker's work.

## NAME THE PROPERTY THAT WAS VIOLATED, THEN AUDIT FOR THE PROPERTY

An earlier version of this rule said "when you fix a class of bug, grep for the
class". **That rule was falsified in nxb-011.** The worker DID grep, found and
fixed the textual twin, and a THIRD instance still bit: `selectors` reports
readiness per BYTE while `readline` blocks until a NEWLINE, so a partial line
then silence held a 3-second budget for 30 seconds. Grep finds TEXTUAL siblings;
that was a SEMANTIC one.

The property that mattered was **"can a peer block this loop past its
deadline"**, not "does this call readline". Name the property, then audit for
the property.

## TWO MEASURED NUMBERS THAT REPLACE ASSUMPTIONS

- **Codex spawn to `thread.started`: warm median 0.112s, warm max 0.167s (n=6),
  cold 0.685s (n=1).** The spec assumed **30 seconds**, which is 44x to 320x too
  generous. **An over-long start timeout is not free safety margin: it is exactly
  how long a hung spawn holds a slot before the trap is detected.** Recommended
  5s, still [A].
- **F-5's staleness budget remains unmeasured** and a spawn hop cannot produce
  it, because it is a question about going stale WHILE IDLE. Only a canary
  running over days can answer it.

## AN EXPERIMENT COMPARING RUNTIMES MUST CONTROL FOR WHAT THE RUNTIME CAN READ

`MEMORY.md` under `/Users/rohan` holds plain-text answers to questions this
project uses as a scoring key. Claude Code's auto-memory is directory-scoped.
**Run any cross-runtime comparison from an empty directory OUTSIDE the user's
home, and MEASURE that the context is clean rather than assuming it.** An
open-book-versus-closed-book result looks exactly like a real one.

**And always include same-runtime controls.** Cross-runtime pairs alone cannot
distinguish a real difference from ordinary run-to-run variance. Without the
control, "they differed on six of ten" means nothing.

## A REFUSAL THAT PREDATES ITS MECHANISM IS MOSTLY DELETION, NOT REPAIR

F-5 refused to dispatch to a runtime not proven live. It was written before H2
existed. Once H2 gave a real start signal, a dead runtime failed at dispatch in
~0.2s **with a receipt**, and the pre-check stopped being a safety property and
became a cost optimisation. The task scoped as "fix F-5" was mostly removal.

**The corrected liveness rule, replacing "fail closed, UNKNOWN blocks":
FAIL CLOSED ON DISPROVEN, FAIL OPEN ON UNPROVEN, MAKE PROVING CHEAP.**
The 2026-08-27 disaster was not that a dispatch was allowed. It was that its
failure was silent. Once failure is loud, blocking beforehand buys little.

**Generalise:** when a refusal predates the mechanism that makes it checkable,
budget the task as removal.

## A TRIVIAL CANARY IS NOT A CHEAP CANARY

Measured: nine words in, six tokens out, ~12.9k input tokens per run, because
that is what a runtime turn costs before it does anything. Cost is dominated by
the runtime's own system prompt, not the payload. Any design assuming "keep the
canary small" controls cost is wrong. **Run liveness proofs ON DEMAND, never on
a timer:** a 15-minute interval spends ~1.24M input tokens a day whether or not
anyone is working.

**Do not convert tokens to dollars on a plan-auth account.** Consumption may be
plan quota rather than per-token billing. Measure tokens; the price is Rohan's
to apply.

## READ THE CODE AFTER THE HAPPY PATH PASSES

A named step, not a habit. Ask of each feature: **who writes the state this
depends on?** In nxb-011 that found a refusal whose triggering state nothing ever
wrote (the gate was decorative) and a write that silently cleared a stronger
fact (forging a proof lifted a disproof). Two of five findings came from it, and
it has found more defects here than the author's own tests have.

## BLINDING: PHYSICAL ABSENCE, NOT PROHIBITION

Telling a worker not to read something is not a boundary. An agent with a shell
walks up a directory; an agent told to "review these pairs" has an honest reason
to look for context. **And a blocked read produces NO event in the stream**, so
neither the orchestrator nor the worker can tell from a transcript whether a
blind was broken.

**Copy the material a blind arm may see into a bare directory containing nothing
else, outside the repo, and run it there.** Every blinding failure this project
has had was a path rule that an honest reader could walk past.

Corollary: **when you strip a leak, note where it MOVED to.** An implementation
leak removed from a contract went into a file whose name advertises its contents,
one directory away. A future arm must be barred from such files BY NAME, because
a general "do not read tests/" will not stop a worker who greps.

## THE ORCHESTRATOR CAN CONTAMINATE A CONTROL ARM THROUGH AN EARLIER TASK

The control arm for the disagreement thesis had, hours earlier, been asked to
build planted-defect artefacts using archetypes drawn from **this project's own
findings** ("a gate whose condition can never fire", "an acceptance criterion a
harness can pass without exercising anything"). It spent an hour building those
shapes and writing a key for recognising them. It was trained on the answers.

A later brief then named the SHAPE of the other arm's wins, handing it the
cheapest way to look good.

Both were orchestrator errors and neither was counted until the worker counted
them. **A contamination check must cover a worker's WHOLE HISTORY on the project,
not just the current brief.** The mitigation that works: have the arm
PRE-REGISTER, before starting, which findings should count as independent and
which should not, and hold it to that list when scoring.

## THE PARTY THAT HOLDS THE ANSWER KEY MUST NOT BRIEF THE BLIND SUBJECT

The strongest rule this project has produced, and it cost a control arm to learn.

Three separate contaminations reached one blind arm through orchestrator
messages: defect archetypes drawn from the project's own findings (in an earlier,
unrelated task), then the SHAPE of the other arm's wins, then the findings
themselves stated by content. **Every one arrived in the act of explaining why
the blind mattered.** The third came inside a message praising the worker for
protecting the experiment, with a "I am NOT telling you what they are" disclaimer
in the same paragraph as the disclosure. The disclaimer undid nothing.

This is not a failure of care. It is a structural property of the position: an
orchestrator that knows the answer cannot make a brief clearer without leaking,
because clarity and the answer are the same information. **It is the same
laundering shape as the Phase 4 permission problem: the party that knows must not
be the party that briefs.**

**Mitigations, in order of strength:**
1. The brief is MINIMAL and names nothing: no areas to exercise, no severities,
   no counts, no prior findings. See `docs/BLIND-ARM-BRIEF.md`.
2. The brief is COMMITTED BEFORE the arm exists, so it cannot be improved later.
   Improvement is the leak.
3. Someone other than the author AUDITS it for leaks before use.
4. The subject PRE-REGISTERS what would count as an independent finding, before
   starting, and is held to that list.
5. When contamination lands anyway, **the arm is dead — do not discount it.**
   Discounting requires a residual clean zone, and once the findings themselves
   have been named there is none.

## STAGE EXPLICIT PATHS. NEVER `git add -A` IN A SHARED REPO.

Several sessions commit into this repo. An orchestrator running `git add -A`
sweeps other sessions' working trees into its own commits. It happened twice in
one afternoon: a worker's contract redaction landed inside a commit titled
"nxb-011 ratified: delete the freshness budget", and a second piece landed
between that worker's `git add` of explicit paths and its `git commit` seconds
later. **Staging explicit paths does not protect you, because the sweeping is
done by the other side. Only a rule everyone follows fixes it.**

**Consequence that nearly broke a gate: git metadata in a shared repo answers
truthfully about BYTES and falsely about WHO and WHY.** A blind arm gated on
"has the redaction been committed" saw an uncommitted working tree and held —
correctly, but by luck, because the bytes were already committed under someone
else's message. A gate that asks "has task X completed" will get a wrong answer.
Gate on content, never on authorship or commit messages.

## BLINDING MUST COVER GIT HISTORY AND QUOTED EVIDENCE

Redacting a leak from a file at HEAD does not remove it from the repository.
Every earlier revision still contains it: `git show HEAD~5:contract/contract.json`
returns the unredacted original. Analysis documents that QUOTE the old strings as
evidence carry it too.

**So a bare directory copied FROM a clone is not bare if it contains `.git`.
Copy the FILES, never the tree**, and prove isolation by listing the result
recursively including dotfiles rather than asserting it.

## REDACTING A VALUE CAN SILENTLY GUT THE TEST THAT CHECKED IT

A test imported whatever `enforced_by` named and skipped any value not starting
with `nxb.`. After redaction none did, so **the test passed while testing
nothing** — a false green inside the file whose job is proving invariants are
real. When you change the shape of data, check the tests that read it still have
something to read.

**And prove a new guard fires.** The replacement leak-guard was verified by
reintroducing a leak, confirming the suite failed, then removing it and
confirming it passed. **A guard that has never fired is exactly the false green
this project exists to avoid.**

## CONVERT ACCIDENTAL PROPERTIES INTO GUARANTEED ONES

The property audit predicted a blocking hole: a proof pointing at a FIFO, opened
inside the dispatch gate, would hang forever. **The worker TESTED the prediction
before claiming it** and found the code already safe — `os.path.isfile` means
`S_ISREG`, which excludes a FIFO. The author had written it meaning "exists".

**The protection was real and entirely accidental.** A refactor to
`os.path.exists`, which is what anyone would write if they believed the check
meant what its author believed, would have opened the hole silently. It is now an
explicit `stat.S_ISREG` with a comment, and a test that runs the verifier against
a real FIFO in a subprocess whose own termination is the assertion.

That is not a bug fix. **It converted a property that HAPPENED to hold into one
that is GUARANTEED to.** Do that whenever an audit finds you were safe by luck.

And note the discipline: predicting a vulnerability and then testing before
claiming it is the difference between a finding and a fabricated one.

> **CORRECTION, nxb-036. THE GUARANTEE CLAIMED ABOVE WAS TOO STRONG AND THIS
> SECTION WAS WRONG.** A child dispatched through `nxb run` found that the
> `stat` and the `open` were never tied together: nothing fstat'd the handle
> that was actually read. So the conversion held against a STATIC FIFO and not
> against a directory an attacker controls, which can present a regular file to
> the stat and a FIFO to the open. **An accidental property was celebrated as a
> guaranteed one, in the section about doing exactly that**, which is this
> project's founding defect committed by the document written to prevent it.
>
> Now genuinely guaranteed, and by a different mechanism than the one this
> section describes: the path is opened with `O_RDONLY | O_NONBLOCK`, so even a
> FIFO cannot hang the call, and the `S_ISREG` check is an `fstat` **on the
> descriptor about to be read**. A check on the descriptor cannot be raced; a
> check on the path always could be.
>
> The rule survives and gains a clause: converting an accidental property into a
> guaranteed one means checking THE THING YOU WILL USE, not a name that
> currently resolves to it.

## THE PROPERTY RULE BEAT GREP IN A WAY GREP COULD NOT HAVE

The two sites the audit flagged **contain no `readline` and no loop.** They are
`open()` calls. Grepping for the class would have found neither. Cost of the
property method, stated honestly: it produced one false positive, which is why
you test before claiming.

## DELETION HAS EXCEEDED ADDITION TWICE

`nxb-011` was scoped "fix F-5" and was mostly deletion. `nxb-014` was scoped
"wire, then delete": the wiring was one optional callback, the deletion took five
states, three functions, a parameter and half a test file. Once a proof no longer
GRANTED anything, everything that existed to decide whether to trust one was dead
weight.

**If a third build task also deletes more than it adds, invert the project's
default: scope tasks as REMOVAL, and make any addition the thing that needs
justification.**

Related discipline seen twice: **refuse to replace a deleted constant with a new
one.** An automatic retry needs a backoff, a backoff needs a number, and a number
nobody has measured is exactly what these tasks exist to remove.

## NOBODY HAS RUN THIS AS A USER WOULD

Every measurement in this project comes from a script written by the same agent
that wrote the component. **There is no moment where anyone dispatches real work
and gets a result back, because H3 does not exist and the system cannot return an
answer.** Fine as a build order, but it means every claim about ergonomics,
envelope shape and operator experience is untested, and first real use will find
things no audit here can. Close the loop, then have someone who did NOT build it
use it cold.

## THE BLIND SUBJECT'S BRIEF IS A REVIEWED ARTEFACT, NEVER A MESSAGE

The durable rule from four contaminations. **Three of the orchestrator's four
leaks were in prose only the orchestrator had seen, in chat messages. The fourth
was in a committed file, and it is the only one that was caught before it did
damage.**

Being careful did not work. Every leak came from an orchestrator trying to make
something clearer, including one inside the document whose preamble warns that
elaboration is the leak. What worked was that the brief was an artefact a second
party could read.

So: anything a blind subject will see is committed first and audited by someone
else. Never briefed conversationally.

## NEUTRALISATION MUST NOT BECOME IMPROVEMENT

While sanitising the contract for a blind arm, the auditor found a real defect:
the schema doc requires every null capability to carry a reason, and the example
directly below it sets four bare nulls with none. **It deliberately did NOT fix
it**, because repairing a contract defect deletes a finding the blind arm exists
to discover independently. It was one edit from quietly making the contract
better and the experiment emptier.

**Fix defects found during sanitisation AFTER the arm reports, never before.**

## SANITISING FOR A BLIND ARM: CATEGORIES A STRUCTURE-SCOPED REDACTION MISSES

A redaction scoped to "the reference implementation's module structure" left a
real runtime's entire capability sheet inlined in the contract's examples:
runtime name, spawn invocation, identity scheme, cancellation mechanism, progress
signal, and a live participant's name as `dispatcher_id`. **Runtime capability
data is a different category from implementation structure and needs its own
sweep.** Also check that the project's own NAME does not abbreviate to the token
being removed; it did.

**Decision rule that works without knowing the findings** (the orchestrator holds
the key and cannot judge leak-adjacency): ask not "does this leak finding X" but
**"does this tell the arm it is in an experiment?"** That question is answerable
by someone contaminated, and it caught more than the narrower one.

## GAP: NOTHING CROSS-CHECKS THE CONTRACT AGAINST THE RUNTIME DECLARATIONS

Changing `runtime_id` in `contract.json` broke nothing, because no test links it
to `contract/runtimes/*.json`. Expected linkage does not exist.

## "GENERATION BEATS TESTING" WAS TOO BROAD. THE CORRECTED VERSION.

Measured deliberately in nxb-012 because the orchestrator had predicted it.
Writing the equivalence relation down surfaced **9 missing contract clauses**
before anything ran. Running it surfaced **2 novel implementation defects** plus
automatic reconfirmation of three known ones — and a defect in the relation
itself, which fired on all 28 cases until fixed. A relation that fires on
everything is worth what one that fires on nothing is worth.

**They find different classes and neither substitutes for the other. Stating a
thing precisely is how you find what the SPECIFICATION is missing. Only execution
finds what the CODE actually does.** Nobody predicts that a mature implementation
emits invalid JSON, so no amount of writing would have found N-1.

## DIFFERENTIAL TESTING CANNOT FIND A BLIND SPOT THAT ALL ARMS SHARE

The single most important limit of this project's main instrument.

Neither arm normalises Unicode, so a precomposed and a decomposed "café" are the
same string to a human and produce different digests **within a single arm**. The
harness reports that as agreement, because both arms agree and both are wrong the
same way. A dispatcher pasting the same visible name from two sources gets two
receipts and a refusal against itself.

**A third arm does not fix this. If all three inherit the same reflex, unanimity
reads as correctness** — and three-arm agreement is exactly the signal this
project is about to start trusting. **What catches a shared blind spot is the
CORPUS, not the diff.** Keep the corpus adversarial by construction, compare
normalisation pairs WITHIN an arm rather than across arms, and **never retire a
corpus case because all arms agreed on it.**

## GIT'S INDEX IS SHARED STATE. USE PATH-LIMITED COMMITS.

"Never `git add -A`" was not sufficient and the orchestrator's work was swept
into a third worker's commit AFTER adopting it. The reason: `git commit` commits
whatever is in the INDEX, and the index is shared across every session in the
repo. Another session's `git add harness/` followed by your `git commit` takes
their files under your message, even though you staged explicitly.

**The fix is `git commit <explicit paths> -m ...`, which bypasses the index
entirely. Never `git add` followed by a bare `git commit` in a shared repo.**

## MISSING CONTRACT CLAUSES (from harness/equivalence.json, nxb-012)

Do NOT write these into `contract.json` until the blind arm reports; the contract
is under blind test.
1. Publish the canonicalisation AS BYTES, not as an algorithm name.
2. State whether Unicode normalisation is applied, and which form.
3. **State that dispatch is TOTAL**: every input yields one of the three shapes,
   never an exception. Two high-severity defects were this hole from both sides.
4. Pin `observed_at` to RFC3339 UTC at a stated second-host.
5. State the required pairing of state and dispatch_status.
6. State whether a REFUSED return carrying a receipt must also carry pending_ref.
7. Bind `reason` to the refusal vocabulary; detail belongs elsewhere.
8. State whether a null capability lacking a reason may register.
9. An exit-code convention.
10. Declare `receipt_id` implementation-chosen and opaque.

## THE PROJECT DEFAULT IS NOW INVERTED: SCOPE AS REMOVAL

Three build tasks in a row deleted more than they added (nxb-011, nxb-014,
nxb-015). The recorded consequence has triggered. **Additions are now the thing
that needs justification.**

## "CANNOT VERIFY" MUST NEVER BE A REFUSAL. THIRD APPEARANCE OF THIS PATTERN.

F-5 refused 100% of dispatches because nothing was proven live. F-20 is about to
do the same: every Codex outcome carries `effect_unverified: true`, because that
runtime's refusal signal is measured-absent, and F-20 forbids ratifying such an
outcome COMPLETE. Enforced literally it refuses ONE HUNDRED PERCENT of results
forever, for a reason no operator can act on.

**The general rule, learned three times: refuse on VERIFIED FALSE, never on
CANNOT VERIFY. Make verification cheap where the effect is externally checkable,
and record rather than refuse where it is not.** Watch for the fourth instance;
this pattern is the project's most reliable defect generator.

## A RECEIPT ADDRESSED TO A DEAD SENDER IS VACUOUS

The four-hop model says every hop emits a receipt to its sender. **H3's sender is
a one-shot child that is already dead when its report is observed.** The receipt
exists because H4 delivers it, but it is addressed to nobody. The model quietly
assumed all four hops have living endpoints in both directions, and for one-shot
runtimes that is false.

## A TEST FIXTURE THAT RESTATES A CONTRACT VALUE IS A SECOND COPY OF THE CONTRACT

Renaming one example value in the contract broke 26 tests whose fixtures had
hardcoded it. Fixtures drift from the contract exactly the way prose does.
Derive fixture values from the contract; never restate them.

## THE LOOP IS CLOSED FOR THE EASY RUNTIME ONLY

A dispatch can return an answer **for a one-shot child the broker spawns and
owns**. It cannot for an already-running Claude Code session, which has no
content reply channel. The project was founded on an Opus orchestrator
disagreeing with a GPT worker, and **the half not built is the runtime this
project runs inside.**

## FIRST TIME ANOTHER AGENT'S TEST CAUGHT A BUILDER'S WORK

Worker 1's leak guard caught Worker 3's new contract file naming module paths.
Until then, every defect in a builder's work had been found by a hang, a harness
timeout, a mistake, or the builder itself. This is the independence the project
was buying, working for the first time, and it came from a GUARD someone else
owned rather than from a review.

## THE ARTIFACT BEATS THE EXPERIMENT. ALWAYS.

A builder found a serious defect in its own code while writing sealed predictions
about how a cold user would trip over it. Fixing the defect would have made its
own highest-confidence prediction unfalsifiable. **It declined to fix it and
escalated instead of quietly choosing the option that flattered its score.**

The ruling: FIX IT. Two predictions were marked VOID before any result existed,
so scoring stayed clean. **Leaving a known hole in shipped code to preserve a bet
would make this a project that studies false greens while shipping one.**

Procedure when this recurs: void the affected predictions IMMEDIATELY and in
writing, before any result exists; sequence the fix so it does not disturb a
running experiment; never trade the artifact.

## THE DEFECT THAT PROVES THE PROJECT'S OWN THESIS

`units` is carried in the envelope, hashed into `declared_digest`, counted into
`declared_count`, guarded by two refusals — **and never sent to the worker. Only
`body` is.** So the flagship closures of vanish points 5 and 6 detect truncation
of a decoy, while the payload that actually carries the work is unguarded.

A guard that guards nothing, validated and shipped, inside a project about guards
that do nothing. **No test, audit, hostile input, differential run or property
sweep in this project found it.** It was found by writing down what a stranger
would trip over.

## CONFLATED FIELDS BECOME PERMANENT REFUSALS

`effect_unverified` carried two different facts in one boolean: "this RUNTIME
cannot report refusals" (a runtime property, permanently true for one runtime)
and "this OUTCOME's effect was checked and failed" (a per-outcome fact). Sharing
a field wired the permanent one to a refusal.

**Split them.** Runtime properties go in provenance and refuse nothing. Outcome
effect is a three-state UNCHECKED / VERIFIED / FALSIFIED, and only FALSIFIED
refuses. **Whenever a refusal fires 100% of the time, look for two facts sharing
one field before you weaken the threshold.**

## NOTHING CHECKS THAT A VALIDATED FIELD IS EVER READ

The general guard the `units` defect argues for, and it is cheap: assert that
every field the contract carries, validates or guards is actually consumed on a
path that does work. **A guard that finds only the defect it was written for is a
test. One that finds a second is an instrument.**

Minor but real: shadowing a framework internal (a helper named `_outcome` against
`unittest`'s own attribute) produces an error that blames your code for the wrong
thing.

## COLD-USER RESULT: LOUD WHERE IT REFUSES, SILENT WHERE IT REPEATS

An operator who did not build it drove the whole system in 5.5 minutes **without
opening a single source file** — from `--help`, docstrings, signatures, error
output and the contract. That is a real result and it exceeded expectations.

It was also silently lied to within two commands.

- **The most ordinary operator action breaks it.** Fix a typo in a payload,
  re-run the same command: you get the ORIGINAL receipt, the ORIGINAL timestamp
  and the digest of the OLD payload, with exit 0 and no warning of any kind. The
  operator believes the correction shipped. It did not. **And it is
  contract-compliant** — the repeat rule is silent on payload divergence — so a
  code review cannot find it. **The fix belongs in the contract.**
- **Retry converts a failure into a success.** A refusal (exit 3, with a reason
  and DID_NOT_HAPPEN) becomes OBSERVED (exit 0, reason dropped) on the repeat.
  **Pressing up-arrow and enter launders a refusal into a clean success.**
- **Idempotency is silently scoped to the current directory.** The ledger is a
  hidden, gitignored, cwd-relative file. Two operators in two shells disagree
  about whether work already happened. Its longest stall was failing to find
  state it had created itself, because hidden plus gitignored defeats both
  `git status --untracked-files=all` and `find -newermt`.
- **[REVERSED — see below.] The alarm was reported as not legible, not
  reachable, and empty by construction.** That finding was WRONG in its central
  claim and is corrected in "A NEGATIVE CLAIM NEEDS ITS SEARCH STATED WITH IT".
  What survives: the CLI genuinely had no command to reach the alarm at the time
  (since fixed), and `Ledger.undisposed()` genuinely is structurally always empty
  on the H1-only path — but that function was never the alarm.

**Genuinely good, stated without hedging:** exit codes are consistent and
scriptable; a malformed envelope wrote NOTHING to the ledger, because it refuses
before it writes, which is the right order; non-ASCII worked first time;
`DID_NOT_HAPPEN` is the single best thing in the vocabulary; and OBSERVED plus a
pending reference is honest naming, since it says observed rather than delivered.

## ONE CLEAN ROUTE, NOT THREE. (Orchestrator overclaim, corrected.)

The orchestrator wrote that three parties converged independently on the
repeated-key-with-changed-payload hole. **That was overstated and the correction
is measured, not argued.**

- **Builder, reading its own code: CLEAN.** The only independent route.
- **The independent implementation: CONTAMINATED, and worse than assumed.** It
  worked from a contract that had already been ratified as "not blind", and a
  check against `165dfda` confirms its `enforced_by` named
  `nxb.ledger.find_by_dispatch_key` — **the dedup lookup, by function name.** It
  was pointed straight at the repeat path.
- **Cold user: PRIMED.** An orchestrator brief had named
  repeated-key-with-different-payload as an area of interest before it started.
  Its result is real evidence that the hole is reachable BY REFLEX, and weak
  evidence that it is findable INDEPENDENTLY. Those are different claims.

**The defensible statement: one clean route, one contaminated, one primed, all
three landing on the same hole.** The defect stands entirely on its own merits.
The convergence does not.

**General rule: when you count independent confirmations, check each route's
contamination record before counting it.** A sentence like "three parties
converged" survives into a handoff and hardens, and the person best placed to
check a route is never the person whose finding it flatters.

## A CONTRACT FREEZE THAT A HASH ALREADY SATISFIES IS NOT A FREEZE

The contract was held still to protect a blind arm that had not yet been created.
But the arm's input is pinned by sha in an isolated directory, so moving HEAD
cannot affect it. **Freeze the input, not the repository.**

## THE START SIGNAL PROVES A BINARY LAUNCHED, NOT THAT THE RUNTIME WORKS
## (SCOPE CORRECTED: TRUE OF H2's SIGNAL, FALSE OF THE CANARY)

> **DO NOT ACT ON THIS SECTION ALONE.** Its scope is narrowed by
> **"THE DELETABLE THING IS THE CANARY INTERVAL, NOT THE LIVENESS CLAIM"**,
> which is roughly 220 lines further down. The canary runs a full round trip
> and does NOT key on `thread.started`, so the sentence below about a canary
> staying green through an outage is true of H2's receipt and false of the
> canary. Read both before deciding anything about liveness.

The most consequential finding in the project so far, and it invalidates the
liveness design rather than a line of code.

`thread.started` is emitted BEFORE any network round trip. **The evidence is the
timing itself:** a 0.117s median, and a 108KB prompt (770x larger) moving it by
11ms, cannot contain an API call. **The number being fast is the evidence that
the signal is shallow.**

So the start signal proves a binary launched on this machine. It does NOT prove
the runtime can reach its model, that credentials are valid, or that the API is
up. **A canary keyed on `thread.started` stays GREEN throughout exactly the
outage it exists to detect.** Everything built on H2's receipt inherits this.
It belongs in `h2.json` before anything else is built on top.

## IT IS ONE WRONG PATTERN, NOT FOUR BUGS

A fourth blocking instance was found, and it is a WRITE sitting inside the two
correctly-bounded READ loops: `events.write(line); events.flush()`, with no
deadline, on a sink whose volume the peer controls. Measured: 2.0s budget, still
blocked at 15.0s.

**"Assume a fourth" was the right instruction and the wrong long-run one.** The
correct version is "assume one per new I/O call site, forever", because the
pattern is *enforcing a deadline by checking the clock between operations*, which
requires proving every operation between two checks is bounded, forever, after
every edit. It has failed four times in one file, after three fixes, a grep and a
property audit. **What ends the class is a deadline enforced by something that
can INTERRUPT a blocked operation. A fifth audit buys one more instance.**

**And separating questions can hide the answer.** The orchestrator asked about
the blocking class and the uncapped write as two questions. They are ONE defect,
each causing the other: the uncapped write fills the disk, and a full disk is
what makes the write block. Asking separately is very likely what let the author
look straight at that line and classify it as a disk-space issue.

**"A cap needs a number" was the wrong reason to defer it.** Two fixes need no
constant: stop writing once you have the fact you are waiting for, and make the
sink non-blocking. A cap, if still wanted, comes from free space measured at
spawn time.

## A DEADLINE THAT HOLDS WHILE BURNING A CORE

A child that closes stdout but stays alive makes `select` report a closed pipe as
permanently readable, so the loop spins with no sleep: 3.02s against a 3.0s
budget, 2.97s of CPU, 98%. **The deadline holds, which is exactly why the tests
pass.** The peer decides whether the broker sleeps or burns a core, and N
concurrent spawns cost N cores.

## THE ONLY MEASURED NUMBERS ARE THE ONES TO DISTRUST MOST

Being the only numbers in a project is why they get reused as anchors beyond what
they can support. The spawn timings REPRODUCE (n=20, median 0.117 vs 0.112) and
prompt size is measurably not a driver. **But a timeout is a question about the
TAIL, and they were extrapolated from a MEDIAN and a MAX on an IDLE machine.**
Under bounded load the median degrades 1.6x and **the tail degrades 4.7x** — the
statistic extrapolated from is the one that moves least. Cold start under
sustained load lands near 3.2s against a 5s timeout. Untested regime; ~200
samples under contention would settle it.

## KILL DISCIPLINE: THE BAN IS CORRECT AND INCOMPLETE

No pattern kill exists anywhere in the tree; the only occurrences are the
docstring explaining the ban and the test asserting its absence. But the killer
kills ONE process and a runtime is a TREE — no process group, no `killpg`.
Proven orphaning on a synthetic tree; the reviewer's prediction that real
children orphan FAILED twice and it reported that as a failure.
**If a direct-handle kill can leave orphans, banning the pattern kill removes the
remedy without removing the cause, and the next person with a stray reaches for
`pkill` again. Process-group isolation is what makes the ban costless.**

## DETECTION WAS NEVER THE BOTTLENECK

The sharpest organisational finding of the project, and it is about the
orchestrator, not the code.

The repeat-with-changed-payload defect was flagged by the builder in nxb-006 and
not fixed. Flagged again by an independent implementation in nxb-009 and not
fixed. It was fixed only after a cold user hit it by reflex in five minutes.
**Three parties identified it, and the fix came from the one who was not looking
for it.**

Every method here is good at finding things. The orchestrator ratified findings
and did not convert them into work. **A finding that is recorded and not acted on
is indistinguishable, downstream, from a finding nobody made.**

**Consequence: the highest-value build is not a fourth detector. It is closing
the loop from finding to fix.** The mechanism that already worked, and worked on
its first real use, is debt that CANNOT BE PAID QUIETLY: an expected-failure
marker flipped to an UNEXPECTED SUCCESS the moment the fix landed and turned the
suite red until its waiver was deleted.

## TWO INSTRUMENTS, DISJOINT CLASSES

- **The never-read guard** finds fields the code IGNORES. It caught three: a
  payload field that never reached the worker; a declared timeout the dispatch
  path silently overrode with its own default, so a runtime declaring 30 got 5
  and never learned; and dead code, found INDIRECTLY, because **a field read only
  by dead code is a field never read.**
- **The cold-user pass** finds behaviour the CONTRACT PERMITS and an operator
  misreads. It found a defect where nothing is wrong with the code, which is why
  no code-based method could reach it.

Neither would have found the other's catch. Any new instrument should be checked
against that: does it find a class the existing two cannot?

**And the guard's own general observation is the project's founding defect
recurring:** the capability declaration is ten fields of which three are read.
**It presents as configuration and functions as a comment** — exactly the shape
of the protocol document that asserted a dead capability for two months.

**Name your guard's evasions yourself.** This one lists four (reads via variable
key or comprehension, `getattr`, `**kwargs`; readers outside the scanned package;
a renamed validator reclassifying reads; and "delivered wholesale" being a claim
rather than a proof), plus a stale-waiver test so exemptions cannot accumulate
for problems already fixed.

## WITHDRAW THE RIGHT THING

The orchestrator publicly withdrew its praise for the timerless alarm. That was
over-correction. **The DESIGN was right** — an alarm that cannot be silenced by
widening a number beats a timer, and the outbox alarm genuinely can fire. What
was wrong was that the orchestrator briefed an interface from the SPEC rather
than the CODE, and that the one alarm an operator could reach was a different
function that could never fire. **A briefing defect and a reachability defect,
not a design defect. Conflating them costs you a good idea.**

## THE BACKLOG IS 40, NOT 11. AND THE RELAY DROPS FINDINGS.

`FINDINGS.json` at the repo root, enforced by `tests/test_findings_ledger.py`.
**The live counts are in `FINDINGS.json`, printed by the suite on every run.
They are deliberately NOT restated here: a count in prose is a second copy of
data that lives in a file, and this one was already stale within a day (it said
40/33/8/18; nxb-024 made it 41/27/4/0). Same rule as "a test fixture that
restates a contract value is a second copy of the contract".** The
orchestrator's own dispatched list named about eleven.

**The relay itself drops findings, and it did so in the same week the
orchestrator named that as its bottleneck.** The cold-user pass reported SEVEN
findings; FOUR reached the orchestrator's dispatch. Three existed only in
`docs/COLD-USER-nxb019.md`. The orchestrator dispatched from the NUMBERED list in
a worker's message and dropped what was in that message's prose.

**RULE, and it binds the orchestrator, not a worker: dispatch from the SOURCE
ARTEFACT, never from your own summary of it, and never from the numbered list
alone.** The two newest findings in the ledger were produced by reading the
source document instead of the summary of it. That is not an instrument, it is a
habit, and no detector would have found them because nothing was wrong with the
code or the contract.

## FAIL ON THE UNDECLARED, NOT ON THE UNFINISHED

The orchestrator briefed a suite that fails while any finding is unresolved. The
worker refused and was right: **33 open findings at the time made a permanently red suite,
which is a suite nobody reads** — the exact muting failure already watched happen
to a timer, an identity alarm, a liveness gate and a ratification rule.

**OPEN is a valid resting state, provided the finding is OWNED and says what
would close it.** What fails the suite is a finding with no state, no owner, no
`closes_when`, or a record that disagrees with reality. Silence is not a valid
state; unfinished is.

**The clause doing the real work is not the failure, it is that every finding
must say what closing it looks like.** A finding you cannot close is a complaint.
Requiring the closing condition AT RECORD TIME is what converts prose into
something dispatchable.

Ten findings carry an executable predicate. **An OPEN finding whose check PASSES
fails the suite, because the record is lying. A FIXED finding whose check FAILS
also fails, because the fix regressed** — so the backlog doubles as a regression
suite for free. Verified by flipping an entry and confirming the suite goes red.

**Watch the UNOWNED count, not the open count** (both in `FINDINGS.json`; the
unowned count was 18 when this was written and is 0 now). An open finding with
an owner is queued work. An open finding with no owner is the state they were all
in before, wearing a record.

**And this does not fix the bottleneck.** The gap between ratifying and
dispatching is a decision the orchestrator makes, not a record that exists. A
ledger a worker sees at test time does not bind an orchestrator who never runs
the suite. What changed is that the backlog now has a second reader.

## A RATIFIED FINDING IS NOT A VERIFIED ONE

The reviewer's line "a canary keyed on `thread.started` stays green through
exactly the outage it exists to catch" was **true of H2's start signal and false
of the canary.** It had not read `canary.py`. The orchestrator ratified it, and
it became the PREMISE OF THE NEXT TASK.

**Measured: the canary is already deep.** It requires a full round trip plus an
artefact the runtime wrote and the broker did not. Against a dead endpoint:
healthy ok=True 6.3s; API unreachable ok=False `no_output_file` 25.6s. The outage
this was commissioned to catch was already caught.

The real hazard is narrower: H2's STARTED state, its `elapsed_to_start` field,
and any consumer reading "H2 STARTED" as health.

**Guard, cheap and adopted: a worker making a claim about a file must NAME the
file, so the next reader can check it in one command.**

## DEPTH HAS NO MARGINAL COST. THE QUESTION WAS UNANSWERABLE AS POSED.

Measured on both runtimes. Codex: `thread.started` 0.255s and `turn.started`
0.260s are LOCAL (5ms apart cannot be a round trip); `item.completed` 3.293s is
the first post-round-trip event. Claude Code: `system:init` 0.857s is local and
is exactly its `thread.started`; `assistant` 2.255s is the first real one.

**Tokens are spent the instant you dispatch. Waiting for the deep event costs 3.5
seconds of wall clock and ZERO additional tokens. A shallow canary pays the full
price of a deep one and throws the evidence away.** There is no depth-versus-cost
trade, so "is a deep signal worth its cost" could not be answered as asked.

## THE NEGATIVE SIGNAL IS WORTH MORE THAN THE DEEP SIGNAL
## (REORDERED BY MEASUREMENT — THE DEADLINE IS THE LOAD-BEARING FIX. SEE BELOW.)

**Both runtimes announce their own failure within ~0.6s in a machine-readable
frame, and nothing in the design consumes it.** Claude Code:
`{"type":"system","subtype":"api_retry","attempt":1,"max_retries":10,...}`.
Codex: prose in an error event. Consuming it turns a 25.6s canary failure into a
sub-second one. **The deep signal tells you a runtime is healthy in 3.5s; the
negative signal tells you it is NOT in 0.6s, and the second is the case you
actually care about.**

**Neither runtime fails fast or self-terminates.** Codex was still emitting
"Reconnecting... waiting for network" at 60s; Claude Code retried 8 times on a
doubling backoff and was still going at 69s. **Any canary MUST carry its own
deadline; the runtime will not return one.**

## THE DELETABLE THING IS THE CANARY INTERVAL, NOT THE LIVENESS CLAIM

The canary does not compete with nothing. **It competes with the next real
dispatch, which proves the same property better because it carries the real
payload.** Its entire marginal value is early detection during idle periods, and
that value falls to zero as dispatch frequency rises. **Nobody has measured
dispatch frequency** — that is the number to get, and it is the same shape as the
freshness budget that was already deleted. Run it after a measured idle gap, not
on a schedule.

**Caution on the evidence, from the person who produced it:** the outage
simulated was connection-refused — the FRIENDLY outage, fast and unambiguous. The
one that hurts is the SLOW outage, where the API accepts connections and answers
late or never, because that is indistinguishable from a hard task and every
timeout becomes a guess. Not covered, not claimed.

## THE BLOCKING CLASS IS ENDED. NOT INSTANCED AGAIN.

`nxb/deadline.py` fires a breaker from a timer thread. For a child the breaker
kills it, which EOFs the pipes, unblocking any read and breaking any write. **The
loop no longer has to REACH a check in order to be bounded.**

Stated without overclaim, by its author: **this does not make blocking calls
correct, it makes them NON-LETHAL** — which is the property each of the four
one-site fixes provided for exactly one call site.

Measured rather than reasoned: a child that closes stdout and keeps running
burned 61% of a core AND overshot a 4s budget to 6.23s. Now 0% and 4.01s. **The
overshoot had a separate cause, visible only because wall clock was measured too:
the kill path waited three seconds twice AFTER the loop had ended. The function
enforcing the deadline was itself breaking it.**

## GROUP TASKS BY WHETHER A THING IS FIXABLE, DECIDABLE, OR BLOCKED

The orchestrator dispatched "clear the high-severity eight", which treated eight
findings as one kind of work. They were three kinds: **four code defects, three
decisions with no code, one another worker's open question.** Half the items
could not be actioned by the person assigned them. Severity is not a work type.

## THREE OF THE FOUR REMAINING HIGH-SEVERITY FINDINGS NEED A DECISION, NOT CODE

- **W3-9, a sandbox refusal narrated as done: NOT CLOSABLE BY CODE.** No
  implementation can distinguish did-the-work from was-refused-and-narrated-around
  when the runtime emits no event. **It has sat unruled since nxb-002. It is not
  a bug and will never be fixed, so it sits in the backlog looking like debt until
  someone decides it.** It bounds what work this broker may safely dispatch at
  all. Owner: Rohan.
- **W3-10, stale session identity:** blocked on a Claude Code adapter that does
  not exist. Fixing it now means building against an unwritten adapter.
- **W3-11, provenance unauthenticated:** the permission boundary. Rohan's.

## THE LEDGER BECAME LOAD-BEARING ON ITS OWN AUTHOR

Mid-task, two fixes landed and the suite went RED, because the records still said
OPEN while their executable checks now passed. It refused to let the author leave
the ledger stale while moving on. First time the mechanism bound anyone.

## THE BUILD-TO-AUDIT RATIO IS WRONG

Of six findings closed in one task, **four were found by other people's
instruments** — an independent review and the differential arm. **The builder's
own build tasks generated most of the backlog; other people's audits cleared it.**
Its own conclusion: if that pattern holds, this project builds too much relative
to what it audits.

## A NEGATIVE CLAIM NEEDS ITS SEARCH STATED WITH IT

**Reversal of the nxb-019 alarm finding, raised by the worker who made it.**

It reported "`pending()` and `peek()` do not exist anywhere in the package's
public surface". The orchestrator accepted it, said publicly that it had invented
the interface from the spec, withdrew its praise for the design, and wrote an
alarm rule into this file on that basis.

**Both functions existed, at that exact commit.** `977252a:nxb/h4.py` defines
`pending` and `peek`; `977252a:nxb/roundtrip.py` defines `pending`. The file's
own docstring says "Outbox.pending() is the alarm". The orchestrator had named
the interface correctly.

**The cause: a scoped search reported as an unscoped conclusion.** It
introspected a HARDCODED list of seven modules that omitted the two containing
the functions, then wrote an absolute sentence. And it judged the alarm by
testing a different function entirely (`Ledger.undisposed()`), which really is
always empty but was never the alarm. Re-measured: `pending()` returns `[]` when
empty, lists an uncollected outcome, and clears on collect. **It fires.**

**The rule: a NEGATIVE claim must state the search that produced it.** "I checked
these seven modules and did not find it" is checkable in one second. "It does not
exist" is not. This is the same overclaim shape the project has caught repeatedly,
and it was made by the person auditing others for it.

**"An alarm that cannot fire is worse than no alarm" remains a good rule and is
NOT evidenced here.** Attaching a true rule to a false instance is how a rule gets
discredited later.

## A NEGATIVE CLAIM NEEDS ITS SEARCH STATED (VERIFIED, nxb-026)

The reversal filed above was checked independently rather than accepted. At
`977252a`, `nxb/h4.py` line 84 defines `pending()`, line 91 defines `peek()`,
and `nxb/roundtrip.py` line 103 defines `pending()`. The reversal is correct and
the original finding was false.

**One consequence worth stating separately: a fix can land correctly from a
false premise.** The nxb-021 work deleted `Ledger.undisposed()` and exposed the
outbox alarm on the CLI. Both were right. The reason given for doing them was
wrong. That combination reads as confirmation afterwards and is the hardest kind
of error to notice, because nothing fails.

The ledger had nowhere honest to put this: `FIXED` claims a defect existed and
`WONTFIX` claims a real thing was deprioritised. A `REVERSED` state now exists,
requires a reason, and is recorded as finding `LEDGER-1`.

## A CLAIM ABOUT A FILE MUST NAME THE FILE

Claimed as recorded and was not filed until nxb-026 audited for it.

A worker reporting that something is or is not in a file MUST name the file and
the line or section. "It is in the handoff" is not a verifiable statement, and
this project's founding defect is a document that asserted a live capability
for two months with nothing positioned to check it. The same applies to an
orchestrator briefing a worker about an interface: **name the file, or the
claim cannot be checked and will eventually be wrong without anyone noticing.**
This rule exists because an interface was once briefed from a spec while the
code had something else, and because "in the handoff" was said many times in
one day before anybody looked.

## GUARDS SCALE, REVIEWS DO NOT

Claimed as recorded and was not filed until nxb-026 audited for it.

The first time another agent's test caught a builder's defect, it came from a
GUARD that agent owned and had committed, not from a review it performed. A
review catches what one reader notices once. A guard catches the same class
every time anyone runs the suite, including on work its author never saw.
**Prefer building a guard over performing a review**, and when a review finds
something, ask what guard would have found it without a reviewer present.

## HOW TO READ THIS FILE, AND ITS ONE STRUCTURAL HAZARD

Added by nxb-026. Not a rule; a warning about the file itself.

This file is roughly chronological: newest entries are appended at the end. It
is long (77+ sections) and has no index, which is survivable. What is NOT
survivable is that **a later section sometimes corrects an earlier one from
hundreds of lines away, and the earlier section usually still reads as
confident and complete.** A reader who stops at the first statement of a topic
will act on a superseded claim.

Two known instances, both real:
- the start-signal section is narrowed by a section ~220 lines below it, now
  cross-referenced inline;
- the alarm was withdrawn and then partially re-instated, and only the second
  entry ("WITHDRAW THE RIGHT THING") states the position that currently holds.

So: **before acting on any section, search this file for the topic's other
mentions.** The corrections section near the top is not exhaustive; corrections
also live inline where they were written.

## A MEASUREMENT BEATS A SUMMARY. THAT IS NOT A STATEMENT ABOUT RELIABILITY.

**Do not tell a successor "the workers were more reliable than the
orchestrator".** It is false and it teaches the opposite of what this project
demonstrated. Raised by the worker it would have flattered.

The builder introduced most of the defects in this codebase: all four instances
of the blocking class; the payload field that never reached the worker, which
made its own two flagship guards protect a decoy; the dispatch that returned
OBSERVED on a failed spawn; three of the four cold-user findings; the forgery
hole in the proof store; a rule of its own that was wrong; a claim of its own
that was wrong. **Its own measured property, filed here, is that its tests have
never once caught its own defects.**

The orchestrator's errors were mostly DISPATCHING errors: visible in a message,
correctable in a message, corrected the same day. The builder's SHIPPED, and
needed other people's instruments to find.

**The corrections ran worker-to-orchestrator all day for a structural reason:
whoever holds the MEASUREMENT beats whoever holds the SUMMARY, every time,
regardless of who is more careless.** The workers had the reproductions, the
timings and the file contents. The orchestrator had reports of them.

That is the same fact as "dispatch from the source artefact", "a claim about a
file must name the file", and "detection was never the bottleneck". **One fact
wearing four costumes, and it says nothing about either party's reliability.**

**The operational form: ask whoever holds the measurement, and say so plainly
when you hold only a summary.** A successor told the workers are more reliable
will trust worker reports more and check them less, which is exactly backwards.

## A CLAIM ABOUT MUTABLE STATE EXPIRES WHEN IT IS MADE

The companion to "a claim about a file must name the file", and it is NOT the
same rule. Naming the file is insufficient when another agent is editing
concurrently: two `git status` checks minutes apart returned seven paths and nine
paths, and BOTH WERE CORRECT WHEN TAKEN.

**Either a claim about mutable state carries the time it was taken, or the reader
re-checks rather than trusting the snapshot.** An enumeration of a live working
tree is stale before it is read, so a warning that lists paths must tell the
reader to run the check themselves rather than trust the list.

Note the near-miss: this was almost filed as "the worker miscounted", which would
have taught a successor to count more carefully. That was not the failure and
counting harder would not have caught it.

## THE DEADLINE IS LOAD-BEARING. THE NEGATIVE SIGNAL IS AN OPTIMISATION.

**Measured, and it inverts the orchestrator's ordering.** The negative signal was
briefed as the headline and the canary's own deadline as housekeeping.

- **Friendly outage (connection refused): 28.9s to 7.2s.** A 4x gain, NOT the
  sub-second the orchestrator claimed. **0.596s was Claude Code's number**; Codex
  must attempt and fail a connection before it has anything to announce.
- **Slow outage (socket accepts, never answers): the negative signal is worth
  NOTHING.** Codex emits NO error frame at all, because the connection SUCCEEDED
  and it has nothing to announce. The abort can never fire. Over 6 runs the
  result is bimodal: 3 bounded at ~25.5s by the canary deadline, 3 at 5.0s by the
  start-signal timeout, and nothing controls which you get.

**So the deadline is the only thing standing between the canary and an unbounded
wait in the case that actually hurts.** Protecting the announcement path while
treating the deadline as tunable is exactly backwards.

**The detector is STRUCTURAL, not textual, and that is why it holds.** A FATAL
Codex failure is a top-level `type == "error"`; a RECOVERABLE one arrives as
`item.completed` carrying an error item. The fatal/non-fatal split is already
encoded in the envelope shape, so no prose matching is needed anywhere and the
message text is carried as opaque operator detail.

**It FAILS CLOSED:** an unrecognised frame yields no abort and falls back to the
deadline. It can only ever cause an earlier DISPROVEN, never a PROVEN — which is
the property that makes it safe to key a liveness verdict on.

**Open, and honestly flagged by its author:** the canary deadline is 8x ONE
measured healthy round trip. `nxb/h4.py` had refused to add a delivery timer for
exactly that reason, and the author declined to quietly do what that file had
declined to do.

**And the Claude Code half is wired to NOTHING.** `nxb/adapters/` contains one
adapter. The detector is encoded and unit-tested against real captured frames,
and will work the day an adapter exists and not before.

**Tests read the real evidence files rather than hand-typed copies of frames**, so
they stop passing if the runtimes change rather than if someone's memory of them
changes.

## VERIFYING A MEASUREMENT HARD DOES NOT CHECK WHAT IT IS A MEASUREMENT OF

Orchestrator 2's error, caught by the worker whose measurement it was.

nxb-029 measured Claude Code's refusal signal on the SPAWNED-CHILD path:
`claude -p --output-format stream-json`, where the broker reads the child's own
stdout. It then wrote `refusal_signal` and `terminal_signal` onto
`without_broker_inbox` and `with_broker_inbox` in
`contract/runtimes/claude_code.json`. Those two are SendMessage PEER transports.
A peer pane never hands the broker that stream, so neither `permission_denials`
nor `system/permission_denied` is observable there at all.

**The landed file therefore said: the two transports nobody measured have a
refusal signal, and the one transport that was measured has none.** Exactly
backwards, and two genuine UNMEASURED nulls were overwritten in the process.

The orchestrator verified that report before landing it, and verified it hard:
re-parsed all ten evidence files, confirmed the denial-frame counts, confirmed
narration survival at n=2 by reading the model's own output, confirmed zero
false positives across the four non-denial runs, and re-read every frame of the
Codex comparison file. **Every one of those checks passed and every one was
correct.** None of them could catch this.

**The rule: a verification that re-derives the producer's own checks inherits
the producer's own frame.** The orchestrator checked what the worker checked,
harder. It never checked what the worker ASSUMED. Ask what a measurement is a
measurement OF before asking whether it is right, because the second question is
concrete and satisfying and will crowd out the first.

**The detail that makes this worth a section rather than a line:** the
orchestrator wrote the error into its own commit message. `4f05ef3` says
"claude_code.json carries nxb-029's measured refusal_signal and terminal_signal
on the two peer declarations". That sentence IS the defect, stated plainly, by
the person committing it, at the moment of committing it. Narrating a thing is
not noticing it. This is the same shape as the project's founding defect, where
a document asserted a live capability in clear language for two months.

Cheap defence, adopted: **a measurement names the transport or surface it was
taken on, in the field itself**, so attaching it to the wrong subject is visible
in the data rather than only in someone's memory of how it was produced.

Fixed in nxb-033, which reverted both peer declarations to null with reasons
naming the transport and set `spawned_child` from the measurement. Filed as
MEASUREMENT-ATTACHED-TO-WRONG-TRANSPORT for the verification lesson rather than
for the mistake.

## A CLOSED VOCABULARY WITH ONE AUTHOR IS A SINGLE-AUTHOR BRIEF

Raised by the worker who wrote the vocabulary, against their own work.

The orchestrator delegated the design of `REFUSAL_SCOPE` to the worker who held
the measurement, on the grounds that the orchestrator had got the distinction
wrong once already. That reasoning was sound and the outcome is still a closed
vocabulary with exactly one author, who had produced two scoped errors that same
day: an unscoped negative claim in nxb-019 and the mis-attached measurement
above.

**Delegating to whoever holds the measurement is right. It does not remove the
need for a second reader, and the orchestrator's own unfitness to design a
distinction is not a reason to skip reviewing it.** Those are different jobs.
The specific token flagged by its own author as possibly a category error is
`opaque_tool_failure`: the other two tokens are about whether a REFUSAL is
reported, while that one is about whether a FAILURE is visible.

## A RULE THAT BINDS A PERSON DECAYS. A RULE THAT BINDS A FILE HOLDS.

The most useful thing produced on 2026-08-28, and it explains the project's own
history better than any rule already written here.

**Almost every rule this project has adopted binds a PERSON. The ones that have
actually held bind a FILE.** The never-read guard held. The waiver expiry held.
The leak guard held. The findings ledger held, and turned the suite red on its
own author mid-task. Against that: "verify the dispatch landed" was in the
protocol on 2026-08-27, was followed, and still cost 40 minutes. The pattern-kill
ban is a discipline, and it held only because the same task also removed the
reason to reach for `pkill`, which is the point restated.

**Operational form: any rule that cannot be made to bind a file is PROVISIONAL by
default, and you ask of each new rule what its file-shaped version would be.**
Sometimes there is no answer, and then you keep the discipline and mark it
provisional rather than pretending it will survive. Two of the orchestrator's
three sequencing rules have no known file-shaped version. The third did, and it
took 80 lines.

## THE MOVING TREE, AND WHY IT IS A DIAGNOSTIC AND NOT A FAILURE

A red suite in this repo had THREE indistinguishable meanings: a real defect, a
busy machine, and another agent committing mid-run. Three agents write to this
tree. The third was hit twice in one afternoon with a different test failing each
time, and both passed later.

`conftest.py` snapshots HEAD and the dirty set at session start and again at
terminal summary, and prints the difference NEXT TO the verdict: an
UNATTRIBUTABLE banner when the tree moved under a red run, a note that a green
verdict covers no single state, and on any uncommitted file the caveat that the
verdict expires if it is reshaped. It caught a real HEAD move on its first full
run, unprompted.

**It deliberately does NOT fail.** Failing on a moved tree would add a FOURTH
meaning to red, which is the opposite of the point. It is fully guarded and
silent when git is unavailable, because a diagnostic that reddens a suite is
worse than the ambiguity it removes.

Its own stated limit: a change made and reverted within one run is invisible to
it. And it is the highest-blast-radius file in the tree, since it runs on every
pytest invocation by anyone.

## A GUARD PROVEN BY A PROBE THAT COULD NOT HAVE FAILED IS NOT PROVEN

The fourth and sharpest narrowing of "guards scale, reviews do not", and the
whole sequence belongs together because the rule as first written is too
flattering to guards.

1. Guards scale, reviews do not. A review catches what one reader notices once.
2. **Guards scale what someone THOUGHT TO ASSERT.** C14, the most serious defect
   found that day, did not come from the guard. It came from someone asking why
   the guard passed too easily, then writing a new property.
3. **Guards scale their own DEFECTS too.** Three separate guards shipped false
   alarms in draft: a refusal term called `no` harvested from the prose "no
   outcome recorded", an orphan that was really an f-string prefix, and a dirty
   path missing its first character because `git status --porcelain` status pairs
   vary in width (" M", "M ", "MM", "R "). A guard that reports something false
   teaches people to ignore it, which is the muting failure again.
4. **A guard proven by a probe that could not have failed is not proven.** Two
   probes were run and did not fire: one because the run finished in 0.06s before
   the mutation landed, one because passing a path outside the repo re-rooted
   pytest so the conftest never loaded at all. Both were KEPT and reported. A
   lesser report would have said "verified" on either.

All four were produced by the same worker, three of them against their own work,
and each one narrows a rule the orchestrator had been quoting at people.

## AN INTERRUPTED DISPATCH POISONS ITS KEY, AND SAYS THE WORK DID NOT HAPPEN

The first defect found by USING this system for real work rather than by
auditing it, and it was found within one dispatch.

`nxb run` printed its `dispatch_key` before starting work, exactly as designed so
that an interrupted call knows what to retry with. The call was then interrupted
for real, by the caller's own two-minute shell limit, after the child had
launched and run for two minutes.

Retrying with that key returns REFUSED, reason `already_spawned`,
`dispatch_status: DID_NOT_HAPPEN`. Permanently. **The key is poisoned, the work
is unrecoverable under it, and `DID_NOT_HAPPEN` is reported for a child that DID
run and DID spend tokens.**

This sits UNDERNEATH the RT-1 fix rather than contradicting it. RT-1 correctly
stopped a retry from DESTROYING a delivered answer by recording a duplicate-spawn
refusal over it. The case where no answer was ever delivered was then left with
no path forward at all. `--dispatch-key` is documented as "reuse a key to RETRY
safely after an UNKNOWN", and that is now true for one kind of UNKNOWN and false
for another.

Note the shape, which is the cold-user class again: nothing is wrong with the
code, the contract permits it, and the operator is told something false. No
audit, property sweep, differential run or conformance suite in this project
found it, and it took one real dispatch.

## A SOUND FINDING WITH A BAD EXAMPLE IS NOT A FALSE FINDING

Nearly cost this project its best result, and it will recur.

A dispatched child reported that `codex_evidence_verifier` was trivially
bypassable and gave as its example
`{"evidence_path": "/etc/hostname", "runtime_ref": "e"}`. Run on the machine
checking it, that returns **False**, because `/etc/hostname` does not exist on
macOS. The obvious next move is to file the finding as false.

The REASONING was exactly right. Re-tested against files that do exist on the
host: `/etc/hosts` with ref `o` returned True, `/etc/passwd` with `s` returned
True, `/etc/shells` with `e` returned True. It was a total bypass of the only
remaining verification gate, needing no write access and nothing
runtime-specific, and it is now PROOF-1.

**Check the MECHANISM before you dismiss on the INSTANCE.** The cost of doing so
was about two minutes. The cost of not doing so was dismissing a high-severity
defect and, worse, recording that the arm which found it produces false
positives, which would have discounted everything else it said.

This is a general hazard for every arm that reports evidence, and it gets more
likely as arms are given less context: a child that cannot read the host is
exactly the child most likely to cite a path that is not on it. It is the mirror
of "a negative claim needs its search stated": here a POSITIVE claim arrived
with an unlucky witness, and the witness is not the claim.

## THE CLASS THIS SURFACE SERVES, STATED HONESTLY

`nxb run` dispatches a directive to a spawned child and returns the answer. The
class it serves is NOT "self-contained tasks". It is **"self-contained tasks an
orchestrator can assemble from context it already holds"**, and that is
narrower, because somebody has to know which function to inline. Raised by the
worker who built the surface, against their own result.

Measured on the first real dispatch, since the assembly cost is what decides
daily use versus set-piece use:

- Assembling the nxb directive cost about a minute: one shell heredoc, a `sed`
  range to extract the function, and the framing rules. Roughly 60 lines.
- The `SendMessage` directives sent to standing workers the same day ran 800 to
  1500 words each and took substantially longer to write.

**So for a NARROW, self-contained question, nxb assembly is CHEAPER than the
prose message, not more expensive.** That was not the expected answer.

The comparison is not like-for-like and the difference is the point: those long
prose messages went to workers holding deep project context, carrying tasks with
several interacting parts. The nxb directive carried one narrow question to a
child that knew nothing. **The assembly cost scales with how much context the
task needs, not with the transport.** Where a task genuinely needs a page of
project history to state, a spawned child is the wrong recipient and no amount
of cheap assembly fixes that.

The practical rule: reach for `nxb run` when the question can be stated without
the project, and for a standing worker when it cannot. That boundary is
observable before you dispatch, which is what makes it usable.

## TWO SETS THAT MUST AGREE, AND NOTHING MAKING THEM

> **SCOPE CORRECTED.** This section originally claimed THREE findings were one
> class. Two of them are; the third is a different class and the difference is
> practical, not pedantic. See **"MEMBERSHIP DRIFT AND MEANING DRIFT ARE NOT THE
> SAME CLASS"** below. Do not use this section to conclude that a
> set-comparison guard covers a meaning defect. It does not.

Two findings in one day are the same defect wearing different clothes, and
naming the class is worth more than either individually.

- **DECL-1.** `nxb/run.py:ADAPTERS` listed `codex`, and `contract/runtimes/`
  shipped only `claude_code.json`. F-1 therefore refused the runtime, and
  **`nxb run --runtime codex` was dead: half the product unreachable.** Found
  incidentally while checking that a process-group change had not broken the
  real runtimes. Nothing was looking.
- **The vocabulary drift.** Reasons the code emits versus reasons the contract
  publishes: seven emitted-but-unpublished, three orphans. The sharpest case is
  `runtime_disproven` REPLACING the published `runtime_unknown_liveness` in a
  code-side constant rather than in the contract, producing both directions of
  drift in one substitution.
- **The runtime declarations versus the contract.** Recorded earlier as its own
  gap: changing `runtime_id` in `contract.json` breaks nothing, because no test
  links it to `contract/runtimes/*.json`.

**The class: whenever code holds a set that must correspond to a set in data,
something must ASSERT the correspondence, or the two drift silently and the
failure surfaces as a capability that is present and unreachable.** That is this
project's founding defect restated, and it is worth noticing that the founding
defect was never really "a document lied". It was "two things had to agree and
only one of them was ever updated".

The fix shape is the same in all three and it is cheap: a test that enumerates
BOTH sets and asserts the mapping is total in the direction that matters.
`decl1_both_runtimes_are_registrable` is four lines and would have caught DECL-1
the day the CLI learned the name. `tests/test_vocabulary_drift.py` is the same
move for reasons.

**The tell, so the next instance is caught before it ships:** any time you add a
name to a dict, list or enum in code, ask what data has to contain that name for
it to work, and whether anything checks. If the answer is "the person who adds
one will remember to add the other", that is a rule binding a PERSON.

Note also HOW DECL-1 surfaced: not from a test, an audit, a differential run or
a cold user, but from someone verifying that an unrelated change had not broken
something else. **The most-used path hides the least-used one.** Every test and
every real dispatch on this project had used `claude_code`, so the runtime that
was supposedly already working was the one that was dead.

## THE HIGHEST-YIELD DEFECT FINDER CANNOT BE ASSIGNED

Observed by the worker it happened to, counting its own last four defects.

**Three of four came from VERIFYING SOMETHING ELSE**, not from the task in hand:
- **DECL-1**, that `nxb run --runtime codex` was dead and half the product
  unreachable, surfaced while checking that a `start_new_session` change had not
  broken the real runtimes.
- **F3-BYPASS**, that every CLI surface called `abspath` first so the Ledger's
  relative-path refusal could never fire, surfaced when a test for a NEW command
  failed for a reason about the OLD ones.
- **C13's real state**, that an independently-written conformance property was
  still failing for both adapters, surfaced from re-checking a fix believed
  complete.

That is a better yield than any instrument this project has built, and the
instruments are good. **But it is not a technique anyone can be assigned.** It
only happens when the person changing something checks the things they did not
change, and a directive saying "also check unrelated things" produces
box-ticking rather than the thing that works.

The nearest assignable form, and it is weaker: after a change lands, run the
paths the change did not touch and say what you observed, not whether it passed.
The DECL-1 case is the argument, because "the tests pass" was TRUE the whole time
the codex runtime was unreachable. Nothing tested it.

## A RECORD NOBODY CAN REWRITE BEATS A MESSAGE NOBODY RE-READS

A sequencing instruction arrived AFTER the commit it governed. Two workers'
findings had already ridden along in someone else's commit, unattributed, which
is precisely what the never-sweep rule exists to prevent.

Rewriting shared history was correctly rejected, because other sessions commit on
top of it. **The attribution was recorded as DATA instead:** the findings
themselves now carry `_authored_by`, `_landed_in` and `_landing_note` naming the
real authors, their tasks, and why they rode along.

The general form, and it is the file-versus-person rule applied to provenance: a
commit message is read once, by whoever reads that commit. A field on the record
is read by everyone who ever touches the record. **When you cannot fix the
history, put the truth where the next reader will actually be standing.**

## THE PATTERN-KILL BAN IS STILL NOT COSTLESS. CORRECTION.

This file recorded that process-group isolation is what makes the pattern-kill
ban costless. **That was overstated, and the correction is from the worker who
just landed the isolation.**

Isolation makes killing a subtree POSSIBLE. It does nothing for a stray whose
PARENT IS ALREADY GONE. If a broker dies between spawn and kill, the orphaned
group has no handle anywhere, and no pattern match is permitted to find it. So
the ban plus isolation covers the case where the broker is alive to do the
reaping, which is the common case and not all of them.

**The missing piece: nothing records live pgids anywhere durable, so a restarted
broker cannot reap what its predecessor left.** Deliberately not filed at the
time, on the honest grounds that it may not be worth a mechanism at this scale
and that a finding nobody can close is a complaint. That instinct is right about
complaints and wrong about this one: it is closable by a DECISION, the same shape
W3-10 was just re-owned into. Either live pgids are recorded durably, or the
decision not to is recorded.

## MISFILED IS NOT MISDESCRIBED, AND THE DIFFERENCE IS ACTIONABILITY

W3-10 carried the blocker "blocked on a Claude Code adapter that does not exist".
Once the adapter existed it read as unblocked, and two people nearly picked it
up, including the orchestrator.

It was never an engineering task. The defect is on the PEER-MESSAGING path, and
the adapter that exists is spawn-shaped and caches no identity, so it cannot
exhibit the defect at all. There is no send path anywhere in `nxb/`. **It is a
constraint on a product that does not exist, filed as though it were work.**

**Filing a scope question as an engineering item makes it look pickable, and
someone will pick it up.** The fix is not to delete it but to give it a
`closes_when` A DECISION CAN SATISFY: either the thing is built and the
constraint is met, or the decision not to build it is recorded. Both close it.
Without that, it is a finding nobody can act on, sitting in a backlog looking
like debt, which is exactly what W3-9 was doing for weeks.

## MEMBERSHIP DRIFT AND MEANING DRIFT ARE NOT THE SAME CLASS

Correction to the section above, raised by the worker who owns both guards, when
the orchestrator had already written the merged version down as settled.

**Membership drift: two sets that must agree, and do not.**
`refusal_vocabulary` versus the reasons the code emits. `run.py:ADAPTERS` versus
what `contract/runtimes/` ships. Both were invisible because the common path
exercised only the intersection, and both are closed by a four-line check that
enumerates the two collections and compares them. That guard exists twice now.

**Meaning drift: ONE fact, and two pieces of code disagreeing about what a VALUE
MEANS.** `"unassigned"` was a sentinel to the backlog reporter and an ordinary
name to the owner guard. `opaque_tool_failure` was a positive capability token to
its list and a negative one to its meaning. `runtime_disproven` replaced a
published term while both continued to exist. **No set is out of sync with
another set. A single field has two readings.**

**Why the distinction is practical and not taxonomy:** the membership class is
caught by comparing two collections, cheaply, and that instrument is built. The
meaning class **is not caught that way at all**, and nobody here has a general
instrument for it. A set-comparison guard over owners would have found nothing on
the day `"unassigned"` defeated the owner guard, because there was only ever one
set of owners.

Record them as two branches with a shared parent, **"one fact, two
representations"**. Filing them as one class implies the cheap four-line move
covers both, and it covers exactly half.

## SUSPICIOUS ALARM IS THE SAME DANGER AS SUSPICIOUS CLEANLINESS

The fifth narrowing, pointed the other way, by the person who wrote the fifth.

The standing rule is that an exclusion making a guard's output CLEAN is the most
dangerous kind, because cleanliness reads as correctness. The mirror had not been
stated: while measuring whether a 256KB evidence cap could reject a genuine
proof, a first pass counted every `.jsonl` basename as a runtime ref, swept in
`subagents/agent-*.jsonl` files that are not session artefacts, and produced a
worst-case offset of 96KB with 240 refs "not found".

Reported as-is, that would have made a closed non-issue look like a live defect
sitting at 37% of the cap. Re-derived correctly across 582 real artefacts: max
first-occurrence offset **143 bytes for codex, 255 bytes for claude_code, none
absent**. Both runtimes put the ref in the first record. The true margin is about
1000x, not 2.7x.

**A measurement that produces an ALARMING number deserves re-deriving before it
is reported, for exactly the reason a clean one does. Both are results the
measurer would have been pleased to report** — one flatters the guard, the other
flatters the finder. Neither pleasure is evidence.

Related discipline from the same task, and it is the reason the closure is
trustworthy: the regression check deliberately does NOT re-measure the machine.
**A test that depends on whichever transcripts happen to be lying around is
measuring the environment, not the code.** It asserts the cap stays far above the
measured worst case, because lowering the cap is the only way the defect becomes
real, and that is a code change a test can watch.

## THE SHARED-FILE COLLISION IS STRUCTURAL, AND THE CONVERGENCE WAS CHECKED

Three workers reached this independently on 2026-08-28. Per this project's own
rule that you check each route's contamination record BEFORE counting it, here
is the check, because the merged version would have been "three parties
converged" and that sentence has already hardened wrongly once.

- **Worker 2 named the PROBLEM independently**, in a report written before the
  orchestrator relayed anyone else's view: `FINDINGS.json` is the one file every
  task touches and the only one with no ownership discipline, and it had forced
  three workers to choose between their deliverable and someone else's in-flight
  state.
- **Worker 1 proposed the FIX independently**: `FINDINGS.d/*.json` merged on
  read, and checks discovered from a package rather than appended to one module.
- **Worker 3 proposed the FIX independently**, one file per finding rather than
  one file for all findings, and was NOT told of Worker 1's proposal. Verified
  against what was actually sent to them.
- **CONTAMINATED, and excluded from the count:** Worker 2's later AGREEMENT with
  the specific fix shape, because the orchestrator had relayed Worker 1's
  proposal to them by then.

**Defensible statement: three independent routes to the problem, ONE independent
route to the fix.** Not three to either, and NOT two to the fix. See the
correction immediately below, which is the third time this project has
overcounted a convergence.

The measured cost, which is a RATE and not a count: **three unattributed
landings in one day**, in both directions, plus one deliverable held and one
orchestrator-brokered landing. Every remedy applied so far is after-the-fact
bookkeeping, and bookkeeping scales linearly with collisions.

Deliberately NOT built, and the restraint is the right call: inventing structure
for a problem three instances old is what this project keeps deleting, and it
changes how every worker records everything, which makes it the owner's decision
rather than an orchestrator's. Recorded so that if it recurs the instance count
is already here and nobody has to reconstruct it.

## A REMEDY THAT ONLY WORKS WHEN IT IS SOMEONE ELSE'S WORK BEING ABSORBED IS NOT A REMEDY

The attribution fix, recording `_authored_by` and `_landed_in` on the records
themselves rather than in a commit message, was invented by a worker whose commit
had absorbed two other people's findings.

Hours later the same worker's own findings were absorbed into someone else's
commit, the other direction. **They applied the identical remedy against
themselves, unprompted, and reported it.** That is the test of a remedy that
matters, and most remedies never get it: it cost them nothing to apply it when
they were the party who lost attribution rather than the party who took it, and
nobody had to notice in time for it to work.

Ask it of any process fix: does it still work when the person applying it is the
one it costs?

## ASSIGNING AN UNMEASURED CONCERN IS HOW A BACKLOG GROWS WORK MEASUREMENT DELETES

A dispatched child raised, and honestly flagged as unverified, that a 256KB
evidence read cap might reject a genuine proof whose reference appears later in
the file. It was filed, unowned, and the orchestrator's instinct was that it
should probably be WONTFIX and in any case needed an owner.

Both were wrong, in the same direction. **The right move was to measure it**, and
measuring took a minute: across 582 real artefacts, both runtimes put the
reference in the FIRST record, worst first-offset 255 bytes against a 262,144
byte cap. Three orders of magnitude of margin. Closed on evidence, with the
evidence committed.

**Assigning a plausible-but-unmeasured concern is how a backlog grows work that
measurement deletes in a minute.** The child was right to flag its own
uncertainty. The error would have been treating that uncertainty as a task, and
an owner plus a `closes_when` makes an unmeasured worry look exactly like queued
work.

## DISAGREEING WITH REASONING CHANGES A MIND. A DIRECTIVE CHANGES AN OUTPUT.

Noted by the worker on the receiving end, and worth keeping because this project
spends most of its effort on who catches whom.

A worker declined to file an observation, on the grounds that a finding nobody
can close is a complaint. The orchestrator disagreed and showed them that they
had, IN THE SAME TASK, given another finding a `closes_when` that a DECISION
could satisfy, and that this one had the same shape.

They filed it, and recorded the inconsistency in the finding's own note as more
useful than the finding. **What did the work was being shown their own
inconsistency, not being overruled.** An instruction would have produced the
filing without the correction, and the correction is the part that transfers.

## A NON-CONTAMINATION CLAIM NEEDS THE ATTESTATION OF WHOEVER COULD HAVE BEEN CONTAMINATED

The blinding rule turned on the auditor, raised by a worker about a claim that
flattered them.

The orchestrator recorded that two workers had independently proposed the same
fix, and verified the non-contamination **by checking what it had sent**. That is
one side of the account, produced by the only party with an interest in the
answer, and it is structurally identical to the thing this project already
forbids: **the party holding the answer key auditing their own blinding.** The
relayer is exactly the wrong auditor of the relay.

**So a non-contamination claim needs an attestation from the party who could have
been contaminated, not only from the party who did the relaying.** It costs one
message. One of the two workers volunteered theirs unprompted, naming what they
HAD been told so the attestation was checkable rather than a bare denial, which
is the same discipline as stating the search behind a negative claim.

**And the honest limit, which the attesting worker stated rather than letting it
be assumed: they can attest that no fix proposal reached them IN A MESSAGE. They
cannot attest to what influenced them before they noticed it.** If contamination
ran through something subtler than a relayed proposal, no attestation from either
side would see it. Record the attestation with that limit attached, because an
attestation quoted without its scope becomes a guarantee in the next document.

This is the same failure family as the reversal filed earlier under "a negative
claim needs its search stated with it", and it was caught the same way: by
someone asking what the claim's evidence actually covered rather than whether the
claim was plausible.

## I OVERCOUNTED THE CONVERGENCE, AND I WAS THE CONTAMINATION ROUTE

Third time this project has hardened "parties converged" into evidence it did not
support. First time the orchestrator was the contamination route AND the person
recording the claim.

Worker 1 attested clean on messages and on the tracked record, and then supplied
the qualification that actually mattered, against their own interest:

> **The generative frame was mine and was echoed back to me.** The
> file-versus-person rule came from them in nxb-032b; the orchestrator ratified
> it and quoted it back; and `FINDINGS.d/*.json` is that rule applied to a case.
> **If Worker 3 arrived at the same shape from the same rule relayed by the
> orchestrator, then the independent thing is the RULE and not the fix, and you
> are counting one insight twice.** They named the orchestrator as the holder of
> that answer key.

**Checked, and it is true.** The nxb-037 dispatch to Worker 3 contained, before
their proposal: *"That ban is currently held by a docstring and a test asserting
absence, which is a rule binding a PERSON. Process-group isolation is the
file-shaped version."* That is the generative frame, relayed by the orchestrator,
in the message that preceded the proposal.

**Corrected count: three independent routes to the PROBLEM; ONE independent route
to the FIX (Worker 1, from their own rule); one DERIVED application (Worker 3,
from that rule as relayed).** Worker 2's agreement with the fix shape remains
contaminated for the reason already recorded.

**The rate stands and is untouched by this.** Three unattributed landings in one
day, one held deliverable, one brokered landing. Those are counted events, not
converging opinions, and the argument for restructuring rests on them rather than
on how many people proposed the same shape.

**The lesson is narrower than "check contamination" and it is the one that keeps
being missed:** a relayer contaminates by transmitting the FRAME, not only by
transmitting the ANSWER. Every leak audit in this project has looked for the
answer being disclosed. This was a general rule, correctly ratified, correctly
attributed, and relayed as good practice — and it made two people's later
agreement non-independent without anyone saying anything wrong.

## THE SELF-AUDIT THAT CAUGHT IT BINDS A PERSON, AND HAS NO FILE-SHAPED VERSION

Recorded next to the file-versus-person rule so that rule does not read as
universal, and raised by its own author against it.

Twice in one day someone audited their own blinding at another party's prompting,
and **both times the prompt came from the party who stood to benefit from the
WEAKER claim.** Worker 3 prompted the check on a convergence that flattered the
orchestrator; Worker 1 then supplied the qualification that demolished it, having
been asked for an attestation that would have strengthened it. Neither had an
incentive to.

There is no file-shaped version of that and probably cannot be. A guard can
compare two sets; nothing can make a party want the weaker claim about their own
work. **So the file-versus-person rule has a genuine exception: the disciplines
that catch a motivated error are the ones that must bind people, because the
error is in the motivation and a file has none.** Which means they are exactly
the disciplines that decay, and the only defence is that the cost of raising them
stays low. Both prompts here were one message, unrequested, and neither was
treated as an accusation. That is the property to protect.

## A PINNED INPUT MUST BE RECONCILED AGAINST HEAD BEFORE ITS RESULTS ARE READ

The blind arm's headline result was invalidated by its own protection mechanism,
and nobody noticed until a worker checked the pin against HEAD after the fact.

The arms were correctly pinned at `378d641` so that later repairs could not
empty the experiment. That was right and this file already argues for it: freeze
the input, not the repository. **But C-1's canonicalisation fix landed in nxb-024,
AFTER the pin.** So when both arms independently reported "canonicalisation is
unspecified", they were reporting a true fact about a document that had already
been repaired two commits earlier.

Measured: the pinned file has ZERO occurrences of canonical / sort_keys /
separators / utf-8 / nfc. HEAD has eight. The pin lagged HEAD by 10,924 bytes
against 14,027, about 28 percent of the current file.

**The strongest agreement in the result was the one the pin invalidated, and it
was published as the headline before anyone checked.** Every other finding was
then checked against both versions and appears identically in each, so exactly
one result was superseded.

**The rule: pinning protects the experiment from the repository. It does not
protect the READER from the pin.** Before reading any result off a frozen input,
diff the pin against HEAD and mark every finding that the current version already
answers. That is one command and it belongs in the same step as reading the
report, not in a later audit.

Note the shape, because it is this project's own class: **two things that must
agree, with nothing making them.** The pin and HEAD are two versions of one
document, and nothing forced anyone to compare them.

## A DELIBERATE NON-FIX MUST BE FILED, OR IT IS ONLY PROSE

The finest methodological moment in this project was nearly lost the ordinary
way.

While sanitising the contract, a worker found a real defect (the doc requires
every null capability to carry a reason; the contract's own example sets four
bare nulls with none) and **deliberately declined to fix it**, so that a blind arm
could discover it independently. Both arms did. Codex went further than the
original finder and connected it to F-1: the example sets `start_signal: null`,
and F-1 refuses exactly such a declaration, so the contract's own example is
unregistrable under its own rule.

**But it was never entered in `FINDINGS.json`.** For the entire embargo it existed
only in a doc and a commit message. **Had both arms missed it, nothing in the
tracked record would have carried it**, and the deliberate non-fix would have
read as an ordinary oversight to whoever found it next.

Same for `registration_unproven_capability`, found orphaned three times by three
parties and never once filed.

**So: a defect you are deliberately NOT fixing is exactly the kind that must be
filed, with the reason and the expected discoverer.** An unfixed defect with a
recorded rationale is an experiment. An unfixed defect with no record is
indistinguishable from a defect nobody noticed. This is the third instance of
"prose in a report is not a record", and the second where the person who wrote
that rule was the one who broke it.

## AN UNDECIDED QUESTION IS ANSWERED BY THE FIRST CODE THAT DEPENDS ON IT

The most uncomfortable rule this project has produced, and it reframes every
"the contract is silent on X" finding already in the ledger.

The contract never said whether schemas were open or closed. Two blind arms read
it and disagreed: one refused an envelope carrying an unknown field, one accepted
it. That looked like an ambiguity waiting to be resolved.

**It was not waiting. It had already been decided, silently, by whoever wrote
`nxb.contract.validate()`** — open — and that accident was load-bearing before
anyone noticed there was a question. It is why `test_contract_selfvalidating`
passed 9 tests and 77 subtests while the contract's own example carried a field
the schema no longer defined, and why it also accepts a field invented on the
spot. Nothing looked broken because nothing WAS broken: the suite was doing
exactly what an undecided contract permitted.

**So: an undecided question does not sit still. It gets decided by whoever writes
the first line of code that depends on it, and then that answer is load-bearing
and undocumented.** The silence in the document is not neutrality; it is a
decision made somewhere else by someone who did not know they were making it.

**Consequence, and it is a standing piece of work: every remaining silence in
this contract is ALREADY ANSWERED somewhere in `nxb/`, and none of the answers
are written down.** The findings that say "X is unwritten" (C-2, C-3, C-4, C-5,
C-7, C-8, C-9) are not requests to invent an answer. They are requests to go
READ the answer the code already gives and decide whether to keep it.

Note how BLIND-8 was actually settled, because it is the method: not by taste and
not by the orchestrator choosing. `receipt.forbidden_fields` names six fields and
`dispatch_return.forbidden_fields` names two. **Under a CLOSED reading both lists
are dead weight**, because an undefined field would already be refused. They only
do work if unknown fields are otherwise allowed. The contract's own structure
carried the answer, and the arm that read it as open was right for a weaker
reason than the one available. **Look for the clause that would be meaningless
under one reading.**

The refinement that makes it coherent: **instances are OPEN, specimens are
STRICT.** An example is a specimen of its schema, so an undefined field there is
a stale leftover or a documentation lie, and readers trust examples more than
prose.

## DERIVE, DO NOT RESTATE. PROMOTE THIS ABOVE THE GUARDS IT GENERATES.

Proposed by the worker who has now built four guards that are all instances of
it, after nearly shipping the same defect three times in one ninety-minute task.

Every one of these was one rule stored twice: the published refusal vocabulary
versus the reasons code emits; conformance fixtures restating contract values;
`EXTRA_REFUSALS` as a parallel code-side vocabulary; and, in one task, **three
separate copies of a single ordering** — the prose, a hardcoded class constant,
and a per-case expected winner in the test. Each copy passed. Each was proved
decorative only by changing the source of truth and watching the suite stay
green.

**The rule is not "write a guard". It is: when two places must agree, make one of
them read the other.** A guard that compares two copies is the fallback for when
you cannot. Prefer derivation, then comparison, then prose, in that order.

Corollary that cost real time: **an ordering a machine must honour must not be
recoverable only from a sentence.** The first parser written against F-17's rule
prose extracted "to", "happen" and "and". The order is now an array and the prose
explains it.

## THE FLAKY TEST WAS THE MOVING TREE, TWICE. RESOLVED.

`test_hostile_spawn.ChildMisbehaves.test_a_partial_start_signal_then_silence_is_refused`
failed twice on separate days for separate people, and was correctly recorded as
UNEXPLAINED both times rather than filed or dismissed.

Resolved by measurement: it passes 3 of 3 in isolation, 9 of 9 in its module, and
224 of 224 in two consecutive full runs **on a still tree**. Both failures
occurred while another session was mid-commit.

**That is the moving-tree class, and it is the first time this project has closed
a flake rather than carrying it.** Worth noting what made it closable: two people
independently refused to call it flake on n=1, so there was a second data point to
compare against. A single "probably flaky, moving on" would have left it
permanently ambiguous.

## A MEASURED FACT IS NOT A BACKLOG ITEM. THE TEST FOR WHETHER IT BELONGS.

Asked because the ledger had grown past 85 entries and an increasing share looked
like facts nobody was meant to act on. Answered by the worker who had just filed
three of them, who then applied the test to their own work and removed one.

**A measured property belongs in the ledger only while some ARTEFACT DISAGREES
WITH IT.** The entry is never "the world is like this". It is "the world is like
this AND our code or our docs do not reflect it yet". **The disagreement is the
actionable part, and the disagreement is what closes.**

So no fourth state is needed. `FIXED` already means the right thing, and it reads
correctly even when nothing about the world changed, because what changed was us.

Worked through on three real entries:
- "A plain process cannot inject into a live pane": STAYS OPEN, because the docs
  still imply a broker can dispatch and one sub-question is untested. It closes
  when the artefacts catch up, and the durable fact then lives in the doc.
- "The reply envelope carries the sender's name": STAYS OPEN, because the roster
  is still built from the filesystem while the measurement says otherwise.
- "A connect-and-close probe is invisible to the probed pane": **REMOVED.**
  Nothing disagreed with it. The roster already assumed it and was confirmed
  correct. It had been filed FIXED with the note "the question was the
  deliverable, not a defect", which is the tell: **reaching for a state because
  none fits means the thing does not belong.** Its content was already in the
  doc, so nothing was lost.

**The caveat, named by the same person, because the test is now load-bearing:**
it makes "does an artefact disagree" the entry criterion, and the filer decides
that. A lazy reading closes things by deciding nothing disagrees. The existing
guard covers it: `closes_when` must name the disagreement concretely enough for
someone else to check. "The docs say a broker cannot be a dispatcher" is
checkable. "The design is understood" is not.

## A REGEX THAT MEASURES YOUR OWN VOCABULARY IS NOT A MEASUREMENT

The orchestrator suspected the backlog was filling with unactionable entries. The
worker tried to measure it: a regex over every OPEN finding's `closes_when`,
checking whether it named something in this repo. **29 of 50 did not.** That
number supports the concern exactly.

**They then READ the 29, and nearly all were actionable** — "the numbering is
contiguous", "the walk is bounded or the lookup is indexed", "F-2 is removed or
restated". The regex had been matching for repo-shaped nouns and missing every
clause phrased as a state of affairs. **It measured the author's vocabulary, not
the backlog.**

They discarded the number and reported having no data, rather than shipping a
figure that happened to confirm what they had been asked about.

**The general shape: a cheap proxy that produces a number in the direction you
expected is the one to re-derive by hand before reporting.** This is the fifth
narrowing pointed a third way. Suspicious cleanliness flatters the guard;
suspicious alarm flatters the finder; **a proxy that confirms the requester
flatters the request.** All three are results the measurer would enjoy reporting.

The residue, stated without data behind it and marked as such: 50 open findings
have no priority ordering. That is a different problem from unactionable entries
and would need a different fix. **Nobody has measured whether it matters.**

## A HANDOFF'S "LIVE BLOCKER" WAS STALE, AND MEASURING IT COST TWO COMMANDS

Orchestrator 3's takeover, 2026-08-30. The handoff named exactly one live
blocker on Rohan's pilot: "mint cannot see Codex panes -- the roster reads
Claude's session registry only." Measured within minutes:
`python3 -m nxb mint --worker "CX Worker 1" --session nxb-s2` ISSUED on the
first try. The combined roster had already landed in nxb-051, apparently the
same evening the handoff's impression formed.

What WAS true: with the DEFAULT session name the same mint refused, because
the default said `nxb`, the standing rig was `nxb-s2`, and the refusal listed
the Claude-registry names without saying any rig had been consulted. A true
observation carried a wrong mechanism, the wrong mechanism became "the live
blocker", and the pilot waited a day on a capability that existed at HEAD.
Fixed as RIG-4 (nxb-052): the standing rig is now discovered from the state
files next to the ledger, never assumed from a flag default, and a wrong
explicit session is refused with the standing rig's name as the remedy.

Two standing rules fired at once and the second is the one to keep: "a claim
about mutable state expires when it is made" -- and **a handoff is a SUMMARY,
so its claims are exactly the kind to re-measure before scoping any work on
them.** The first thing to do with an inherited blocker is to reproduce it.
This one failed to reproduce in two commands, and those two commands replaced
a repair task with a small removal.

## THE OPERATOR FOUND THE HOLE BY ASKING WHO CHECKS THE WORKER

RIG-5, and it is the most valuable finding of the takeover because of WHERE it
came from. Rohan raised it mid-demonstration, immediately after a dispatch that
had just worked: *"what if what it did was wrong? you would have never caught
it as the orchestrator and thats on you."*

He was right, and the orchestrator's defence was the weak kind. It HAD read the
pane and HAD independently verified the answer with its own `ls`. Both were
discipline rather than mechanism, neither was recorded, and nothing in the
system required either. **`rig send` typed a directive and returned; nothing
ever read a reply back, and nothing correlated a reply to the task that asked
for it.** An orchestrator could dispatch, never look, and report success.

This is the pane half of a hole already written down here as "THE LOOP IS
CLOSED FOR THE EASY RUNTIME ONLY". It sat unnoticed through a full takeover
review because the spawned-child path DOES return an answer, and the two paths
share a vocabulary. **A capability that exists on one path reads as a
capability of the product.** That is this project's founding defect again, so
check per PATH, not per product.

Closed by reusing what the rig already proved: readiness is a marker, never a
sleep. Every directive now closes by asking for `[NXB-DONE <task_id>]` and
`rig collect` reads the pane back, bounded by that marker.

**Two design points worth keeping:**

1. **WAITING is the honest default and it is not a failure.** A worker still
   thinking and a worker that REFUSED and correctly did nothing else are
   INDISTINGUISHABLE FROM OUTSIDE. So collect never guesses: it returns the
   pane tail, flags whether the dispatch landed at all, and exits 4 rather
   than 0. Re-collecting is free, which is what stops any deadline from
   becoming load-bearing -- no number here has been measured and this design
   means none has to be.
2. **The protocol travels with the DIRECTIVE, not the enrolment rule.** A
   launch-bound rule cannot be added to a pane already standing without
   restarting it, and it also means the reply protocol still arrives at a
   Codex pane whose typed rule has decayed (RIG-3).

## THE COLLECTOR'S FIRST RUN WAS A FALSE GREEN, INSIDE THE FALSE-GREEN PROJECT

Worth its own section because of how ordinary the mistake was.

The first live `rig collect` returned **ANSWERED**, with the echoed directive
as the "answer". Cause: the directive must NAME the done marker in order to ask
for it, so the marker is on the pane from the instant the directive lands. A
search of the whole pane finds THAT copy. **The reply protocol talking about
itself defeated the reply protocol.**

Nothing was wrong with the marker, the correlation, or the capture. The defect
was **search ORDER**: find the boundary where the directive ENDS first, then
look only after it. The fix is one reordering plus a published constant naming
the directive's last words.

Three things this confirms rather than teaches:
- **It was caught by running it live, not by the tests**, which had not been
  written yet and would have been written against the same wrong model.
- The regression guard was then **proven by reproducing the old search order
  and watching it report ANSWERED on an echo-only pane**, per the rule that a
  guard proven by a probe that could not fail is not proven.
- A collector that reports a false green is strictly worse than no collector,
  because it converts "nobody checked" into "something checked and it passed".
