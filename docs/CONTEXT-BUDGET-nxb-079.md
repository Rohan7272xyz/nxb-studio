# nxb-079: the context budget

2026-09-12. Built after Rohan's 48-hour Pact programme (25 panes, five rigs,
2026-09-07 evening to 2026-09-10 morning) burned through a Codex weekly window
and most of a Claude one. He asked for the usage bleed to be found and closed
without touching model selection. This file is the measurement first, then
what changed, then the rules. Nothing in it is a guess: every number below was
read out of the runtimes' own transcripts on this Mac with the two scripts
under `evidence/nxb-079/`.

## What was measured

Source: every Codex rollout under `~/.codex/sessions/2026/09/07..10` whose
thread was named `pact-*` (72 threads), and every Claude transcript under
`~/.claude/projects/-Users-rohan-dev-pact/` (20 sessions). Codex records a
`token_count` event per request with `last_token_usage`; Claude records
`usage` on every assistant message. A "request" is one model round-trip; a
"turn" is one user message and every request it triggered.

### Codex fleet

| measure | value |
| --- | --- |
| requests | 11,779 |
| input tokens, total | 1,484M |
| of which cached | 1,437M (97 percent) |
| uncached | 47.5M |
| output tokens | 7.6M |
| average context per request | 125K |
| largest context seen | 244K (every pane; the model's window) |
| compactions | 103 |
| `rig collect` calls | 1,632 |
| orchestrator turns with 5+ collects | 68 |
| requests inside those 68 turns | 5,047 |
| input tokens inside those 68 turns | **633M, 43 percent of everything** |

The Program Director alone: 1,375 requests and 175.9M input on the 9/8 thread,
1,018 and 110.6M on the 9/9 thread, 704 collects across both. One single turn,
the 9/8 resume brief, ran 236 requests, 90 of them collects, 34.8M input.

The cost model this implies is simple and it is the whole document: **cost is
requests times context**. Cached tokens are cheaper than uncached but they are
not free, and there were 30 times more of them. Every command an orchestrator
runs is a request that re-sends its entire context. A polling loop of `collect`
every few seconds is therefore a loop of full-context requests, and "wait a
few seconds and collect again" in the brief was the most expensive sentence in
the system.

### Claude panes

| measure | value |
| --- | --- |
| requests | 2,656 (corrected; see note) |
| cache-read tokens | **953M** (corrected) |
| uncached (input plus cache writes) | 19.7M, all on the 1-hour cache |
| output | 3.25M |
| largest context | 930K (a reviewer on `opus[1m]`), 864K (a reviewer on `fable[1m]`) |
| cache misses after a 5-minute gap | 10M of the 19.7M |

The two largest sessions were screenshot-heavy UI reviewers on the 1M-context
models, each re-reading a context of 860K to 930K tokens on every request.

**Correction, 2026-09-12 evening.** The first version of this table counted
6,039 requests and 2,158M cache-read tokens. A Claude transcript writes one
assistant record per content block, all carrying the same `usage`, so that
summed each request about 2.3 times. The Codex figures above are one
`token_count` per request and were never inflated. Corrected output is in
`evidence/nxb-079/claude-bleed-2026-09-12-corrected.txt`. Nothing bounded how far a pane's context could grow, so on the models
with the largest windows it grew to the window. The models were the operator's
choice and are not the problem; the absence of a ceiling was.

### The restarts

The Mac restarted twice (9/8 10:11, 9/9 10:37). Each time every rig was
rebuilt from its Studio draft: 25 new threads with no memory, each re-enrolled
(one turn) and re-briefed (a second turn), then the Director was handed a
resume brief and told to revoke the in-flight ids and re-dispatch the work
"from the committed state". Fresh workers then re-read the repository and
redid whatever had been mid-flight. The 9/9 rebuild's Client Lead and Home
Reminders Builder alone spent 172M input tokens after it. Both runtimes can
reopen a conversation by id; the rig record already held the Codex thread ids
and could have held the Claude session ids.

### The watchers

Overnight on 9/9 a stall watcher typed thirteen "you have been silent"
notes into Claude panes, four of them into one pane inside thirty minutes,
several into panes that were correctly waiting. A budget guard typed six
notes into the Director; a 30-to-90-minute heartbeat woke the chairman 36
times. Each of those is a full-context turn in the pane it lands in. They are
Pact's own scripts, not nxb, but nxb offered them nothing better than raw
`tmux send-keys`.

## What changed

Everything below is in this commit. No model, effort or runtime selection was
touched.

**1. `collect` waits inside itself. [RIG-24]** `rig collect --wait 600` blocks
inside the command, checking the filed reply and the pane on a 2 to 15 second
backoff, and returns the moment the answer lands. One model round-trip per ten
minutes of waiting, against one per few seconds. `rig await --wait 600
--task-id a --task-id b` waits on several tasks at once and returns on the
first answer. The orchestrator brief now says: never poll in a loop of your
own, never sleep between collects, never collect without `--wait`, and it
says why, with the 43 percent in it.

**2. A WAITING payload is small. [RIG-24]** Eight lines and 700 characters of
tail, a one-line detail, a `busy` flag. The old 40-line tail was 1 to 4 KB per
poll and the Director polled 704 times.

**3. Dispatch is one command. [RIG-24]** `rig dispatch --worker W
--message-file path` mints and types in one step, so a dispatch costs one
request instead of two. Long directives go by file, never on a command line,
so the directive is in the orchestrator's context once rather than twice.

**4. Context is per task. [RIG-25]** `rig send` and `rig dispatch` reset the
worker's pane before typing (`/clear`; for Codex the rule and role are
re-typed in one message and the acknowledgement verified). The filed reply
and the repository carry the state between tasks; the pane's memory of the
last task does not ride along on every request of the next. `--keep-context`
is the opt-out, for a revision of the same worker's immediately preceding
task, and the brief says so. Peers keep their context: a peer holds a whole
programme's state. A worker that still holds an unfiled task is refused a
reset (`keystroke_worker_busy`) rather than cleared.

**5. Every pane launches with a context ceiling. [RIG-25]** `claude
--autocompact 200000` and `codex -c model_auto_compact_token_limit=160000`,
per-agent `context_limit` in the Studio inspector, in drafts and over MCP; 0
disables it. Both flags verified to boot READY on claude 2.1.270 and codex
0.154.0 on 2026-09-12. `nxb doctor` now checks both.

**6. A downed rig is resumed, not rebuilt. [RIG-26]** A Claude pane is launched
with `--session-id <uuid>` so its address is known before it speaks; the rig
record keeps `session_id`, `thread_id`, `instructions`, `dir`, the layout and
the window. `rig resume --session X` rebuilds the tmux window and reopens each
pane on its own conversation (`codex ... resume <thread>`, `claude ...
--resume <session>`), reports which panes hold unfiled tasks, and with
`--continue` types an unmarked note into each of those: continue from where
you were, do not start over. Panes with no recorded id are relaunched fresh
and reported as such. Studio shows a **resume** button on a downed rig that has
ids. Nothing resumes at login by itself.

**7. One outstanding directive per worker, enforced. [RIG-27]** `mint` (and
so `rig dispatch`) refuses a second id for a worker whose last id has no
reply on file and is not revoked (`task_worker_busy`), unless `--supersede
<old id>` revokes it in the same step. An answer collected off a screen is now
recorded next to the ledger, so a screen-collected task does not count as
outstanding forever.

**8. Nudges have guards. [RIG-28]** `rig nudge --worker W --message ...`
refuses a pane that is mid-turn (`rig_pane_busy`), a pane nudged inside the
last hour (`rig_nudge_throttled`), and a pane with no task (`rig_nothing_to_
nudge`) unless forced. `rig health --session X` is the read-only view a watcher
should consult first: alive, busy, blocked, outstanding tasks and their ages.

**9. Role and rule in one message. [RIG-22, tightened]** A Codex pane's
standing role is typed inside its enrolment message under the "not a task"
preamble, so a launch costs one acknowledged turn per Codex pane instead of
two, and the same is true of every reset.

**10. The worker is told not to echo its report.** The filed copy is the
answer; after filing, at most three lines of summary. A 78 KB report printed
into a pane was 78 KB the collector could scrape into the orchestrator.

## What this should save, and what it cannot

On the measured run: the 633M of polling input goes to near zero; the
per-request context of a worker pane falls from the window (200K to 930K) to a
ceiling (160K to 200K) and, between tasks, to the brief alone; the two
restarts stop costing a re-dispatch. A rough floor on the saving is half the
fleet's input tokens, and on the Claude side considerably more than that.

It cannot save the work itself. A builder that reads forty files and runs a
test suite spends what that costs, and the fixes here do not touch it. It also
cannot fix an orchestrator that ignores its brief; the brief carries the
numbers so that it has a reason not to.

## Rules, for whoever runs the next programme

- Orchestrators: `rig dispatch` from a file, `rig collect --wait 600`, never a
  loop. If a lead is seen polling, that is a defect in its brief, not in it.
- Watchers: read `rig health`; type through `rig nudge`; never raw
  `send-keys` into an agent pane.
- After a restart: `rig resume --session X --continue` for each rig, then read
  the report's `outstanding` map. Do not rebuild. Do not re-dispatch anything
  whose id is still open.
- Before a long run: read the plan windows (`docs/…usage`, Studio's usage
  panel) and set `context_limit` per agent deliberately; screenshot-heavy
  reviewers want a lower ceiling, not a higher one.
- A worker that needs its last task's context is a revision; send it with
  `--keep-context` and say so in the directive.

## Not done

- Codex's own compaction prompt and Claude's are the vendors'; a ceiling
  decides when they run, not how well. Whether a compacted worker loses
  something a task needed is a per-task question and is not measured here.
- `rig await` waits on task ids from one ledger; a hub waiting on peers in
  another ledger would need `--ledger` per id. Rohan runs one ledger.
- The Pact watchers (`~/.nxb/pact-*.py`) are historical and were not rewritten;
  the next programme's watchers should be written against `rig health` and
  `rig nudge`.
- Nothing here changes what a runtime charges for a cached token. The plan
  window arithmetic stays the vendors' and is read, never predicted.
