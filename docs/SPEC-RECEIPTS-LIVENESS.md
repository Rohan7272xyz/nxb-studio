# Spec: receipts and liveness

Task: nxb-005.1. Author: Worker 3. Date: 2026-08-28.
Status: **DRAFT 2. Supersedes draft 1 in place.** Specification only; no
implementation is proposed and none was written.

Grounding tags, unchanged from draft 1:

- **[M]** measured, with the source task named.
- **[A]** assumption, stated so it can be attacked.
- **[H]** hole. A named gap where a measurement is owed, with the shape the
  answer must fill.

Requirement ids (`R-*`) are stable across drafts so earlier references still
resolve. Draft 2 reorganises them under refusals rather than renumbering them.

## What changed from draft 1, including a rule of mine that was wrong

1. **Reorganised around refusals.** Obligations to emit erode; refusals do not.
   Section 1 is now the spine.
2. **Provenance moved into Phase 1**, and redesigned so it cannot be muted.
3. **The blocking mechanism is specified** (section 3). Draft 1 named its absence
   as its own largest gap. The mechanism comes from the orchestrator's
   observation that hand-delivery succeeded 7 of 7 while emission failed 7 of 7,
   and the difference is that a call returns a value and an emission does not.
4. **R-033 in draft 1 was wrong and is replaced.** It said work produced under
   identity divergence is inadmissible as an independent check. Applied to the
   measured Codex surface, where `config.toml` said `gpt-5.6-sol` and every
   thread recorded `gpt-5.6-luna` [M: nxb-002], that rule would mark **every
   Codex dispatch inadmissible**, which is absurd and would be switched off
   within a week. The error was keying admissibility on the *pinned* model.
   Admissibility must key on the **reported** model, because that is the only
   claim about who actually did the work. Divergence does not make the work
   inadmissible, it makes the *label* wrong. See section 6.

## 0. Four hops across three transports

Settled in draft 1, retained without argument.

| hop | from | to | transport | how it fails today |
|---|---|---|---|---|
| **H1** dispatch | dispatcher | broker | A inbound | silently. Nobody listens [M: nxb-003] |
| **H2** spawn | broker | runtime | B | loudly at tmux, or silently if the child hangs on stdin [M: nxb-002] |
| **H3** report | worker | broker | C | polls a directory forever [M: nxb-004] |
| **H4** deliver | broker | dispatcher | A outbound | no retry, no durable record [M: nxb-003] |

**R-000.** H1 and H4 MUST be separable channels. The broker MUST NOT depend on
the H1 reader's health in order to emit an H4 signal.

## 1. The refusal spine

Each refusal names the vanish point or measurement it exists for. **Load-bearing**
marks the ones whose removal reopens a hole that actually occurred.

### 1.1 Registration

**F-1 [R-021] LOAD-BEARING. The broker MUST REFUSE to register a runtime whose
capability declaration has a null `start_signal`.** A runtime that cannot say it
received work cannot be dispatched to. Had this existed on 2026-08-27, the
browser adapter could not have been registered and seven dispatches would have
failed at dispatch time instead of vanishing [M: nxb-003].

**F-2 [R-020] LOAD-BEARING. The broker MUST REFUSE to register a runtime whose
capability declaration omits any field.** A capability the runtime lacks MUST be
declared explicitly null with a reason. Omission is forbidden, because omission
is how "the adapter watches the chat" survived two months after it stopped being
true [M: nxb-003].

**F-3 [R-042]. The broker MUST REFUSE to register a runtime whose declared
non-null capabilities have not each been observed by a canary against the live
runtime.** A fixture-only proof reproduces the original defect exactly: a
description that agrees with itself while disagreeing with reality.

**F-4 [R-043]. The broker MUST REFUSE to treat a capability proof older than the
freshness budget as valid.** `NEXUS PROTOCOL.md` was true when written and became
false silently. **A proof with no expiry is a document.**

### 1.2 Dispatch

**F-5 [R-016, R-010] LOAD-BEARING. The broker MUST REFUSE to accept a dispatch
for a runtime whose liveness state is `UNKNOWN`,** where `UNKNOWN` includes "no
heartbeat within the freshness budget". Liveness fails closed. The 2026-08-27
failure was fail-open: no signal read as fine.

**F-6 [R-001] LOAD-BEARING. The broker MUST REFUSE to interpret a payload before
it has emitted a receipt for it.** This is draft 1's central rule inverted, and
the inversion is stronger: it is no longer possible to satisfy the letter of the
rule by emitting a receipt after a successful parse. Closes vanish point 4.

**F-7 [R-002]. A receipt MUST REFUSE to carry a verdict.** No `ok`, no `valid`,
no `accepted`. A receipt that can fail to be emitted because the payload was bad
is a disposition wearing a receipt's name.

**F-8 [R-005]. The broker MUST REFUSE to proceed when `payload_digest` differs
from the sender's declared digest,** and MUST NOT resolve the conflict by
proceeding with the bytes it observed. Closes vanish point 6 on any
byte-preserving transport.

**F-9 [R-006] LOAD-BEARING. The broker MUST REFUSE to complete a dispatch whose
`observed_count` differs from `declared_count`, including when `observed_count`
is zero and nothing else went wrong.** The receiver stays free to skip a unit it
cannot parse; it can no longer do so without the sender learning one went
missing. Closes vanish point 5.

**F-10 [R-008] LOAD-BEARING. The broker MUST REFUSE to deduplicate on
`task_id`.** Dedup keys on `receipt_id` and carries the dispatch state. [M:
nxb-004: today `state.register` runs *before* `spawn_task`, and
`seed_dedup_from_state` then skips any on-page directive whose `task_id` is in
the DB, so a directive that registered and failed to spawn is permanently
invisible after a restart. Vanish point 8.] Under F-10 that record sits visibly
at `ACCEPTED`.

**F-11 [R-003]. The broker MUST REFUSE to close a receipt without emitting
exactly one disposition referencing it,** including when the disposition is "I
could not parse this."

**F-12 [R-009]. The broker MUST REFUSE to leave a dispatch record in a
non-terminal state past its budget.** It becomes `ABANDONED` and emits an
outcome. "Still running" and "gone" must be distinguishable by the broker, not
inferred by a human.

### 1.3 Spawn

**F-13 [R-024] LOAD-BEARING for Codex. The broker MUST REFUSE to spawn a Codex
process without redirecting stdin from `/dev/null`.** [M: nxb-002. With stdin
held open, `codex exec` produced zero bytes, no `thread.started`, and was still
alive after 70 seconds. A caller waiting on process exit waits forever. A second
variant completed the turn but never exited.]

**F-14 [R-025]. The broker MUST REFUSE to treat the presence of the `-o` file as
a success signal,** while treating its absence as a reliable failure signal. [M:
nxb-002: it was written while a process still hung.] Generalised: **a signal may
be reliable in one direction only, and the capability declaration MUST say
which.**

**F-15 [R-026]. The broker MUST REFUSE to leave a child process alive after
`start_timeout` elapses without a `start_signal`.** It kills it. [M: the hung
child persists indefinitely.]

**F-16 [R-011] LOAD-BEARING. The broker MUST REFUSE to accept process liveness as
evidence of anything.** Two independent proofs: the 2026-08-27 adapter was not a
process at all, so a PID check had nothing to check [M: nxb-003]; and a hung
`codex exec` was alive, had produced zero bytes, and never would [M: nxb-002].

### 1.4 Evidence and provenance

**F-17 [R-034] LOAD-BEARING. The broker MUST REFUSE to deliver an outcome without
a provenance record**: pinned model, reported model, runtime id, thread or
session id, host, sandbox mode, and capability-declaration version. [M: nxb-004,
nothing carries any of this today; `task.json` has no orchestrator, origin or
host field at all.]

**F-18 [R-035] LOAD-BEARING. The broker MUST REFUSE to count a dissent as
independent evidence unless the reported identity is present, is proven against
the runtime's own record, and differs from the dispatcher's own identity.** Two
instances of the same model disagreeing is variance, not independence.

**F-19 [R-036] LOAD-BEARING. The broker MUST REFUSE to infer refusal, blocking or
success from an agent's prose or from a clean event stream.** [M: nxb-002,
verified three ways: under `-s read-only` a blocked write produced no event at
all; the only trace was prose.] A clean stream is not evidence that work was
permitted. Parsing prose for refusal is a false-green generator.

**F-20 [R-039], REWRITTEN nxb-018 before it ever fired. The broker MUST REFUSE
to ratify an outcome as COMPLETE when its intended effect was CHECKED AND FOUND
FALSE. It MUST NOT refuse merely because the effect could not be checked.**

The original wording refused on "not independently checked AND `refusal_signal`
is null", which for Codex is every outcome ever produced [M: nxb-002,
`refusal_signal` measured absent]. A refusal that fires one hundred percent of
the time for a reason no operator can act on is switched off within a week, and
takes the one case it was meant to catch with it. That is F-5's failure shape,
and this is its third appearance in the project.

The asymmetry that saved F-5 applies unchanged: **refuse on verified false,
record on cannot verify.** An outcome carries `effect: UNCHECKED | VERIFIED |
FALSIFIED`, and only FALSIFIED refuses. Whether the runtime can report its own
refusals is a property of the RUNTIME, recorded once in provenance, and was
never a property of an individual outcome; conflating the two is what built the
trap.

**F-21. The broker MUST REFUSE to accept a sandbox or permission mode chosen by
the directive body or by the worker.** [M: nxb-002: `-c` can override
`sandbox_mode`; `--dangerously-bypass-approvals-and-sandbox` and
`--approve-for-me` exist; `codex exec` rejects `-a` entirely, so in exec mode the
sandbox is the only boundary and there is no human in the loop by construction.]
This is a requirement the receipt layer places on Phase 4. It is not a design of
the permission boundary, which is Rohan's.

### 1.5 The dispatcher side

**F-22 LOAD-BEARING. The dispatcher MUST REFUSE to report progress on a dispatch
for which it holds no receipt.** This is the rule that would have prevented forty
minutes of narrated progress that was not occurring.

**F-23. The dispatcher MUST REFUSE to re-dispatch after an `UNKNOWN` return
without reusing the original `dispatch_key`.** See section 3.4.

**F-24. The dispatcher MUST REFUSE to treat `UNKNOWN` as failure.** No receipt
means it does not know. Conflating "I got no answer" with "it did not happen" is
the same class of error as conflating "nothing came back" with "nothing was
sent".

## 2. The three obligations that cannot be inverted, and why that matters

The reorganisation does not reach everything, and the residue is structural
rather than stylistic.

**A refusal binds an actor that is running. It cannot bind an actor that does not
exist.** The 2026-08-27 failure was a non-running component, so a system built
only of refusals would not have caught it: there was nothing there to refuse.
This is the reason liveness is a separate mechanism and not a special case of the
refusal spine, and it is why the two must both exist.

Three requirements are therefore obligations to act, and each needs its own
enforcement:

**O-1 [R-001 emission side].** A receiver MUST emit a receipt on observation.
Enforced by F-6 only when the receiver is running. When it is not, nothing
enforces it, and only liveness detects that.

**O-2 [R-013].** The broker MUST dispatch a canary to each registered runtime on
an interval. Nothing refuses on its behalf. Enforced by F-4 and F-5 downstream:
an un-canaried runtime ages into `UNKNOWN` and then cannot be dispatched to.
**This is the design's one self-healing loop and it is worth noticing: the
obligation is enforced by a refusal that fires later.**

**O-3 [R-031].** The broker MUST record what the runtime itself reported as its
identity. Enforced downstream by F-17 and F-18.

Each obligation is paired with a refusal that fires if it was skipped. **Any
future requirement added to this spec MUST either be a refusal or name the
refusal that catches its omission.** An obligation with no downstream refusal is
a documentation rule, and documentation rules are what this project exists to
stop trusting.

## 3. The blocking mechanism

Draft 1 named this as its own largest gap: a receipt you can ignore is a log
line, and `NEXUS PROTOCOL.md` already said "verify the dispatch actually landed",
which was followed and still took forty minutes.

### 3.1 The diagnosis, and the caution attached to it

**Call versus emit.** On 2026-08-27, hand-delivery over `SendMessage` succeeded 7
of 7 while emission of directive text failed 7 of 7 [M: nxb-003]. `SendMessage`
is a tool call whose result enters the dispatcher's context. Emitting text into a
transcript has no return value, so there is no moment at which checking is
forced. SOURCE: Orchestrator 1, 2026-08-28.

**[A] The caution.** Two variables differed between the two paths, not one. Hand
delivery had a return value **and** it had a human choosing each recipient and
reading each reply. Attributing the whole difference to the return value is a
single-variable explanation of a two-variable comparison. I think it is the right
explanation, and it is certainly the actionable one, but it is inferred and not
established by the 2026-08-27 data. It would be cheap to test directly, and
section 10 recommends doing so.

### 3.2 The rule, stated more generally than "synchronous"

**R-050 LOAD-BEARING. A dispatch MUST be a call that returns a value into the
dispatcher's own runtime, never an emission the dispatcher hopes is observed.**

The general property is not synchrony. It is **unskippability**. Two shapes
satisfy it:

- the receipt is the return value of the dispatch call; or
- the dispatch call returns a `pending_ref` and the dispatcher must complete a
  blocking `await_receipt(pending_ref)` before its turn can end.

One shape does not satisfy it: **a receipt delivered onto a channel the
dispatcher must voluntarily read.** That reintroduces "remembering to look",
which is exactly what failed.

**This means R-021 alone does not settle the asynchronous case, and the
orchestrator's instinct is right for one of the two cases and not the other.**
Distinguish:

- **(a) A transport that cannot return anything at all.** Pure emit. It has no
  `start_signal` by construction, so F-1 refuses to register it. Settled, and the
  instinct holds.
- **(b) A transport that returns asynchronously.** It may well have a real
  `start_signal`, so F-1 does *not* refuse it, and it is acceptable **only if the
  dispatcher's runtime can block on the receipt.** That is a property of the
  dispatcher, not of the transport, and F-1 does not test it.

**F-25 LOAD-BEARING. The broker MUST REFUSE to accept a dispatch from a
dispatcher that cannot block on the receipt,** on any transport whose receipt is
not the return value of the dispatch call. This is the gap the instinct left, and
it needs its own refusal.

### 3.3 What the call returns

Exactly three terminal shapes. The distinction between the second and third is
the load-bearing part.

```
OBSERVED    receipt_id, hop=H1, observed_at, observer, payload_digest,
            payload_bytes, observed_count, declared_count, state=OBSERVED,
            pending_ref
REFUSED     reason ∈ {runtime_unknown, runtime_unregistered, stale_heartbeat,
            digest_divergence, count_divergence, malformed_envelope, ...},
            dispatch_status = DID_NOT_HAPPEN
UNKNOWN     reason ∈ {receipt_timeout, transport_error},
            dispatch_status = UNKNOWN, dispatch_key echoed
```

**The call MUST always return within a bounded budget.** A dispatch call that can
hang is an emission with extra steps.

`REFUSED` is a **positive** assertion that the dispatch did not happen. The
broker knows, and the dispatcher can safely redirect.

`UNKNOWN` asserts only that the dispatcher does not know. **It MUST NOT be
rendered as failure** (F-24). This is where the old system's worst confusion
lived: "nothing came back" was indistinguishable from "nothing was sent".

### 3.4 What the dispatcher must do with each

| return | required action |
|---|---|
| `OBSERVED` | record `pending_ref` in the durable pending ledger (R-029) and proceed |
| `REFUSED` | do not proceed as dispatched; surface the reason; a retry needs a changed cause, not a repeat |
| `UNKNOWN` | do not report progress (F-22); do not re-dispatch except by reusing `dispatch_key` (F-23); reconcile before concluding anything |

**R-051 LOAD-BEARING. Every dispatch envelope MUST carry a dispatcher-generated
`dispatch_key`, unique per intent, and the broker MUST return the existing
receipt for a repeated key rather than creating a second dispatch.** This is what
makes `UNKNOWN` recoverable rather than a trap: the dispatcher can retry safely
without risking a duplicate, and a duplicate directive was a real hazard in the
old system's dedup design [M: nxb-004].

### 3.5 The asymmetry across hops, which the rule does not survive intact

Blocking is right for two hops and wrong for two, and it is worth being explicit
because "dispatch must be a call that returns" reads as universal.

| hop | blocking? | why |
|---|---|---|
| **H1** dispatcher to broker | **yes** | the broker is a service; it can answer immediately |
| **H2** broker to runtime | **yes** | bounded by `start_timeout`; for Codex this is `thread.started` on stdout [M: nxb-002] |
| **H3** worker to broker | **no** | on a filesystem transport there is nothing to call. The broker polls with a deadline, and the worker MUST be told that deadline in its directive so a slow worker knows it is being abandoned |
| **H4** broker to dispatcher | **no** | **you cannot block on a peer that is busy doing the work you gave it.** The dispatcher is mid-turn by construction |

**R-052. H3 and H4 MUST use a durable pending record with retry, not blocking.**
An H4 outcome that fails to deliver stays pending and is redelivered; it is never
dropped, and its non-delivery is itself an alarm after a budget. This closes
vanish points 9 and 10 without pretending the dispatcher can answer on demand.

**H-053 [H].** The unresolved case: a dispatcher that is permanently busy or has
ended. H4 then accumulates undelivered outcomes forever. The spec requires the
pending record and the alarm; it does not specify a garbage-collection policy,
because the right policy depends on whether a dispatcher's identity survives a
session ending, which is part of H-027 and unmeasured.

## 4. Liveness

**R-010** (fail closed) and **R-011** (process liveness banned) are now F-5 and
F-16.

**R-012 [R-013]. The heartbeat MUST be an end-to-end capability assertion through
the real path**, not a ping. The only assertion that would have caught
2026-08-27 is one that exercises the same code a real dispatch uses.

**R-014.** The canary MUST be distinguishable from real work in the ledger and
MUST NOT consume a `task_id` from the real sequence.

**A-015 [A].** Canary interval 15 minutes per runtime; freshness budget 30
minutes. **Both unmeasured.** The only anchor is that the observed blind window
on 2026-08-27 was 40 minutes before a human noticed, then roughly 6 hours [M:
nxb-003], so the budget must be well under 40 minutes to be an improvement.
Rohan should set these, because a canary costs real tokens on every interval
forever to detect a condition that has occurred once.

**R-017.** A stale heartbeat marks the runtime `UNKNOWN`, refuses new dispatches
(F-5), alarms every dispatcher in that dispatcher's own runtime, and does NOT
silently queue work. Queuing against a dead counterpart is how forty minutes
passed.

**H-018 [H].** No runtime measured so far offers a progress signal distinguishable
from a slow model. For Codex the only observed signals are start and terminal [M:
nxb-002]. Until measured otherwise, the broker MUST treat "running" as "started
and not yet terminal", bounded by a timeout, and MUST NOT claim to observe
progress.

## 5. Per-runtime primitives

**R-019.** Ack primitives are declared per runtime as data, never hardcoded. [M:
nxb-004 measured the cost of the alternative: `VALID_TARGET_AGENTS` in
`validation.py:13`, `AGENT_COMMANDS` in `runner.py:41`, `AGENT_ARGS` in
`runner.py:53`, three tables in two modules that must agree with no test
asserting they do.]

Declaration fields, all mandatory (F-2): `runtime_id`, `spawn`, `start_signal`,
`start_timeout`, `identity`, `terminal_signal`, `refusal_signal`, `cancel`,
`progress_signal`, `last_proven_at`.

### 5.1 Codex, from measurement

All [M: nxb-002], measured on this Mac 2026-08-28.

| field | value |
|---|---|
| `spawn` | `codex exec --json -m <model> -C <abs workdir> --output-schema <schema> -o <file> ... < /dev/null` |
| `start_signal` | `{"type":"thread.started","thread_id":...}`, first line on stdout, before any model work |
| `start_timeout` | **A-023 [A]: 30 seconds.** Not measured; a healthy run reached exit in 5 seconds |
| `identity` | `thread_id` UUID from `thread.started`. **UUID only.** Names are auto-generated and mutate; 4 of 8 sampled ids carried more than one name |
| `terminal_signal` | exit 0 / 1 / 2; `turn.completed` or `turn.failed`; **absence of the `-o` file as a reliable failure signal** (F-14) |
| `refusal_signal` | **null. Measured absent.** |
| `cancel` | **null. UNVERIFIED.** SIGINT to a live turn untested; `RecoverTurn` and `abortReason` exist in the binary |
| `progress_signal` | null |

### 5.2 Claude Code: the named hole, unchanged

**H-027 [H].** Not measured. nxb-001 is still running and guessing here would
reproduce the exact error this project keeps finding. The answer MUST distinguish:

1. **A transmission ack generated on the sending side** versus **an observation
   receipt from the receiver.** Only the second is a receipt under F-6. *Data
   point offered from my own use in this session, not a probe:* `SendMessage`
   returns `{"success":true,"message":"... → Orchestrator 1 ...","msg_id":"..."}`.
   That object is generated sender-side and names the resolved recipient.
   **Whether it implies the receiving session ever observed the message is
   precisely what nxb-001 must measure.** If it is sender-side only, Claude Code
   has no `start_signal`, F-1 refuses it, and the broker must instead require the
   receiving session to emit its own receipt.
2. Whether a receiving session can emit a receipt **before** interpreting the
   directive, or only after.
3. What delivery to a busy, idle, or ended session does, distinguishably. This
   also bears on H-053.
4. Whether identity is stable and machine-readable, given that names are the
   address and name mutation is a measured hazard in the other runtime.
5. Whether anything observable distinguishes a refused action from a completed
   one.

**R-028.** Until H-027 is filled, Claude Code MUST NOT be registered (F-1), and
hand-delivery to a Claude Code pane MUST be labeled a receipt-less transport in
the ledger. Naming it honestly is the point; that is what was not done on
2026-08-27.

## 6. Provenance, in Phase 1, designed not to be muted

Moved forward because the product of this broker is not dispatch, it is
**attributable disagreement**. A dissent that cannot be attributed to a known
model that demonstrably did the work is worth nothing however good the receipts
are.

### 6.1 The muting problem, and the fix

Draft 1's R-033 would have fired on every Codex dispatch, because the divergence
[M: nxb-002, `config.toml` said `gpt-5.6-sol`, every thread recorded
`gpt-5.6-luna`, cause UNVERIFIED] appears to be a property of the runtime rather
than of any one dispatch. An alarm that always fires is switched off.

The fix is to make **systemic** and **per-dispatch** divergence mechanically
distinguishable, and to alarm only on the second.

**R-030.** The broker MUST pin model identity explicitly at spawn (`-m` for
Codex [M: works]) and MUST NOT rely on a runtime's configured default.

**O-3 / R-031.** The broker MUST record what the runtime itself reported, read
from the runtime's own record of the thread, not from the broker's request.

**R-054. Each runtime carries an `identity_baseline`**: the mapping from pinned
to reported identity, established by canary observations, with a count and a
`last_proven_at`. The baseline is a fact about the runtime, refreshed by the same
canary that proves liveness, and expiring under F-4.

**R-055. Divergence that matches the baseline is RECORDED, not alarmed.** It is
carried in provenance as `divergence: baseline`. It is not an incident. It is a
known property of that runtime.

**R-056. Divergence that does NOT match the baseline raises
`IDENTITY_DIVERGENCE`** and is rare by construction, so it does not get muted. It
means something changed between the canary and this dispatch, which is exactly
the condition worth interrupting for.

**R-057. A change in the baseline itself is a separate, louder event**
(`BASELINE_SHIFT`). If a runtime silently starts serving a different model, that
is the most consequential thing that can happen to the disagreement thesis and it
must not be absorbed as noise.

**A-058 [A].** Baseline established after 3 consecutive agreeing canary
observations. Unmeasured; it trades detection latency against flapping.

### 6.2 Admissibility, corrected

**F-18 / R-035, restated with the correction from draft 1.** Admissibility keys
on the **reported** identity, never the pinned one.

A result is admissible as an **independent** check only if all hold:

1. a reported identity is present;
2. it was read from the runtime's own record (O-3), not echoed from the request;
3. it differs from the dispatcher's own identity;
4. the runtime's `identity_baseline` is established and unexpired.

Otherwise the result is still **delivered and readable**. It is simply not
counted as a second opinion. **A systemic divergence therefore costs nothing in
admissibility. It only changes the label from `sol` to `luna`,** which is the
correct outcome and the one draft 1 got wrong.

**R-059. Provenance MUST record both pinned and reported identity, always, even
when they agree.** Recording only on divergence makes the absence of a record
ambiguous.

### 6.3 The part provenance cannot fix

**F-19 and F-20** stand. A sandbox denial is invisible in the Codex event stream
[M: nxb-002, verified three ways], so provenance can say *which model, under
which sandbox, on which host* produced a claim, and still cannot say whether that
model was refused and narrated around it.

**Stated plainly, because it bounds the product:** work whose effect is externally
checkable is safe to dispatch and verifiable. **Work whose only product is a
judgement is a claim, not a verified result, and this project's product is
largely judgements.** Provenance moving to Phase 1 improves attribution and does
nothing for verification. Both are needed and only one is available.

## 7. Vanish point coverage

Unchanged from draft 1 except where noted. **CLOSED** means the loss becomes
impossible or immediately visible to the sender.

| # | vanish point | closed by | verdict |
|---|---|---|---|
| 1 | wrong surface | F-1, F-5 | CLOSED |
| 2 | adapter not running | F-5, O-2 canary | CLOSED |
| 3 | wrong host | envelope names the runtime target; adapter declares hosts served; H2 receipt asserts resolution | CLOSED, requires the envelope field |
| 4 | silent parse rejection | F-6, F-11 | CLOSED. The flagship |
| 5 | unpaired or mis-nested tags | F-9 | CLOSED on a structured transport; degrades to sender discipline on a text one |
| 6 | payload truncation | F-8 | CLOSED on a byte-preserving transport. **OPEN on DOM scraping**, where rendering mutates text and no honest sender-side digest exists |
| 7 | selector drift, soft-skip forever | O-2 canary | CLOSED |
| 8 | restart amnesia | F-10 | CLOSED |
| 9 | lost failure report | R-052 durable retry, R-000 | CLOSED. **Draft 2 strengthens this**: draft 1 relied on separable channels alone |
| 10 | paste-back into the void | R-052 | CLOSED |
| 11 | in-memory-only dispatch set | F-10, R-029 | CLOSED |
| 12 | no transactionality | receipts make it visible, not impossible | **MITIGATED, NOT CLOSED** |
| 13 | no dispatcher-side pending list | R-029, F-22, R-051 | **CLOSED, and draft 2 strengthens it**: draft 1 relied on the dispatcher choosing to keep a ledger, draft 2 makes `pending_ref` arrive in a return value the dispatcher cannot skip |
| 14 | hand-delivery has no receipt | R-028 labeling | **PARTIAL, weakest.** Uninstrumentable by construction; can be labeled or banned |
| 15 | sandbox refusal narrated as done | nothing | **OPEN and unclosable on the measured Codex surface** |

**R-029.** The dispatcher MUST maintain a durable pending ledger on disk with a
timer per entry. The caveat that made this weak in draft 1 still applies: a
dispatcher is a Claude Code session, its context is compacted, and **a pending
list that lives in an LLM's context is not a pending list**. Draft 2 reduces the
exposure by making `pending_ref` arrive as a return value rather than something
the dispatcher must remember to write down, but the durable write is still an
obligation on dispatcher-side tooling, not something the broker can enforce.

**Which of the eleven silent-by-construction points survive: three, unchanged.**
#6 on a byte-lossy transport, #12 as a real gap receipts only illuminate, #14
entirely.

## 8. The self-validating contract test

**R-040.** The contract MUST be published as machine-readable data, not prose:
dispatch envelope, receipt, disposition, outcome, capability declaration, error
vocabulary. Prose documentation MUST be generated from it or tested against it,
never authored independently.

**R-041.** Three assertions in CI:

1. **Examples validate.** Every published example passes the production
   validator. Catches a document drifting from code.
2. **No undocumented requirements.** Every field the production validator
   requires appears in the published contract. Catches code drifting from the
   document. This direction is usually omitted and it is the one that matters: an
   undocumented required field is how a worker gets a rejection it cannot
   diagnose.
3. **Declared capabilities are exercised.** Each non-null capability field is
   observed by a canary against the live runtime, enforced as a refusal by F-3.

**F-3 already carries assertion 3**, which is the reorganisation working as
intended: what was a test obligation in draft 1 is now a registration refusal.

## 9. Reuse versus rewrite

Decision deferred [nxb-004]. Draft 2 changes the delta in one place.

**Under reuse.** Receipts bolt onto the existing subprocess-plus-JSON seam [M:
nxb-004]. But **F-6 cannot be satisfied by wrapping**, because `execute_directive`
parses first and its first observable act is already a verdict. Reuse requires
splitting it into an `observe` step that emits a receipt and an `execute` step
that validates: a real change to `orchestrator.py`. **Draft 2 adds a second
obstacle:** R-050 requires dispatch to be a call that returns a receipt, and the
existing CLI returns only after `execute-directive` has parsed, created a task
folder and spawned. Its return value is a disposition, not a receipt. So reuse
now needs a new entry point, not just a re-composition.

**Under rewrite.** Receipt-first and call-returns-receipt are the natural shape.
Vanish point 5 disappears; 6 reduces to a digest check.

**Identical either way, safe to build now:** the durable pending ledger (R-029,
R-051), the capability declaration (F-1, F-2, R-019), the canary (O-2), the
provenance record (F-17, R-054 to R-059), and the contract test (R-040, R-041).

## 10. Objections to draft 2

New objections only. Draft 1's stand where unchanged and are not repeated.

**1. The refusal spine relocates the muting risk rather than removing it.** This
is the strongest objection and it is aimed at the reorganisation itself. Change 2
was made because an alarm that always fires gets switched off. But draft 2 now
contains twenty-five refusals, several gated on unmeasured budgets (A-015, A-023,
A-058). At seven tasks a day, the most likely lived experience is not a caught
failure, it is **the broker refusing to dispatch because a canary proof expired
while nobody was working**. The predictable human response is to widen the
freshness budget until it stops biting, which is muting by another name. **The
muting risk I removed from the identity alarm has reappeared in the liveness
refusals, and draft 2 does not solve it.** A refusal is only un-mutable if its
false-positive rate is near zero, and I have no measurement that says these are.
The mitigation I would propose, and have not specified because it needs a number
nobody has: refusals should distinguish "stale because broken" from "stale
because idle", and idleness should trigger a canary rather than a refusal.

**2. `dispatch_key` makes the broker's dedup store a new single point of silent
failure.** R-051 makes `UNKNOWN` safe to retry, but only if the broker's record of
issued keys survives its own restart. If that store is lost or corrupted, a retry
silently becomes a double dispatch, and double-dispatching a worker into the same
repo is a real hazard [the old protocol warned that two workers in one repo
collide]. Draft 2 requires durability and does not require the corruption to be
detectable, which is the same shape as vanish point 12.

**3. The call-versus-emit diagnosis rests on a confounded comparison.** Stated in
3.1 and repeated here because it is load-bearing for the whole of section 3.
Return value and human attention both differed between the two paths on
2026-08-27. **This is cheap to test and nobody has:** have a dispatcher emit a
directive into a transport with a return value while nobody watches, and see
whether the return value alone changes the outcome. Until then R-050 is a
well-motivated assumption, not a measured one, and it is currently the most
load-bearing unmeasured claim in the document.

**4. Section 2 concedes that refusals cannot catch the failure that started this
project.** A refusal binds a running actor; 2026-08-27's actor was not running.
So the reorganisation, which was adopted precisely because refusals are harder to
erode, does not cover the originating incident. Liveness does. That is fine, but
it means the answer to "which single mechanism would have prevented this" is
still O-2, an **obligation**, and obligations are what the reorganisation
distrusts. The design's most important component is its least enforceable one.

**5. F-18's condition 3 may not be evaluable.** Admissibility requires the
reported identity to differ from **the dispatcher's own**. Whether a Claude Code
session's model identity is machine-readable by a broker is unmeasured, and if it
is not, condition 3 cannot be evaluated and F-18 becomes another document rule.
Add it to H-027.

## UNVERIFIED

- Every number remains an assumption: A-015 (canary 15 min, freshness 30 min),
  A-023 (Codex start timeout 30s), A-058 (baseline after 3 canaries). The only
  anchor is the observed 40-minute blind window.
- R-050 itself, per objection 3. Inferred from a two-variable comparison.
- H-027: all Claude Code primitives, now including whether its model identity is
  readable by a broker (objection 5) and what delivery to an ended session does
  (H-053).
- Whether receipt-before-parsing is possible on any candidate transport. Trivial
  on a structured bus, assumed; possibly impossible on a scraping one.
- Whether `payload_digest` is computable by the sender on a real transport.
  Asserted impossible for DOM scraping by reasoning, not tested.
- The cause of the sol-to-luna divergence remains unknown [M: nxb-002 marks it
  UNVERIFIED]. R-054's baseline design works whether or not the cause is ever
  found, but a known cause might make the baseline unnecessary.
- Reuse-side change sizes in section 9 are estimates.

## Was it shorter

**No. It is longer, and I predicted shorter.** Draft 1 was 580 lines, draft 2 is
700, up 21 percent for the same vanish-point coverage. Three reasons, two
legitimate and one not.

Legitimate: the blocking mechanism is new material that draft 1 omitted entirely,
and the anti-muting identity design replaced one paragraph with a mechanism.

Not legitimate: **inverting a requirement into a refusal costs words.** "The
broker MUST emit a receipt" becomes "the broker MUST REFUSE to interpret a
payload before it has emitted a receipt for it", which is stronger and longer.
The prediction that refusals would be shorter was wrong. The claim that they are
harder to erode still holds, and I would still make the trade, but it is a trade
and not a free win.

## Where I think you may still be framing this wrongly

**1. The blocking mechanism is a requirement on the dispatcher's tooling, and
neither the broker nor the spec can enforce it.** The broker can return a
receipt. It cannot make an LLM read the return value or write the pending ledger.
So call-versus-emit converts silence into a **visible but ignorable** value, which
you acknowledged. What neither of us has said: **the only actor that can enforce
unskippability is the harness, not the broker and not the model.** R-050 is
really a requirement on whoever builds the dispatcher-side dispatch tool, that
its result be structurally impossible to proceed without. That belongs written
down as a tooling requirement with an owner, or it will quietly become another
document rule, which is the failure mode this whole project is about.

**2. Stop specifying and build one hop.** This is the reframe I most want you to
weigh, and it argues against my own continued usefulness on this track. The
project is four documents deep with zero lines of running code, and **every
document has corrected the one before it, including two of my own claims.** The
correction rate is 100% and there is no reason to believe draft 2 breaks the
streak. The cheapest way to find draft 2's errors is not draft 3. It is building
H1 alone: a dispatch call that returns a receipt, a `dispatch_key`, and a durable
pending record, against one runtime, and seeing which of these twenty-five
refusals turn out to be unimplementable or intolerable in practice. Objections 1
and 3 above are both empirical questions that a week of real use would answer and
that no amount of specification will.

**3. Consider that the disagreement thesis has not been tested at all.** Every
task so far has measured plumbing. The premise, that an Opus orchestrator and a
GPT-5.6 worker disagreeing is a genuinely independent check, is the load-bearing
assumption of the entire project and it is [A], not [M]. It would be cheap to
test now, before the broker exists: hand the same question to both runtimes by
hand, and see whether the disagreements are substantive or stylistic. If they are
mostly stylistic, the broker is a delivery mechanism for noise and the whole
shape of the project should change. That test costs an afternoon and nobody has
run it.
