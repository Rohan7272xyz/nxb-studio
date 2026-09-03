# NEXUS Bridge — Task Ledger

Updated on every dispatch and every ratification. If it is not here, it does
not exist. Never reuse a `task_id`; revisions get `.1`.

## Live

| task_id | worker | status | what |
|---|---|---|---|


| nxb-006 | Worker 3 | COMPLETE, ratified. `nxb/` + `docs/H1-BUILD-REPORT.md` @ 006376c. 34 tests. |
| nxb-009 | Worker 1 | COMPLETE, ratified. `docs/CONTRACT-AMBIGUITY-nxb-009.md` @ 2237929. |
| nxb-012 | Worker 1 | COMPLETE, ratified. Harness @ deb5972, findings @ 41964b5. Catches C-1 unaided. |
| nxb-017 | Worker 1 | COMPLETE, ratified @ 2994978. Fourth blocking instance found, on the WRITE path. |
| nxb-022 | Worker 1 | COMPLETE, ratified @ cde0ad0. Canary already deep; premise of the task was a ratified-but-unverified claim. |
| nxb-025 | Worker 2 | DISPATCHED | Consume the negative signal: 25.6s failure detection becomes 0.6s. |
| nxb-013 | Worker 2 | ABANDONED as a subject: orchestrator contaminated it 3x. Converted to AUDITOR. Audit @ 6f3f1e6. |
| nxb-016 | Worker 2 | COMPLETE, ratified @ 378d641. Contract sanitised, isolation rebuilt. |
| **BLIND ARM** | **NEEDS A FRESH PANE FROM ROHAN** | Brief @ docs/BLIND-ARM-BRIEF.md (hand ONLY the section below the rule). Contract sha256 869c590bca43451f43965d4d at 378d641. Isolated dir is session-scoped: REBUILD AND RE-VERIFY before use. |
| nxb-010 | Worker 3 | COMPLETE, ratified. `nxb/adapters/codex.py` + `docs/H2-BUILD-REPORT.md` @ 91acb6c. 48 tests. |
| nxb-011 | Worker 3 | COMPLETE, ratified. `nxb/proof.py`, `nxb/canary.py` @ 1d466f9. 74 tests. |
| nxb-014 | Worker 3 | COMPLETE, ratified @ 9ab3aab. Budget deleted; no fourth blocking instance. |
| nxb-015 | Worker 3 | COMPLETE, ratified @ 46992dd. Live Codex round trip. 99 tests. |
| nxb-018 | Worker 3 | COMPLETE, ratified @ 8e70cf6. F-20 survived at 0%. Predictions sealed. |
| nxb-020 | Worker 3 | COMPLETE, ratified @ f4d596c. Guard caught 3, not 1. |
| **OWED** | after nxb-019 | Fix `units` (never reaches worker) and dispatch returning OBSERVED on a FAILED spawn. Predictions P1 and P4 VOID as of this ruling, before any cold-pass result existed. |
| nxb-019 | Worker 2 | COMPLETE, ratified @ 977252a. Four findings, one of them a contract gap. |
| nxb-021 | Worker 3 | COMPLETE, ratified @ c6b79d0. All six fixed; F1 chose REFUSE. 118 tests. |
| nxb-023 | Worker 3 | COMPLETE, ratified @ 8aecc59. **FINDINGS.json: 40 findings, 33 open, 8 high, 18 unowned.** |
| nxb-024 | Worker 3 | COMPLETE, ratified @ 0824786. Blocking class ENDED. 27 open, 4 high, **ZERO unassigned**. |
| **OWED** | unassigned | Score the sealed predictions against `docs/COLD-USER-nxb019.md`. P1 and P4 void. Scorer must be neither predictor nor subject. |
| nxb-007 | Worker 2 | COMPLETE, ratified. `evidence/nxb-007/` @ 4645c41. Both halves. |
| nxb-008 | Worker 1 | QUEUED behind nxb-009. Blind judging of nxb-007. Brief below. |

## Closed

| task_id | worker | outcome |
|---|---|---|
| nxb-001 | Worker 1 | COMPLETE, ratified. `docs/RUNTIME-CLAUDE-CODE.md` @ 6c215d2. |
| nxb-003 | Worker 3 | COMPLETE, ratified. `docs/ADAPTER-AUTOPSY.md` @ a013f31. |
| nxb-002 | Worker 2 | COMPLETE, ratified. `docs/RUNTIME-CODEX.md` @ e5b91b0. |
| nxb-004 | Worker 3 | COMPLETE, ratified. `docs/REUSE-ASSESSMENT.md` @ 658e9db. Reuse-vs-rewrite DEFERRED by design. |
| nxb-005 | Worker 3 | COMPLETE. Superseded by 005.1. |
| nxb-005.1 | Worker 3 | COMPLETE, ratified. `docs/SPEC-RECEIPTS-LIVENESS.md` @ b8c91d8. **Specification phase CLOSED here.** |

## Facts established (source-labeled)

- **The adapter reads directives out of a browser DOM.** It is a Playwright
  program driving Chrome at claude.ai, whose entire input is
  `page.locator("#main-content").inner_text()`. Terminal-emitted directives are
  outside its sensory range. There is no file watcher, hook, log tail or stdin
  path in the codebase. SOURCE: nxb-003, read from source at web_adapter.py:503.
- **It has not run since 2026-06-14**, on either host. Zero `agent_prompt.md`
  artifacts exist anywhere; none of the 106 task folders was adapter-written.
  SOURCE: nxb-003 across two hosts; orchestrator independently confirmed the Mac
  side (no ~/.config/nexus/orchestrators, no process, 0 artifacts).
- **It lives only on second-host** at /home/operator/nexus. Not on the Mac.
  SOURCE: nxb-003, orchestrator confirmed absence on Mac.
- **11 of 14 identified vanish points are silent BY CONSTRUCTION, not by bug.**
  Every error path INSIDE the pipeline works; the system is blind to every
  failure that prevents entry to it. SOURCE: nxb-003, full list with cited
  source lines in docs/ADAPTER-AUTOPSY.md.
- **The gap is not "an ack". It is a RECEIPT plus a HEARTBEAT.** No component of
  NEXUS ever asserts that a counterpart exists. There is no signal at the moment
  of observation, before validation, addressed to the dispatcher in the
  dispatcher's own runtime. SOURCE: nxb-003.
- **Count correction: 5 directive BLOCKS were emitted on 2026-08-27, not 7.**
  Seven task ids were dispatched (007, 007.1, 008, 009, 010, 011, 011.1) but 008
  and 009 were never wrapped in directive tags. Do not conflate the two numbers.
  SOURCE: nxb-003, read from the session transcript.
- Claude Code peer messaging works: `ListAgents` + `SendMessage` delivered all
  7 hand-delivered directives and carried every worker report back.
  SOURCE: orchestrator, direct use.
- Codex reportedly has `codex queue` for messaging local or remote sessions and
  `@` mentions of other Codex tasks. SOURCE: web search 2026-08-28, NOT verified
  by use. This is exactly the kind of fact nxb-002 exists to replace.

## Codex facts (nxb-002, measured on this Mac 2026-08-28)

- **Codex is USABLE.** codex-cli 0.150.1, ChatGPT OAuth, doctor 22 ok / 0 fail.
  "Codex down" is STALE and should not be carried forward.
- **`codex exec` hangs silently if the caller leaves stdin open.** Zero bytes,
  no `thread.started`, still alive 70s later. Fix is `< /dev/null`. Its stderr
  line "Reading additional input from stdin..." also appears on healthy runs, so
  it is not a diagnostic.
- **`codex queue` exit 0 does NOT mean delivered.** It validates only that a
  rollout exists on disk; it returned 0 for a thread whose process had exited.
  Queued into a demonstrably mid-task turn: never seen, row still pending after.
  Store-and-forward for a LATER turn.
  **SCOPE THIS PRECISELY: what was proven is that `codex queue` does not reach a
  turn in flight. It is NOT established that Codex cannot be reached mid-task at
  all.** `codex-reply` against an in-flight turn is UNTESTED, and the binary
  contains `activeTurnNotSteerable` with the steer feature enabled, so a mid-turn
  path may well exist. Do not let "Codex cannot be steered mid-task" become
  canon on this evidence.
- **The web-search claim about `@` mentions is NOT confirmed.** `UserInput::Mention`
  is an inline text annotation; neither exec nor queue exposes a mention param.
- **A sandbox denial is INVISIBLE in the event stream.** A blocked write under
  `-s read-only` produced no event at all; the only trace was the agent's prose.
  A broker CANNOT detect "this worker was blocked" by parsing the stream.
- **MCP IS AN AGENT LAYER FOR CODEX AND ONLY A TOOL LAYER FOR CLAUDE CODE.**
  The two probes appeared to disagree and both are right. nxb-001 measured
  `claude mcp serve` as tools-only, no sampling, prompts/list and resources/list
  both -32601: an MCP client CANNOT ask Claude Code to think. nxb-002 measured
  `codex mcp-server` returning `{threadId, content}` synchronously: it CAN ask
  Codex to think. **Consequence for adapter shape: Codex returns content over
  MCP; Claude Code has NO content reply channel at all, so a broker must own the
  worker's stdout or read its transcript.** The orchestrator previously recorded
  nxb-002's "strongest cross-runtime candidate" conclusion unqualified. Corrected.
- The real bidirectional path FOR CODEX is MCP, not queue. `codex mcp-server` exposes
  `codex` and `codex-reply`, both returning `{threadId, content}` synchronously.
  Proven: reply with only the threadId recalled turn-one context. Deprecated in
  favour of `codex app-server` — build against app-server.
- **Ack primitive: `thread.started`**, first line on stdout, carries thread_id
  before any model work. Means "process launched, thread created", NOT "work will
  succeed". Require it within a timeout and kill the child if absent. Do NOT use
  process liveness, and do NOT use the `-o` file as a success signal (it was
  written while a process still hung); its ABSENCE is a reliable failure signal.
- Exit codes: 0 completed, 1 turn failed or queue target unresolved, 2 usage error.
- **Flag surfaces differ per subcommand.** `codex exec` rejects `-a`;
  `codex exec resume` rejects `-s`. Both exit 2. Flags do not carry across.
- **The model a thread RECORDS can diverge from what config sets.** config.toml
  set `gpt-5.6-sol`; the five probe threads recorded `gpt-5.6-luna`; the threads
  table holds both (luna 6, sol 3) over two hours.
  **The divergence is OBSERVED. The CAUSE is UNVERIFIED and must travel that
  way.** It could be alias resolution, provider-side routing, an A/B, or `sol`
  simply being a label that resolves to `luna`. There is NO evidence of a silent
  substitution and "Codex swaps models on you" is NOT a supported claim.
  The design rule holds either way, which is why it is a good rule: **This threatens
  the disagreement thesis directly: pin `-m` explicitly and record what the
  thread actually recorded, or you do not know which model produced a
  disagreement.**
- **Identity: thread UUIDs only.** Names are auto-generated AND MUTATE (4 of 8
  sampled ids carried more than one name). `codex queue` accepts a name, so name
  addressing is a live hazard.
- **`codex exec` has NO approval policy.** It rejects `-a` and every thread
  recorded `approval_mode=never`. In exec mode the sandbox is the ONLY boundary
  and there is no human in the loop by construction. Bypass paths exist
  (`--dangerously-bypass-approvals-and-sandbox`, `--approve-for-me`, and `-c`
  overriding `sandbox_mode`). **A worker must never pick its own target sandbox.**
  Lead for Phase 4: enterprise-managed keys (`allowedSandboxModes`,
  `allowedApprovalPolicies`) may give a machine-level ceiling a per-invocation
  flag cannot raise. Usability outside a managed deployment UNVERIFIED.
- **Codex already ships a native multi-agent layer, enabled on this host:**
  `spawn_agent`, `send_input`, `resume_agent`, `wait_agent`, `close_agent`,
  `list_agents`, plus a `thread_spawn_edges` table (parent/child/status, 59 rows).
  It does not solve cross-runtime, but it has solved spawn, address, wait,
  interrupt and cancellation within a runtime. Copy rather than reinvent.

## Open, needs Rohan
- Starting `codex app-server` is a machine-wide state change; not done unilaterally.
- Rohan has three live `codex --yolo` sessions and `--yolo` is not in `--help`.

## SPECIFICATION IS CLOSED. TWO REASONS, BOTH FROM nxb-005.1.

**1. Four documents, zero lines of running code, and a 100% correction rate.**
Every document has corrected the one before it, including two of the same
worker's own claims. There is no reason to think draft 3 breaks that streak. The
cheapest way to find draft 2's errors is to build H1 and see which of its 25
refusals are unimplementable or intolerable. Two of the strongest open objections
are empirical questions that a week of real use answers and no amount of
specification will.

**2. THE DISAGREEMENT THESIS HAS NEVER BEEN TESTED.** Every task so far measured
plumbing. The premise that an Opus orchestrator and a GPT-5.6 worker disagreeing
is a genuinely INDEPENDENT check is the load-bearing assumption of the entire
project and it is tagged [A], not [M]. **If the disagreements turn out to be
mostly stylistic, this broker is a delivery mechanism for noise and the shape of
the project must change.** It is testable now, without the broker, in an
afternoon, and nobody has run it.

## Corrections carried in draft 2

- The refusal reorganisation made the spec LONGER (700 vs 580 lines), not
  shorter as its author predicted. Erosion-resistance claim holds; brevity claim
  was wrong.
- Draft 1's R-033 keyed admissibility on the PINNED model, which would have
  marked every Codex dispatch inadmissible under the measured sol/luna
  divergence. Replaced: admissibility keys on the REPORTED model, since that is
  the only claim about who actually did the work. Divergence makes the LABEL
  wrong, not the work inadmissible.
- **A refusal binds an actor that is RUNNING. It cannot bind one that does not
  exist.** The 2026-08-27 failure was a non-running component, so a system built
  only of refusals would not have caught it. This is why liveness must be a
  separate mechanism rather than a special case.
- **The orchestrator's own call-versus-emit diagnosis is [A], not [M].** On
  2026-08-27 the return value AND human attention both differed between the two
  paths. Attributing the whole difference to the return value is a
  single-variable explanation of a two-variable experiment. Cheap to test.
- **R-050 cannot be enforced by the broker or by any spec.** Only the HARNESS can
  make a return value unskippable. It is a requirement on whoever builds the
  dispatcher-side tool, and needs a named owner or it becomes another document
  rule, which is the exact failure this project exists to fix.
- UNKNOWN must never be rendered as failure. Conflating "I got no answer" with
  "it did not happen" is the same error as conflating "nothing came back" with
  "nothing was sent".

## nxb-006 (H1 BUILT) — what one hour of code found that five documents did not

- **R-050 AMENDED, and it partly undercuts the orchestrator's diagnosis.**
  `SendMessage` returned `{success:true, msg_id}` to a peer that `ListAgents` had
  just reported OFFLINE. The return value is a TRANSMISSION ACK: truthful about
  address resolution, silent about delivery. **Had the seven lost directives gone
  into a channel with a transmission ack, the orchestrator would have received
  seven `success:true` and proceeded exactly as it did.** A dispatch must return
  THE RECEIPT; a call returning an acknowledgement of transmission is an emission
  with extra steps. Still [A]: the attention half is untested because the
  experimenter was the dispatcher.
- **Broker-as-library vs broker-as-peer.** If the broker is a library you call,
  the return value IS the receipt and no inbox is needed. If it is a peer, the
  return value is a transmission ack that lies and the inbox is mandatory.
  **The inbox is a precondition for a receipt on any transport where the return
  value is not itself the receipt** — which is every cross-process transport
  measured so far.
- **F-5 failed in the FIRST HOUR, and worse than predicted.** With no canary
  every runtime is UNKNOWN forever, so it refused 100% of dispatches. The
  predicted end state was an operator widening a budget. The OBSERVED end state
  was the operator FORGING A PROOF by hand-writing `last_proven_at`. F-5 must
  distinguish never-proven from proven-and-stale, and a first dispatch probably
  must serve as its own proof.
- **GENERATION BEATS TESTING.** A validator generated from the contract makes
  schema drift impossible rather than detectable, which made the drift assertion
  vacuous. The surviving assertion is the one that cannot be generated: every
  claimed invariant must name code that enforces it, and any invariant enforced
  by nothing must say so out loud. One does: `provenance_is_asserted`,
  `enforced_by: "NOTHING. Declared open."`
- **F-1 caught the real defect on the real runtime.** It read Claude Code's
  measured declaration, saw a null start_signal, and refused to register it,
  before any work was dispatched. That is nxb-003's failure being prevented by
  the rule written for it.
- **R-051 as specified CREATES a vanish point:** a repeated dispatch_key carrying
  a DIFFERENT payload returns a stale receipt whose `state: OBSERVED` is true
  about the wrong thing. Should refuse with `dispatch_key_reuse_divergence`.
- **F-8 has an undocumented dependency:** a digest check needs an agreed
  canonicalisation, and if that drifts F-8 fires on every dispatch for reasons
  unrelated to truncation. The canonicalisation must be published WITH the
  contract. It is not.
- New vanish points **16-19**: stale session identity, unauthenticated sender,
  dispatch_key reuse divergence, canonicalisation drift.
- **THE BROKER MUST REFUSE TO TREAT A LIVENESS SIGNAL AS A COMPLETION SIGNAL.**
  `peer_idle_notice` fired at 10.8s on a task still running a 25s command.
- **This project reproduced its own failure mode on itself.** The orchestrator
  closed specification before nxb-001's measured facts reached the spec, so they
  existed only in a chat message. HANDOFF.md says a durable fact goes in a file
  the same turn it is learned.

## Codex's answers about itself (2026-08-28)

SOURCE: a Codex session measuring its own runtime, relayed by Rohan. These are
Codex's claims about Codex, not our measurements. Its own UNVERIFIED marks are
preserved. Treat as a strong but unaudited source.

**`--yolo` IS FULL BYPASS. It is not narrower.** Hidden flag: `codex --yolo
--help` succeeds but no help output lists it. Measured at runtime with an
intentionally invalid model so settings were emitted before any model work:
`approval_policy=never`, `sandbox_policy=danger-full-access`,
`permission_profile: Disabled`. **Identical to
`--dangerously-bypass-approvals-and-sandbox`.** Live `--yolo` sessions
corroborate in `state_5.sqlite`: `approval_mode=never`,
`sandbox_policy={"type":"disabled"}`.
**AND A RESTRICTING FLAG DOES NOT RESTRICT IT: `--yolo --sandbox read-only`
still resolved to `danger-full-access`.** For the broker: a sandbox argument is
not evidence of a sandbox. Verify the RESOLVED policy, never the flags passed.

**`codex app-server` is PER-INVOCATION, not machine-wide.** This CORRECTS an
orchestrator claim that starting it was a machine-wide state change.
- Plain `codex app-server` is a foreground, per-invocation server, stdio by
  default (also `unix://`, `ws://IP:PORT`). Starting one would NOT interrupt or
  reconfigure existing sessions.
- A separate `codex app-server daemon start` IS a per-user shared daemon. None is
  running (`app-server-control.sock` refuses).
- The ChatGPT Desktop app runs its own `codex app-server --listen stdio://` with
  process-local socketpairs, not a discoverable socket.
- **Schemas can be generated WITHOUT starting anything:** `generate-json-schema`
  and `generate-ts` produced 411 JSON / 812 TS files (experimental), 295 / 688
  (stable). Protocol is JSON-RPC, API v2.
- Caveat from the source: the generated `JSONRPCRequest` schema requires id,
  method, params but does NOT require `jsonrpc: "2.0"`. Standalone stdio framing
  UNVERIFIED.

**The native multi-agent tools are NOT externally callable.** `spawn_agent`,
`send_input`, `resume_agent`, `wait_agent`, `close_agent`, `list_agents` do NOT
appear in the 153 experimental ClientRequest methods. They appear only as
camel-case fields inside `collabAgentToolCall` payloads describing INTERNAL tool
activity. **This kills the hope of reaching Codex's own agent mesh from outside.**

**What IS externally callable, and it matters:** `thread/start`, `thread/resume`,
`thread/fork`, `turn/start`, **`turn/steer`**, `turn/interrupt`. So an external
client can address a persisted thread UUID and request a new reply, with replies
arriving as notifications (`item/agentMessage/delta`, `turn/completed`).
End-to-end against an already-running thread in a different app-server process is
UNVERIFIED.
**`turn/steer` vindicates nxb-002's scoping guard.** That worker insisted its
result proved only that `codex queue` cannot reach a turn in flight, and refused
to let "Codex cannot be steered mid-task" become canon. There is a named steer
method. Had the guard not been added, the broker would have been designed around
a limitation that does not exist.

## nxb-010 (H2 BUILT, Codex) — three more refusals died

- **F-15 was structurally incapable of firing.** "Kill the child if no start
  signal within the timeout" implemented as check-clock-then-blocking-readline
  cannot fire against a child emitting zero bytes. Hung 2 minutes on an 8s
  budget. Needs an explicit clause: **the wait MUST be non-blocking**, because
  the natural implementation of the refusal cannot enforce it.
- **F-15b (new):** kill only processes you hold a direct handle to, never by
  command-line pattern. Now enforced by an AST test rather than documented.
  That test's first version scanned raw text and failed on the comment
  explaining the rule — a live demonstration that grep-shaped checks produce
  false REDS as well as false greens.
- **F-16b (new): a child SIGINTed for missing its start signal EXITS 0.** A
  broker keying on exit code records SUCCESS for a process it just killed for
  never starting. Only two signals are truthful here: presence of
  `thread.started`, absence of the `-o` file. Generalised: **the exit code is
  reliable for a turn that RAN and meaningless for one that never BEGAN**, and a
  capability declaration must say which of those a signal covers.
- New vanish points **20-22**: a timeout implemented around a blocking read;
  pattern-based cleanup reaping other tenants; a killed child reporting success.
- **`contract.json` blocks its own successor:** `receipt.hop` is a closed enum
  `["H1"]`, so an H2 receipt cannot validate. H2's schemas went into an additive
  `contract/h2.json` instead, leaving nxb-009's blind test untouched. **Widen the
  enum once nxb-009 reports.**

## THE SOL/LUNA DIVERGENCE DOES NOT CURRENTLY REPRODUCE

On nxb-010's live thread: pinned `gpt-5.6-luna`, recorded `gpt-5.6-luna`, and
`config.toml` now reads `gpt-5.6-luna`. This does NOT make nxb-002 wrong; that
worker read the file at a different time and fixed / transient / misread cannot
be distinguished. **Design consequence: the `identity_baseline` machinery exists
to tell systemic divergence from per-dispatch divergence, and there is currently
no systemic divergence to baseline.** Building it now is building against an
unobserved condition. **Keep R-030 and R-031 (pin the model, record what was
reported) — cheap and correct regardless. DEFER the baseline until a divergence
is observed twice.**

## nxb-007: the disagreement thesis, material collected and blinded

10 questions (6 keyed against answers we measured this week, 4 open judgement)
plus 5 planted-defect artefacts. Every question set and key was COMMITTED BEFORE
the collection it governs. 36 runs, 36 exit 0, zero refusals.

**THE CONTAMINATION CATCH THAT WOULD HAVE SILENTLY RUINED IT.** `MEMORY.md`
contains, in plain text, the literal answers to THREE of the six keyed
questions. Claude Code's auto-memory is scoped by working directory, so had both
runtimes been run from a directory under `/Users/rohan`, **Claude would have sat
an open-book exam and Codex a closed-book one, and the result would have looked
clean while being noise.** Both runtimes were run from an empty `/private/tmp`
directory and the cleanliness was MEASURED, not assumed: a headless probe asked
directly and returned NO; Codex's AGENTS.md is 0 bytes and its memories table
has 0 rows. **Anyone re-running this from under `/Users/rohan` gets a worthless
result that will not look worthless.**

**SAME-RUNTIME CONTROLS were added unprompted, and they are the comparison to
read first.** The orchestrator's design never tested its own null hypothesis:
with cross-runtime pairs alone, "A and B differ substantively on six of ten"
cannot be separated from ordinary run-to-run variance. 4 of 14 question pairs
and 2 of 7 defect pairs are same-runtime, mixed into the same numbering.
**If the same-runtime pairs diverge as much as the cross-runtime ones, the thesis
is not supported by this data no matter how the cross pairs read.**

Cost, single sample each: Codex mean 35.8s (median 24), Claude mean 57.8s
(median 59). Claude 2.79 USD / 18 runs = ~0.155 USD per answer. **Codex exposes
NO dollar figure** (plan auth, marginal cost is plan capacity), and the worker
declined to invent one.

**Two ways this is still rigged, neither fixable by the collector:** effort is
NOT matched (Codex ran xhigh, Claude at headless default) so token counts are not
like-for-like; and output length differs ~3x in Claude's direction, so **a judge
that equates length with thoroughness produces a predetermined result.**

Self-corrections from the collector: **the `-m` pin IS honoured** (every thread
spawned with explicit `-m gpt-5.6-sol` recorded sol), so the earlier divergence
is specific to relying on the CONFIGURED DEFAULT, and sol/luna are distinct
catalogue entries, not aliases. And a suspected Codex hang did not happen; it was
a misread `ps` snapshot of a process mid-exit. Zero hangs in 24 runs with
`< /dev/null`.

## nxb-008 BRIEF (do not lose these)

1. **Point the judge ONLY at `evidence/nxb-007/pairs/` and
   `evidence/nxb-007/defects/`. NEVER the parent directory.** DEFECTS-KEY.md,
   SCORING-KEY.md, KEY-DO-NOT-SHOW-JUDGE.json and QUESTIONS.md all sit in
   `evidence/nxb-007/` and any one of them ends the experiment. A path is safer
   than a request.
2. Tell it same-runtime controls exist; **never tell it how many.** Knowing the
   count lets it guess.
3. **Judge substance, not volume.** One runtime's answers are ~3x longer.
4. **The key may be wrong.** D3 is flagged CONTESTED: our device measurement says
   the button fires, the widely taught answer is the opposite. An answer
   reasoning the other way is defensible, not careless, and may be recorded as
   disputed. More generally: if the judge finds something real that the key calls
   a decoy, **doubt the key, not the answer.**
5. **CODEX judges the same material blind as well**, and the two judgements are
   compared. Every worker here is a Claude instance, and a Claude judging whether
   Claude differs usefully from Codex is the bias this project exists to route
   around.
6. **PATH DISCIPLINE IS NOT A BOUNDARY FOR AN AGENT WITH A SHELL.** Pointing a
   judge at `pairs/` does not stop it walking up to the key, and a judge told
   "review these pairs" has an honest reason to look around for context. It would
   not be misbehaving; the run would just be silently worthless. Worse, per
   nxb-002, **a blocked read produces NO event in the stream**, so a failed reach
   is undetectable too. **ISOLATE THE MATERIAL: copy `pairs/` and `defects/` into
   a fresh directory outside this repo containing nothing else, and run each
   judge there with the working directory set to it and read-only sandboxing.**
   Applies to the Claude judge as much as the Codex one.
7. **Both judges are judging material they wrote half of.** Neither is blind to
   its own prose across 21 pairs, and self-recognition is likelier on the keyed
   questions. The brief therefore requires each judge to REPORT any sense of
   authorship per pair, so the agreement number can be read knowing whether the
   judges agreed because each recognised and favoured itself.
8. **The brief must be BYTE-IDENTICAL for both judges** or judge disagreement is
   confounded with brief difference. It is written and committed at
   `docs/JUDGE-BRIEF.md`, authored by the ORCHESTRATOR — not by the collector,
   who wrote the artefacts and the key and could leak through prompt wording.
9. **Pin the Codex judge's model explicitly with `-m`** and record what the thread
   reports. The configured-default path is exactly where sol resolved to luna.

## nxb-009: two high-severity defects, and the experiment was not blind

**C-1: THE CANONICALISATION DIVERGES ON ONE KEYWORD ARGUMENT.** Both
implementations independently chose the same algorithm, `sha256` over
`json.dumps(units, sort_keys=True, separators=(",",":"))`. They differ on
`ensure_ascii`: one takes Python's default True, the other sets False.
**Identical on ASCII, divergent on ANY non-ASCII byte.**
`[{"summary":"café"}]` gives `c7d8118f...` vs `90414d08...`.
F-8 refuses on digest divergence and never resolves it, so a dispatcher on one
implementation and a broker on the other **refuses every envelope containing an
accent, an emoji, a smart quote or any non-Latin text, and reports
`digest_divergence`, which points at truncation rather than the cause.** 71 tests
on one side and 17 on the other catch none of it. **Naming the algorithm is
provably insufficient: the contract must publish the canonicalisation AS BYTES.**

**B-1: THE RETRY PATH MANUFACTURES A FALSE GREEN.** A repeated `dispatch_key`
whose ORIGINAL dispatch was REFUSED returns `OBSERVED` in the reference
implementation and `REFUSED` in the independent one. The reference is wrong:
`REFUSED` is defined as a positive assertion that the dispatch did not happen.
And it lands on the load-bearing mechanism — **R-051 exists so a dispatcher that
got UNKNOWN can retry safely, and under the reference that dispatcher retries,
receives OBSERVED, and proceeds when the work was refused.** The reference's test
suite never dispatches a refused key twice, so it passes.

Also: C-6, the SHIPPED system cannot dispatch at all through the published data
path. No field or procedure exists for proving liveness, so F-6 through F-11 and
R-051 are reachable only by writing a synthetic timestamp in a test.

**Cost of one cross-runtime check of one hop:** 688s wall, ~1.14M tokens, about 2
points of a weekly Codex window. It returned two high-severity defects that four
documents and 71 passing tests had not.

## THREE ORCHESTRATOR ERRORS THIS TASK EXPOSED

**1. THE BLIND TEST WAS NOT BLIND, AND IT IS THE ORCHESTRATOR'S DESIGN FAULT.**
`contract.json`'s `invariants[].enforced_by` publishes the reference
implementation's private structure: `nxb.dispatch._observe`,
`nxb.ledger.find_by_dispatch_key`, "PRIMARY KEY is receipt_id". Codex's first
planning message, before writing anything, proposed "a dependency-free Python
package (nxb)" and then produced `nxb/dispatch.py`, `nxb/ledger.py` with
`_observe` and `find_by_dispatch_key`. **You cannot blind an implementer against
a reference whose module and function names are printed in the spec. Every
structural convergence in nxb-009 is worthless as evidence.** Move `enforced_by`
out of the published contract, or restate it as a RULE rather than a symbol path.

**2. "WHERE IMPLEMENTATIONS DISAGREE IS WHERE THE CONTRACT IS AMBIGUOUS" IS THE
WRONG DETECTOR.** C-1 is a place where both AGREED at the level of description
and diverged at the level of BYTES; a code diff shows two functions that look
the same. **The right detector is a DIFFERENTIAL TEST OVER ARTIFACTS: generate
envelopes, run both implementations, diff the receipts and returns.** That finds
C-1 in seconds and generalises to every future hop. The rule also OVER-reports:
B-1 was not ambiguity, it was one implementation plainly wrong about a clear
clause. Disagreement is neither necessary nor sufficient for ambiguity.

**3. THIS DID NOT TEST THE DISAGREEMENT THESIS AND WAS BEING COUNTED AS THOUGH IT
DID.** What the independent implementation won on — binding an orphan vocabulary
term, giving an unreachable state a job, inventing the missing liveness
procedure — **are the moves of a fresh careful reader, not of a different
cognitive architecture. Nothing about them is GPT-shaped.** A second CLAUDE
instance building blind would plausibly have found the same three, because the
mechanism was BLINDNESS AND FRESHNESS, not model diversity. **What nxb-009
actually measured is the value of independent re-implementation, which is real
and worth buying. To test the project's premise you need a THIRD ARM: the
identical blind build by a Claude instance, then compare all three. If
Claude-blind finds roughly what Codex-blind found, the cross-runtime premise is
not carrying its weight and this broker is solving a cheaper problem than
advertised.**

**And the independent implementation's readings are BETTER than the reference on
three points** (UNKNOWN semantics, the liveness-proof procedure, the null-reason
gate). It was framed as a by-product; treating it that way risks discarding
fixes already paid for.

## HANDOFF AUDIT (nxb-026) — 17 accurate, 2 absent, 3 wrong or stale

**FILING IS NOT THE FAILURE MODE. DRIFT AND DISTANCE ARE.** A checklist asking
"is it in the file" would have PASSED the most dangerous defect found.

- **Absent, both claimed as recorded and neither filed:** "a claim about a file
  must name the file", and "guards scale, reviews do not". Now written in.
- **Counts restated in prose rotted within a day** (40/33/8/18 in three places
  against a real 27 open of 42, 0 unowned). Fixed by POINTING AT `FINDINGS.json`
  rather than by updating the numbers — the file's own rule about test fixtures
  applied to itself. A count in prose is a second copy of data that lives in a
  file.
- **A section said "SCOPE CORRECTED BELOW" with the correction ~220 lines away,
  while its own body still stated the uncorrected claim confidently.** A
  successor reading in order acts on the wrong thing. Now cross-referenced inline.
- The alarm entry reads correctly as it stands.

**A FIX CAN LAND CORRECTLY FROM A FALSE PREMISE.** The F4 work deleted the right
function and exposed the right alarm for a reason that was wrong. Afterwards that
reads as confirmation. **It is the hardest error to notice, because nothing fails
and the outcome is good.**

**The findings ledger had no honest state for a reversal.** FIXED asserts a defect
existed; WONTFIX asserts a real thing was deprioritised. REVERSED was added when
the mechanism met its first reversal — found by use, not by review.

## THE WORKING TREE IS NOT CLEAN. DO NOT TIDY IT.

**RUN `git status` YOURSELF. Do not trust any enumeration of paths, including
this one.** Worker 2 has uncommitted work in flight (nxb-025, the negative
signal: a new `nxb/failsignal.py` plus edits wiring its `detect` into the
adapter, canary, hops and contract). **The list of touched files GROWS while that
work continues** — one check saw seven paths, a check minutes later saw nine, and
both were correct when taken.

**Do NOT stash, reset, checkout or `git add -A` any of it.** This repo has already
had its shared index swept twice by an orchestrator committing another session's
staged files. Leave it until Worker 2 reports.

### A CLAIM ABOUT A LIVE WORKING TREE EXPIRES THE MOMENT IT IS MADE

The orchestrator told Rohan the tree was clean without looking. A worker checked
and it was not. The orchestrator then re-checked, found more files than the
worker had reported, and filed that as the worker miscounting. **It had not: the
tree changed between the two checks, provable from mtimes.**

**Naming the file is NOT sufficient when another agent is editing concurrently.**
Either a claim about mutable state carries the time it was taken, or the reader
re-checks instead of trusting the snapshot.

The behaviour to copy is the orchestrator re-checking rather than accepting the
report — that is what caught the drift. The behaviour to avoid is concluding
"count more carefully", which was not the failure and would not have helped.

## SUCCESSOR ORCHESTRATOR: START HERE

1. Read `HANDOFF.md`. It is 1145 lines, 77 sections, no index. **Before acting on
   any section, search for that topic's OTHER mentions** — a later section
   sometimes corrects an earlier one from hundreds of lines away while the
   earlier one still reads confident and complete.
2. Read `FINDINGS.json` for live state. Never trust a count written in prose.
3. Read this ledger for task history.
4. Nothing needs to transfer from the previous orchestrator's context.

## RECOMMENDED NEXT TASK (not dispatched)

**A mechanical check that a ratified claim has a file behind it.** The nxb-026
audit could only verify rules the orchestrator thought to LIST; anything believed
recorded but not listed is unchecked, and by construction that is the set most
likely to be missing. Same shape as the never-read guard and the findings ledger.
Also unbuilt: nothing cross-checks `HANDOFF.md` against the ledger or the
contract, so a rule can be filed and then contradicted by a later rule without
either changing.

## ORCHESTRATOR 2 TAKEOVER, and three facts the handoff did not have

Orchestrator 1 handed off at 91% context. Rohan's goal, his words: finish it end
to end so NexusV3 replaces NexusV2 in actual use.

Verified independently before dispatching anything, rather than relayed:
tree clean at `a1ad578`, `python3 -m pytest tests/ -q` 156 passed / 281 subtests,
`nxb/adapters/` contains `codex.py` and `__init__.py` only.

**Three facts found by reading, that change what the adapter task is.** All
three post-date the documents that describe this runtime, which is the founding
defect of this project wearing its usual costume: a capability sheet written once
and then trusted.

1. **`--json-schema` exists on Claude Code CLI 2.1.251.** Read in `claude --help`:
   "JSON Schema for structured output validation." It is the direct analogue of
   Codex's `--output-schema`, so `nxb/h3.py:report_json_schema()` can constrain a
   Claude Code report structurally instead of the broker parsing prose.
   `contract/runtimes/claude_code.json` and HANDOFF.md were both written without
   it. Dispatched to nxb-027 as a claim to VERIFY, not to build on: a flag in
   `--help` is a sentence someone wrote, which is the thing this project exists
   to stop trusting.

2. **`nxb/proof.py:codex_evidence_verifier` is misnamed, not Codex-specific.**
   Claude Code writes `~/.claude/projects/<cwd-slug>/<session_id>.jsonl`.
   Verified on `/Users/rohan/.claude/projects/-Users-rohan/02fd2e0c-6af9-4a79-96b4-275c6d56728c.jsonl`,
   whose first line carries `"sessionId":"02fd2e0c-6af9-4a79-96b4-275c6d56728c"`.
   The verifier requires the ref in the basename AND in the content; both hold.
   So the canary's proof requirement, an artefact the runtime wrote and the
   broker did not, is already satisfiable for Claude Code.

3. **`contract/runtimes/claude_code.json` has NO registrable declaration for a
   spawned child.** Both declarations describe the peer-messaging path: their
   `spawn` field is `SendMessage(to=<ref>, ...)`. `without_broker_inbox` carries
   `start_signal: null`, which `nxb/runtimes.py:register()` refuses under F-1.
   A third, spawn-shaped declaration is needed, and its start signal is the
   `system/init` frame on the child's own stdout, which the broker owns and which
   needs no inbox at all. Assigned to nxb-027.

**A count in this entry would be a second copy of `FINDINGS.json`**, so there
isn't one. The handoff message quoted figures that the file disagreed with when
I read it minutes later, which is "a claim about mutable state expires when it
is made" firing on the handoff itself.

## DISPATCHED: nxb-027, nxb-028, nxb-029 (parallel, independent)

Grouped by work type rather than by severity, per the rule that cost half a
dispatch when eight findings were treated as one kind of work.

- **nxb-027, Worker 3, FIXABLE:** build `nxb/adapters/claude_code.py`, spawn
  shape, to the interface `nxb/h2.py`, `nxb/roundtrip.py` and `nxb/canary.py`
  already call. The one real structural divergence: Codex writes its final
  message to `-o <path>` and `nxb/h3.py:collect_report` reads it, treating
  absence as failure under F-14. Claude Code has no `-o`; the answer is in the
  `result` frame on stdout, so the adapter must produce `out_path` itself while
  preserving F-14's asymmetry.
- **nxb-028, Worker 1, INSTRUMENT:** a runtime-agnostic adapter conformance
  suite, written WITHOUT reading Worker 3's implementation and committed before
  it is run against it. Built on "the author's tests do not test the author" and
  "guards scale, reviews do not". `CodexAdapter` must pass it unmodified.
- **nxb-029, Worker 2, DECISION INPUT:** does Claude Code's `result` frame
  populate `permission_denials` when a tool is ATTEMPTED and DENIED? W3-9 is
  recorded at HANDOFF ~line 1134 as never fixable, but that rests on a
  Codex-only measurement, and ~line 194 still carries the "on the measured Codex
  surface" qualifier the later summary dropped. If the field populates, W3-9
  narrows from a property of brokering to a property of one runtime, and Rohan
  is being asked to rule on a different question than the one he was handed.

**Deliberately NOT re-asked of Rohan yet: W3-9.** Orchestrator 1 put two options
to him and got no answer. Re-asking the same question adds nothing; nxb-029 may
change the question. The other two items that are his stay his: W3-11, the
permission boundary, and a fresh pane for the blind arm.

## ORCHESTRATOR 3 TAKEOVER (2026-08-30)

Verified before acting, not relayed: tree clean at `70f6c95`; fast suite 339
passed / 581 subtests; rig `nxb-s2` standing with all five panes live (screens
read directly -- Orchestrator and both CX workers still show their ENROLLED
acks, CX Worker 1 still shows its wrong-worker refusal from the six-case run).

**This ledger lagged from nxb-029 to nxb-051 under Orchestrator 2.** Task
history for that span lives in `git log` and `FINDINGS.json`, not here.

## nxb-052 (orchestrator-executed): RIG-4, the standing rig is discovered, never assumed

The handoff's named live blocker ("mint cannot see Codex panes") failed to
reproduce: minting for `CX Worker 1` with `--session nxb-s2` ISSUED on the
first try. The real defect was the `--session` default (`nxb`) drifting from
the standing rig (`nxb-s2`), with refusals that blamed the roster and a remedy
that would have stood up a second rig. Filed FIXED as RIG-4 with check
`rig_4_dispatch_defaults_find_the_standing_rig`.

Change: `mint` counts every rig recorded next to the ledger; `rig send`
resolves the one standing rig, refuses `keystroke_ambiguous_rig` (published in
contract/rig.json) when two stand, and names the standing rigs when told a
wrong session. Suite 345 passed / 586 subtests. Probe-minted ids
nxbt-8bff70861b1a42b9 and nxbt-2c729d6e22d2409f revoked after verification.

## nxb-053 (orchestrator-executed): RIG-5, the answer comes back

**Raised by Rohan**, mid-demonstration, against a dispatch that had just
succeeded: if the worker got it wrong, who catches it? Nothing did. `rig send`
typed and returned; no reply was ever read back, and nothing correlated a
reply to its task. The orchestrator had read the pane and verified the answer
independently, but both were discipline, not mechanism, and neither was
recorded.

Built: a reply protocol on every automated directive asking for
`[NXB-DONE <task_id>]`, `rig collect` to read it back bounded by that marker,
`capture_history` so a long answer is not silently truncated to the visible
screen, and one shared `_resolve` so send and collect can never disagree about
which pane a worker is. WAITING exits 4 and carries the pane tail, because a
worker still working and a worker that refused look identical from outside.

**The first live collect was a FALSE GREEN** (returned the echoed directive as
the answer, because the directive names the marker in order to request it).
Fixed by search order; regression guard proven by reproducing the old order and
watching it report ANSWERED on an echo-only pane.

VERIFIED LIVE, both runtimes: CX Worker 1 (codex) and CC Worker 2
(claude_code), each answer carrying its own validate call as evidence. Suite
352 passed / 588 subtests.

Also filed **RIG-6, OPEN, high**: `rig clear` very likely discards a Codex
pane's typed enrolment rule while the rig state keeps reporting it enrolled.
Derived from the code and NOT measured, so deliberately not fixed blind, and
deliberately not taught to Rohan as a usable verb until it is settled.

## nxb-054 (orchestrator-executed): the orchestrator learns its job, and six bugs from one live lesson

Rohan ran the workflow himself, by hand, as a cold operator, with the
orchestrator only teaching. **That single session produced more defects than
any instrument this project has built.** Every one was found by using the
thing, not by testing it.

- **RIG-7 (high), his finding, and the important one.** The orchestrator seat
  was being handed the WORKER rule, so nothing anywhere knew that mint, send
  or collect existed. His words: "I am NOT going to do this by hand thats
  stupid and inefficient." Fixed with an orchestrator brief typed at stand-up,
  plus `rig orchestrate` to brief a pane in a rig already standing, plus
  `rig workers` because nothing printed the live fleet -- the only way to see
  it had been to trigger a mint refusal and read the roster out of the error.
- **COLLECT-1 (high).** A Claude pane scrolls its transcript internally, so
  yesterday's collector anchor vanishes and it reported a landed dispatch as
  never having landed. Found within one dispatch of shipping RIG-5.
- **RIG-6 (high).** clear() discarded a Codex pane's typed rule while the
  state kept reporting it enrolled. Now re-typed and re-confirmed, and any
  pane that will not acknowledge is downgraded and named.
- **RIG-8.** tmux prefix-matches session targets: `rig down` defaulting to
  `nxb` killed his `nxb-s2` and reported a session that never existed.
- **RIG-9.** A Codex update prompt nobody had seen turned a readiness check
  into a 60s sleep with a useless verdict.
- **RIG-10.** The trust-prompt remedy said "re-run", which refuses, and was
  wrong for one of the two runtimes anyway.
- **RIG-11.** No revoke verb existed, so 20 ids for dead workers and torn-down
  rigs were still valid. Revoked.

Suite 352 passed / 597 subtests. Orchestrator brief verified live on the
standing rig: BRIEFED and acknowledged.

**The lesson to carry: this project measures itself constantly and none of its
instruments found any of these. An operator using it for twenty minutes found
seven.** "Nobody has run this as a user would" was filed as a gap weeks ago
and closed on paper; it was not closed until today.

## 2026-09-03: THE LOOP CLOSED. First end-to-end cross-runtime dispatch.

One sentence from Rohan to a Codex orchestrator pane, in plain language, with
no command typed by him:

  "Ask CC Worker 1 and CX Worker 1 how many files are in ~/workspace, then tell
   me whether they agree."

The orchestrator listed its fleet, minted two ids, dispatched to a Claude
worker and a Codex worker, collected both, and reported: **they agree, 13,279
files each.**

VERIFIED INDEPENDENTLY rather than accepted, per this project's own rule that
an orchestrator holds a summary and the panes hold the measurement:
- ledger: two distinct ids issued at 18:45:54Z, one per worker
- `%1` shows 13279 and `[NXB-DONE nxbt-b8876241a3da4dea]`
- `%3` shows 13279 and `[NXB-DONE nxbt-91cd062fb9994628]`
- a THIRD count, taken outside the experiment: `find ~/workspace -type f` = 13279

Every hop is now real: roster ceiling, minted id, typed dispatch, worker-side
validation, marker-correlated collection, cross-vendor comparison.

**What this closes.** HANDOFF has carried "NOBODY HAS RUN THIS AS A USER WOULD"
and "THE LOOP IS CLOSED FOR THE EASY RUNTIME ONLY" for weeks. Both are now
false. It also closes the founding thesis in the smallest possible instance:
an Opus worker and a GPT worker, dispatched by a third model, independently
agreeing on a checkable fact.

**And the honest measure of the day.** Nine defects were found between 12:00
and 14:45 (RIG-6 through RIG-15, COLLECT-1), every one by USING the system --
seven by Rohan operating it cold, two by the freshly briefed orchestrator on
its first real dispatch. In the same window this project's own instruments --
377 tests, a never-read guard, a leak guard, a vocabulary-drift guard, a
findings ledger with executable checks -- found exactly two: the vocabulary
guard caught an unpublished refusal, and the one-line-command guard caught a
launch command that newlines would have broken. Both catches were real and
both were of MY OWN work made minutes earlier.

The ratio is the finding: instruments catch what someone thought to assert;
an operator catches what nobody thought of. This project measured itself
constantly and shipped an orchestrator that had never been told its own job.

## nxb-060: the fleet is composable, and two rigs run side by side

Rohan asked for two things after the first end-to-end run: parallel rigs, and
a configurable shape ("maybe im low on claude code usage so i want a claude
code orchestrator and 5 workers are codex"). Both delivered; four defects
surfaced getting there, three of them found by attempting the thing.

- **RIG-16 (high), found by READING before spending a stand-up.** RIG-7 had
  been fixed only on the typed path, so `launch_command` ignored `role` for
  claude_code entirely and a Claude orchestrator would have launched with the
  WORKER rule. It survived because every rig ever built seated Codex in that
  chair, so that branch had never been taken. DECL-1's lesson again: the
  most-used path hides the least-used one.
- **RIG-17.** `SCENARIOS` was a one-entry table in Python. `--orchestrator cc
  --workers cx:3` now composes at the prompt. The table was the only limit.
- **RIG-18 (high), found by standing the second rig.** Both rigs contain a
  "CX Worker 1", and a ticket names a WORKER, not a rig, so an unscoped mint
  would have issued into the wrong fleet and the worker would have validated
  it. Now refused by name, and every command in an orchestrator's brief
  carries --session.
- **RIG-19 (high), a near-miss.** The rule was typed into a shell, and a pty
  drops input past ~1024 bytes. Measured: 1000 arrives, 2000 never reaches
  the shell. The worker rule's command was 1014. TEN BYTES, recorded nowhere.
  The orchestrator brief at 3891 had already crossed it and failed loudly,
  which is the only reason the near-miss was found at all. Rules now live in
  `~/.nxb/briefs/` and the typed command is ~150 bytes forever.

**A discipline note worth keeping.** The pane capture appeared to show a
mangled rule on a LIVE worker ("You re the worker", "if nd only if"), which
read as active corruption of the fleet. Reading the running process's own
argv showed it intact at 1035 bytes. `capture-pane` renders a screen; argv is
the fact. A false alarm, avoided by asking the authority instead of the
display, and it would have been a loud and wrong finding.

VERIFIED with both rigs standing: `nxb` (codex orchestrator, 2 CC + 2 CX in
~) and `lab` (claude orchestrator, 3 CX in ~/dev). Separate sessions, separate
rosters, ambiguous mint refused with both rig names, scoped mint issued.
Suite 365 passed / 642 subtests.

## nxb-061: RIG-20, a name carries its rig

Rohan, on the ambiguity refusal shipped minutes earlier: "that hazard is
easily solvable tho no? you just change the name ... to adding the rig number
to it". Right, and it replaced a guard with an invariant.

**The distinction is the finding.** RIG-18 DETECTED a collision and refused.
A refusal that fires during ordinary operator use is a design conceding it
could not make the bad state impossible. This project already holds that a
rule binding a PERSON decays while one binding a FILE holds; an invariant is
that idea one level up. The refusal is kept and is now unreachable in normal
use, firing only on a naming regression -- which is the single thing that
could bring the collision back.

Three consequences beyond the rename:
- `--session` stops being needed to say WHO you mean. send and collect find
  the rig holding the name, because no two workers anywhere share one.
- The ORCHESTRATOR collided too, and was easy to miss because there is only
  ever one per rig.
- Naming is applied at STAND-UP, not baked into scenarios, so a scenario stays
  a SHAPE and the rule lives in one place.

VERIFIED with both rigs standing: `nxb` (codex orchestrator, 2 CC + 2 CX) and
`lab` (claude orchestrator, 3 CX). Zero name overlap. mint -> send -> collect
ran end to end against "lab CX Worker 1" with NO session flag anywhere, and it
answered MANGO. Suite 370 passed / 662 subtests.

**A near-miss worth recording, because it would have been a loud wrong
finding.** The collect output failed to parse in a shell loop and read as
nxb emitting malformed JSON. Saved to a file it parsed perfectly: the mangling
was my own `$(...)` pipeline. Ten seconds of checking separated a real defect
report from a false one, on the same day a pane capture nearly convinced me a
live worker's rule was corrupted when the process argv showed it intact.
Twice in one session, the DISPLAY lied and the AUTHORITY did not.

## nxb-062: the studio — a fleet composed on a canvas, standing up in tmux

Rohan chose the harder option: drive tmux from the browser, not emit a command
to paste. "i know its difficult but i also belive in you."

**Architecture, and the constraint that decided it.** A hosted page cannot
reach this machine -- browsers block cross-origin requests to 127.0.0.1 and a
published artifact runs under a policy forbidding them outright. So nxb serves
the page itself from loopback and it talks to its own origin. `nxb studio`
starts it, prints a tokenised URL, and opens it.

**Treated as a weapon, because it is one.** This endpoint spawns `--yolo`
agents, and "only on localhost" is not a boundary: every page in his browser
can POST to 127.0.0.1. Four guards, all tested: loopback bind, a per-run token
required on EVERY request including the page load, a loopback-only Host check
against DNS rebinding, and `compare_digest`. The security tests were written
before the surface was driven, which is the opposite of this project's usual
order and deliberate.

**STUDIO-1, found by a test before the surface was used.** `compose()`
validated the orchestrator's runtime and trusted the workers', because its
only caller ran them through `parse_workers` first. The studio is a second
caller that does not, so an unknown runtime raised KeyError and the HTTP
handler dropped the connection. A validation that lives in the caller is one
new caller away from being absent, and a second caller arriving is exactly
when nobody re-reads the first one's guarantees.

VERIFIED END TO END through the HTTP API, not through the UI's own claims:
POST /api/rig/up stood up `studio1` (Claude orchestrator + 2 Codex workers,
main-vertical, in ~/dev) READY, alongside `nxb` 5/5 and `lab` 4/4 -- three
rigs, twelve panes, no interference. GET /api/state reported all three plus
the torn-down `nxb-s2` correctly as not standing. POST /api/rig/down removed
it. Suite 383 passed / 669 subtests.

Honestly not built, and named rather than left implied: the studio composes
and tears down. It does NOT yet dispatch, collect, or show what a worker is
doing. That is the live-dashboard half, and it is a bigger piece.

## nxb-063: the studio gets tabs and a palette

Rohan, on seeing v1: tabs like Ghostty, one per rig, and a palette of the four
node kinds to drag from rather than three buttons that only ever made a Codex
orchestrator.

- **Tabs** are drafts, held in localStorage, one rig each with its own name,
  directory, layout and canvas. A tab's dot is green while that rig stands, so
  the tab bar doubles as fleet status.
- **The palette** carries all four kinds, which is what makes a Claude
  orchestrator reachable from the UI at all -- v1's single orchestrator button
  hardcoded Codex, so the RIG-16 fix was invisible from the page that was
  supposed to expose it.
- **Rebuild** replaces Bring-it-to-life when the rig is already standing, and
  tears down first. Standing on top of an existing session would only have
  produced rig_session_exists.

**The reason for the error surface, stated honestly: I could not reproduce
his empty canvas.** His screenshot showed a blank board while the code seeds
three nodes on load. I read the old script several times and did not find it,
and the honest options were to guess at a fix or to make the page incapable of
failing quietly. It now reports every error and rejection into the log strip,
and a test runs its script through `node --check` so a parse error cannot ship
a board that never loads. That is not a claim to have fixed it; it is a claim
that the next occurrence will say what it is.

## nxb-064: the studio becomes an app, and the token had to stop rotating

Rohan: strip the prose from the sidebar, denser grid, "hyper ghostty themed",
and make it an app with Cmd+T rather than a localhost tab.

- **Theme** taken from his own terminal rather than from a generic dark
  palette: plum ground, mauve prompt accent, and the bright tmux status line
  he reads all day, reproduced at the bottom with `[rig] n panes` on the left
  and `"host" HH:MM DD-Mon-YY` on the right. The grid is now a terminal-cell
  pitch with a coarser rule every fourth cell.
- **Sidebar is standing rigs and nothing else.** The honesty note about node
  positions was not deleted -- it moved onto the layout selector's tooltip,
  which is the control that actually decides the arrangement and therefore
  where the question gets asked.
- **App**: a web manifest plus `--app`. He has only Safari, whose Add to Dock
  is the better route on macOS anyway and is already how his Gmail and YT
  Music "apps" work.

**THE BLOCKER THAT MADE THE APP REAL, and it was not the UI.** Add to Dock
FREEZES a start URL. A per-run token -- the safer default, chosen deliberately
in nxb-062 -- would have turned yesterday's Dock icon into a 403 every single
morning, and the failure would have looked like the app being broken rather
than like a security decision. The token is now persisted 0600 next to the
ledger, with `--fresh-token` to rotate. Same trust boundary as the ledger
itself: anything that can read that file can already run nxb directly.

Also measured and worth stating: a browser fetches a manifest and its icons
WITHOUT custom headers, so those two routes carry the token in the URL. Had
they stayed header-only, Add to Dock would have installed an app with no name
and no icon and nothing would have said why.

## nxb-065: the studio composes AGENTS, and every control had to earn its place

Rohan brought back a mockup from a UI session and asked for it. The rule I
held it to: no control ships that the backend cannot honour, because a
selector that looks like configuration and functions as a comment is this
project's founding defect in a nicer font.

So each was measured against the runtimes' own --help BEFORE any UI was
written: claude takes `--model` and `--effort`; codex takes `-m` and reaches
reasoning effort through the same `-c model_reasoning_effort` key its
config.toml already uses. Both are now real, per agent, alongside a custom
name, per-agent working directory and startup instructions.

**What was refused rather than mocked up.** Pane preview says out loud that it
is not built, because an invented picture of a tmux layout is a diagram that
lies. Activity is the log strip rather than a fabricated feed. Attach copies
the tmux command rather than pretending a browser can attach a terminal.

**STUDIO-3, and it is the sharper of the two.** I shipped a closed model
dropdown typed from memory. The plumbing was right and the VALUES were
invented: the rig came up READY while its Codex pane sat on a 400, "The
gpt-5.6 model is not supported". A test of the flag plumbing would never have
caught it, and a closed picker presents an invented list with the authority of
a discovered one. Codex's suggestions now come from the operator's own
config.toml and both fields are free text.

**How it was caught matters more than the fix: I read the pane after the
stand-up instead of trusting READY.** The rig genuinely was READY -- every
pane booted, was named and was enrolled. READY is a statement about the RIG,
never about whether the agent inside can reach its model, which is the same
distinction this project already recorded for `thread.started`.

VERIFIED by standing the mockup's own fleet through the API and reading the
processes: `claude --model opus --effort xhigh`, `codex -m ... -c
model_reasoning_effort=xhigh`, and the Claude pane reporting "Opus 5 with
xhigh effort" on its own screen. Suite 392 passed / 683 subtests.

## nxb-067: the studio's four rough edges, and a scope ruling that removed the fifth

Rohan went through the honest problem list I had given him before pushing.

**He ruled the biggest item out of scope, and the reasoning is his.** I had
filed "the studio cannot dispatch or collect" as its largest gap. His answer:
"thats not a problem the pane should be open at all time so i can be the human
gate this setup is just to architect the workflows BEFORE using them once they
are created i go to tmux and work from there." Filed WONTFIX, owned by him,
with the reason recorded. The studio designs and stands up; tmux is where work
happens. It also keeps the gate where he wants it -- work reaches a fleet in
front of him, not through a browser button that could fire while he is looking
elsewhere.

- **STUDIO-5.** The live chip matched a node's CURRENT label against the
  running panes, so renaming a drawn node made a working pane read as a draft.
  Nodes are stamped with what they were DEPLOYED as; a node whose label has
  moved on reads "edited" rather than claiming either state, because neither
  is true. General shape: identifying a running thing by its display name is
  identifying it by something the operator is free to change.
- **STUDIO-6.** A tab was a drawing with no way back from the machine. Any rig
  can now be opened into a tab, read from the rig's own state, including one
  stood up from the CLI. Tearing a rig down clears the tab's live stamps.
- **STUDIO-7.** No undo. Cmd+Z / Shift+Cmd+Z over snapshots taken before each
  act, with text fields snapshotting on FOCUS -- an undo that walks back one
  character is a typing history.
- Rebuilding a standing rig now asks first, the same one-click hazard the
  tear-down button had.

Suite 398 passed / 687 subtests.

## nxb-068: clean slate, and the record that could never be deleted

Rohan asked to take the rigs down before a live run. Both standing rigs torn
down, five stale records forgotten, four outstanding tickets revoked. tmux is
empty, `~/.nxb` holds no rig files, and no task id issued today is still valid.

**STUDIO-9, seen the moment he asked for the clean slate.** `rig down` keeps
the state file deliberately -- that is how a torn-down rig stays visible and
re-openable -- and nothing had ever removed one. With two rigs standing the
panel listed five; after tearing both down it still listed five. A record with
no delete is a list that only grows, in a project whose stated default is to
scope work as removal.

`rig forget` now exists on the CLI and as the × on a DOWN rig, and REFUSES
while the session stands: forgetting a live rig leaves a running fleet with no
record naming its panes, which is the one state nothing else here can recover
from. The refusal is server-side, so it holds whatever the page believes.

## nxb-069: the model fields existed, reached the runtime, and could not be typed into

Rohan: "currently in studio it is only default model. we need to add model
selection, effort selection as well. this is imperative."

The feature was already built and already worked. Per-node model and effort
had reached real processes that same afternoon -- `claude --model opus
--effort xhigh` read straight out of a running pane's argv. So the natural
reading of his report was that it needed building.

**It needed to stop eating his keystrokes.** Their `oninput` handler called
`paint()`, and `paint()` rebuilds the inspector with `innerHTML`, so the input
being typed into was destroyed on the first character: focus gone, suggestion
list closed, nothing retained.

**The lesson is about how I verified it.** A feature that cannot be OPERATED
is indistinguishable from a feature that does not EXIST -- and my verification
could not see the difference, because I drove the backend through the API and
never once typed into the field. That is how the entire studio was checked.
The operator found it in the first minute of using it, which is the same
result as every other UI defect this week.

Fixed by splitting `paint()` into `paintCanvas()` and `inspector()`: text
fields repaint the canvas only; selects still do a full paint, because
changing the provider must re-render the panel to swap the model suggestions.

Also: the placeholder now names the model each runtime is actually configured
with, read from settings.json and config.toml. "Runtime default" is a word,
not an answer, and an operator cannot decide whether to override a default he
cannot see.

## nxb-070: usage the operator can design against, and a persona library

Two asks, and the first had to be MEASURED before a pixel of it was built,
because Rohan chooses which vendor carries a fleet based on which has
headroom. A fabricated usage figure would not merely be wrong; he would design
against it.

**What the machine actually holds, measured 2026-09-03:**
- Codex records real plan usage in every rollout: used_percent, window,
  resets_at, plan_type. REAL, and local.
- Claude records NOTHING of the kind. The only `rate_limit` string in its
  transcripts is a 429 ERROR record, and its CLI has no usage command. Its
  absence is now REPORTED WITH A REASON, never drawn as an empty gauge that
  reads as zero.
- Tokens are real for both, from the transcripts each writes.

Two numbers kept deliberately apart: a percentage of a plan window is not a
token count, and cache reads are shown apart from input because **97.7% of the
all-time Claude total is cache reads** -- one combined figure would be
alarming and nearly meaningless. Nothing is converted to money, per the
standing rule that consumption here may be plan quota.

**STUDIO-11.** Roles were typed as a first message on every runtime. Claude
has --append-system-prompt, and Rohan's own example is why it matters: an
adversarial auditor is precisely the role a later message would most want to
talk out of its job, and RIG-3 already records that a typed rule decays.
Claude now binds it at launch, Codex still gets it typed, and each pane
records WHICH -- `role_binding: launch|typed`, not a boolean, for the same
reason enrolment does.

**STUDIO-13, the library.** Personas are markdown files in ~/.nxb/personas,
one per role. Prose the operator wrote belongs where he can open, edit and
grep it; a persona in a JSON blob is one he cannot. It grows BY USE: a role
that is not yet saved is offered once after the rig goes up, and never
re-offered afterwards, because a prompt that fires on a no-op is how prompts
get dismissed without being read.

**STUDIO-14, caught by a test rather than by thinking.** The cold token scan
blocked the HTTP handler for 5.5 seconds. The test timed out; nothing else
would have noticed until the first real cold start. A page cannot tell a
five-second handler from a dead server. It now answers `computing: true`
immediately and scans on a worker thread.

Suite 406 passed / 713 subtests.

## nxb-071: it could not be panned, could not be resized, and I had answered the wrong question about Claude usage

Rohan opened the studio on a second monitor: "i cant even drag around the grid
or change the sizing of any of the panes its very frustrating to work with."

Both true. A node dragged past the edge was UNREACHABLE -- there was no pan,
zoom was anchored at the origin, and Fit scaled without panning, so it left
off-screen nodes off screen, which is the entire complaint it existed to
answer. The columns were three hardcoded widths, so a narrower display crushed
the canvas with no way to give it room, and the header clipped Auto layout: a
control he could see half of and could not press.

Now: drag empty canvas to pan, scroll to pan, cmd-scroll and pinch to zoom AT
THE CURSOR, space-drag over a full canvas, a Fit that pans, draggable
splitters that persist and reset on double-click, and everything wraps.

**The shape of both defects is the same one as STUDIO-10, twice in a day:
built and verified through the API by someone who never resized the window and
never typed into the field.**

## STUDIO-17: a negative claim of mine, with the wrong search behind it

Earlier today I recorded that Claude does not record plan usage on this
machine. True of what it WRITES. False of what it will ANSWER: `claude -p
"/usage"` returns session, weekly and per-model percentages in about two
seconds, which is MORE than Codex records.

Rohan proposed a standing session on the Dell to poll it -- a "usage tunnel".
Not needed, and the check that showed it was one command.

**My search was "what is written to disk". My claim was "not available".**
Those are different statements and I published the second. This project has a
rule for exactly that, written after the same overclaim twice before: a
negative claim must state the search that produced it. I broke it while
writing a docstring about not fabricating usage numbers.

Fetched ON DEMAND and never polled -- each call is a full runtime turn, about
13k input tokens by this project's own measurement, so polling quota spends
quota. Cached with its age. An unparsed answer is an error, never 0%, because
this parses a vendor's human-readable text and a wording change must break
loudly.

First reading: session 14%, week 74%, and **Fable at 100%** -- exactly the
kind of fact that should change how he composes a fleet, and he could not see
it until now.

## nxb-072: I shipped a layout I never looked at, because an edit failed silently

Rohan: "just opened the new layout .. its worse. what happened?"

The splitters reached the markup, making `#body` five children. The CSS that
should have turned it into a flex row never applied, so those five wrapped
inside the old three-column grid and the inspector landed underneath the
canvas.

**The mechanism is the finding, and it is not about CSS.** The edit was a
`str.replace` whose anchor no longer matched the file. `str.replace` does not
raise; it returns the string unchanged and says nothing. Other edits in the
same batch asserted their anchors. This one did not, so half the change
landed. I then "verified" by running the page's JS through a parser -- which
cannot see CSS -- and shipped a page I had never looked at.

Two rules already written in this repo, both broken in one step: a harness
that silently does nothing reports a clean pass, and the author's own tests do
not test the author. The new guard asserts the LAYOUT MODE and the CHILD
ORDER, because those are the facts that were silently wrong.

Suite 412 passed / 743 subtests.
