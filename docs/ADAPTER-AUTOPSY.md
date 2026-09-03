# Adapter Autopsy: why zero of seven directives fired on 2026-08-27

Task: nxb-003. Author: Worker 3. Date: 2026-08-28. Method: read-only.
Nothing was started, stopped, fixed or modified. Two hosts were inspected:
this Mac (`/Users/rohan`) and `second-host` (`second-host`,
reached over `ssh second-host`).

Every claim below is labeled OBSERVED (I ran a command and read its output)
or INFERRED (I reasoned from observations). Nothing is quoted from memory.

## The direct answer

**The adapter exists, it is real and it is fully built, but it can only see a
web browser tab. The directives were emitted into a terminal. There was never
a path between the two.**

The adapter is a Playwright program that drives a real Chrome window pointed at
`https://claude.ai/new` and reads the chat transcript out of the page DOM. Its
single input is one line of code:

```python
# nexus/web_adapter.py:503
def read_page_text(self):
    selector = self.config.message_container_selector or "body"
    return self.page.locator(selector).inner_text()
```

On 2026-08-27 the orchestrator was a **Claude Code terminal session on the
Mac**, not a claude.ai browser tab. Text printed in a terminal TUI is not in
any DOM. There is no file watcher, no hook, no log tail, no socket and no
stdin path in the adapter. Directives emitted in a terminal are not merely
missed by an unhealthy adapter, they are outside its sensory range entirely.

Second, independent cause, sufficient on its own: **the adapter was not
running**, on either machine, on 2026-08-27. It has not run since
2026-06-14.

Third: the adapter lives on `second-host`, not on this Mac. Even a running
instance would have spawned its workers on `second-host`.

Any one of these three alone accounts for 0 of 7. All three were true at once.

## 1. What the adapter is, and where

OBSERVED. The implementation is `/home/operator/nexus` on `second-host`. It is
a Python package, `nexus-directive` version 0.1.0, console script `nexus`
(`nexus.cli:main`), no runtime dependencies except an optional `[web]` extra
that pulls Playwright. Playwright 1.60.0 is installed in its `.venv`.

Modules under `nexus/`: `parser.py`, `validation.py`, `state.py`, `errors.py`,
`runtime.py`, `report.py`, `collector.py`, `waiter.py`, `runner.py`,
`orchestrator.py`, `web_adapter.py`, `registry.py`, `routing.py`,
`dashboard.py`, `launcher.py`, `cli.py`. Docs: `README.md`,
`NEXUS_HANDOFF.md` (the implementation handoff, dated 2026-05-23),
`examples/web-configs/{claude-ai,chatgpt,imd,bfd,qad,local-smoke}.json`.

It is none of the things the brief asked me to rule in or out on this Mac. It
is **not** a daemon, **not** a launchd or systemd unit, **not** a file watcher,
**not** a tmux integration and **not** a browser extension. It is a
**Playwright browser-automation process** that a human starts by hand.

The pipeline, from `NEXUS_HANDOFF.md` and confirmed against the source:

```
claude.ai tab (DOM)
  -> WebAdapter.read_page_text()          Playwright inner_text of #main-content
  -> extract_all_directives()             pair START/END tags in document order
  -> DirectiveDedup.add()                 in-memory, per-session, keyed on block text
  -> parse_directive()                    validate the 5 header fields
  -> execute_directive()                  state.check -> create_task -> state.register -> spawn_task
  -> runner.TmuxAdapter.spawn             tmux pane, paste agent_prompt.md into `claude`
  -> waiter/collector                     poll status.json, validate final_report.md
  -> WebAdapter.send_response()           type the NEXUS_EXECUTION_RESULT block back into the chat box
```

Its configured surface for Claude is `examples/web-configs/claude-ai.json`:
`page_url: https://claude.ai/new`, container `#main-content`, input
`div[contenteditable='true']`, submit `button[aria-label='Send message']`,
profile `~/.config/nexus/browser-profiles/claude-ai`, tmux session
`nexus-claude-ai`. The config marks itself `"_starter_only": true`.

**It does not exist on this Mac.** OBSERVED: `grep -rIl 'NEXUS_DIRECTIVE'`
across `~/dev`, `~/workspace`, `~/.config`, `~/.local`, `~/bin`, `~/.claude`,
`~/.codex`, `~/.agents`, `~/.another-project`, `~/Documents`, `~/Desktop` and `~/.nexus`
matched **only conversation records**: Claude Code transcripts under
`~/.claude/projects/-Users-rohan/*.jsonl`, `~/.claude/history.jsonl`, and Codex
session logs under `~/.codex/sessions/`. No source file, no script, no config.
`launchctl list` shows no NEXUS job. No matching process. There is no tmux
server running on the Mac at all.

## 2. Was it running on 2026-08-27

**No.** Four independent artifacts that a running adapter writes are absent or
last written 2026-06-14. I did not stand at the machine on 2026-08-27, so this
is a reconstruction from artifacts rather than a live observation, but the
artifacts agree and there is no reading of them in which it ran.

| Signal | What a running adapter does | OBSERVED state |
|---|---|---|
| Registry entry | `run_web_adapter` calls `registry.register()` on start, `unregister()` on exit; both mutate the directory | `~/.config/nexus/orchestrators/` exists, is **empty**, mtime **2026-06-14 16:10** |
| Chrome profile | `launch_persistent_context` writes `Local State`, `SingletonLock`, caches on every launch | newest file under **either** profile root (`~/.config/nexus/browser-profiles`, `~/.cache/nexus/browser-profiles`) is **2026-06-14 16:10** |
| Process | one long-lived `python -m nexus web-adapter` plus a Chrome | no `web-adapter`, no `dashboard`, no `python -m nexus`, no playwright-driven Chrome on either host |
| tmux session | workers land in `nexus-claude-ai` (or `nexus-<slug>`) | second-host sessions are `another-project-panes`, `main`, `obsidian-mcp`, `tether-*`. No `nexus-*` session. Mac has no tmux server |
| Dedup state DB | `~/.nexus/state.db` created on first use | **does not exist** on either host |
| Task folders | `runtime.create_task` writes `task.json`, `status.json`, `agent_prompt.md`, later `final_report.md` | `find ~ /tmp -name agent_prompt.md` returns **0 hits on both hosts** |

The last row is the strongest, and it is worth stating on its own because it
also disposes of the "maybe it ran with non-default paths" objection. There are
106 folders under the two `~/.nexus/tasks` trees (36 on the Mac, 70 on
second-host) and **not one of them contains a single adapter-written file**. They
hold `REPORT.md`, `evidence/`, ad-hoc scripts: artifacts workers created by
hand because a hand-delivered directive told them where to put things. The
adapter's own task-folder format has never been produced anywhere on either
machine that still exists on disk.

OBSERVED: the adapter's source has not been touched since 2026-05-23 (no `.py`
under `~/nexus` is newer than 2026-06-01). `~/.nexus/run/` is dated 2026-05-23.

INFERRED, and this is the useful part: the mechanism did not rot or crash. It
was **built, demonstrated live in May, used through mid-June, and then simply
not started again**, while the directive *format* and the orchestrator prompt
kept being used daily. `NEXUS PROTOCOL.md` on the Mac still tells an
orchestrator that "the user's local NEXUS adapter, watching this chat, detects
and validates it, creates a task folder, and spawns a terminal coding agent."
That sentence has been false for over two months, and nothing in the system was
in a position to notice.

## 3. Where the directives went

Nowhere. They were rendered as text in a terminal and written to a JSONL
transcript. Nothing read them except humans and peer agents.

OBSERVED, from `~/.claude/projects/-Users-rohan/72daf95b-4011-41ec-b024-fa345f08c607.jsonl`
(the orchestrator's own session, first entry 2026-08-27T18:36:38Z, last
2026-08-28T15:12:02Z, 725 records). Assistant-emitted `<NEXUS_DIRECTIVE_START>`
blocks:

| # | timestamp (UTC) | task_id | target_agent | repo_path |
|---|---|---|---|---|
| 1 | 2026-08-27T18:51:49Z | nexus-busy-007 | claude_code | /home/operator/downstream-project |
| 2 | 2026-08-27T19:05:14Z | nexus-busy-007.1 | claude_code | /home/operator/downstream-project |
| 3 | 2026-08-27T19:55:41Z | nexus-busy-010 | claude_code | /Users/rohan/downstream-project |
| 4 | 2026-08-27T23:42:07Z | nexus-busy-011 | claude_code | /Users/rohan/downstream-project |
| 5 | 2026-08-28T01:02:08Z | nexus-busy-011.1 | claude_code | /Users/rohan/downstream-project |

That is **five** blocks spanning 6h11m, not seven over twelve hours. Seven
distinct task ids do appear in the session (007, 007.1, 008, 009, 010, 011,
011.1); 008 and 009 are never wrapped in directive tags anywhere in the
transcript. INFERRED: the count of seven is a count of dispatched *tasks*, of
which five were emitted in directive form. This changes nothing about the
conclusion and I flag it only because the ack we build will be counted against
one of these two numbers and they should not be conflated.

One detail that matters for the design. Directives 3, 4 and 5 name a **Mac**
`repo_path` while the adapter runs on **second-host**. `validate_repo_path`
checks only that a path is absolute, never that it exists. Had the adapter been
alive on second-host, those three would have parsed clean, created a task folder,
registered the task_id in the state DB, and only then failed at
`tmux new-window -c /Users/rohan/downstream-project`, a directory that does not
exist on that host. The protocol's instruction to name the host in the first
line of the body is a workaround for a field the header does not have.

**How it was ever supposed to observe them.** Only one way: the orchestrator
had to be a claude.ai chat in a Chrome window that the adapter itself launched,
with the adapter process running and pointed at that tab. `NEXUS PROTOCOL.md`
is explicit in its first line: "You are the NEXUS **web** orchestrator." The
transport assumes the orchestrator lives in a browser. On 2026-08-27 the
orchestrator was a terminal pane. The protocol document was carried over to a
runtime it was never written for, and the document itself does not say which
runtime it requires anywhere except that first line.

## 4. What failure would have looked like

The system has a rich error vocabulary and a real result contract. Twenty
stable `error_type` values exist (`parse_error`, `validation_error`,
`duplicate_directive`, `task_exists`, `agent_command_missing`,
`tmux_not_available`, `runner_error`, `timeout`, and so on), and
`process_cycle` genuinely pastes `{ok: false, error_type, error}` back to the
chat when a spawn fails. **None of that could fire, because every one of those
paths is downstream of an observation that never happened.** The error
machinery is inside the pipeline. The failure was that the pipeline had no
input and nobody was watching the input.

Concretely, the points at which it *could* have said "I saw a directive and
could not act on it", and what stopped each:

1. **On observation.** The adapter never observed. Stopped by: not running, and
   watching the wrong surface. Nothing in the design monitors whether the
   adapter is alive; the registry exists for a *dashboard* to discover live
   adapters, and the dashboard was not running either. There is no heartbeat
   and no liveness assertion anywhere.
2. **On parse rejection.** `process_cycle:705-708` catches `NexusError` and
   `continue`s, by design, so pasted format examples and templates do not spawn
   workers. This is a **deliberate silent drop of anything that looks like a
   directive but fails validation**. It is the single most important line in
   the codebase for this project: a typo'd field, a body containing a boundary
   tag, a non-absolute `repo_path`, all vanish here with no event and no
   record, and the block is already deduped so it will never be reconsidered.
3. **On spawn failure.** This one *is* reported, to the chat, via
   `send_response`. But `send_response` (`web_adapter.py:544`) has no error
   handling of its own, and the caller has already marked the directive as seen
   in `DirectiveDedup`. If pasting the failure report throws (a changed
   selector, a logged-out page), the enclosing loop converts it to a soft
   `selector_not_found` and keeps polling. The failure report is then lost
   permanently, because the directive that produced it is deduped.
4. **On the orchestrator's side.** Nothing. The orchestrator has no timeout, no
   pending-dispatch list, no unacknowledged-directive alarm. `NEXUS PROTOCOL.md`
   addresses this with prose ("Verify the dispatch actually landed... check
   `ListAgents`"), which is a human procedure standing in for a missing
   protocol feature. That prose is why the orchestrator eventually caught it,
   after 40 minutes.

## How a dispatch can vanish

The requirements list for the ack. Each entry is a point where a directive is
lost with **no signal to the orchestrator**. Sources are cited so each can be
re-checked.

1. **Wrong surface.** The orchestrator emits into a runtime the adapter cannot
   observe (terminal instead of browser DOM). No error is possible because
   nothing is listening. `web_adapter.py:503`. *This is what happened.*
2. **Adapter not running.** No process, no heartbeat, no liveness check. The
   registry is written by the adapter for the dashboard's benefit, so it is
   evidence of life only when something reads it, and nothing did.
   `registry.py`, `run_web_adapter`.
3. **Wrong host.** The adapter spawns on the machine it runs on. `repo_path` is
   validated for absoluteness only, never existence, and there is no `host`
   field in the schema. A Mac path dispatched to a second-host adapter parses
   clean and dies at tmux. `validation.py`, `NEXUS PROTOCOL.md` field rules.
4. **Silent parse rejection.** `except NexusError: continue`, with the block
   already deduped. Deliberate, and it is the designed-in vanish point.
   `web_adapter.py:705-708`.
5. **Unpaired or mis-nested tags.** `extract_all_directives` skips stray,
   unmatched or mis-nested boundary tags and returns nothing for them. A
   truncated or reflowed block disappears silently. `web_adapter.py:61-96`.
6. **DOM truncation.** The adapter reads `inner_text()` of `#main-content`. A
   virtualised or collapsed transcript, a "show more" fold, or a long directive
   scrolled out of the rendered region means the block is not in the text at
   all. There is no assertion that what was read is complete.
7. **Selector drift.** `claude-ai.json` is marked `_starter_only` with no
   live-DOM CI. A UI change makes every cycle a soft `selector_not_found` and
   the adapter keeps polling forever, healthy-looking and blind.
   `run_web_adapter` exception handler.
8. **Restart amnesia in the wrong direction.** `seed_dedup_from_state` marks
   every on-page directive whose task_id is already in the state DB as seen.
   Because `execute_directive` calls `state.register` **before**
   `spawn_task`, a directive that registered and then failed to spawn is
   permanently skipped after a restart. `orchestrator.py`, `web_adapter.py:508`.
9. **Lost failure report.** A spawn failure whose paste-back throws is gone
   forever, because dedup ran before the report was delivered.
   `web_adapter.py:696` versus `:739`.
10. **Paste-back into the void.** Results are delivered by typing into a chat
    box. If the box is not focusable, the page is logged out, or the
    orchestrator is not that tab, the result is lost with no retry queue and no
    durable record outside the task folder.
11. **In-memory-only dispatch set.** `DirectiveDedup` is a per-process Python
    set, explicitly persistence-free. Adapter state about what is in flight
    dies with the process; a crash mid-task orphans the worker with nothing
    tracking it. `web_adapter.py:135-158`.
12. **No transactionality between the state DB and the filesystem.** Named as a
    known gap in `NEXUS_HANDOFF.md`. A task can be registered without a folder,
    or foldered without being spawned.
13. **No orchestrator-side pending list.** The orchestrator has no record of
    what it dispatched and no timer on it, so "nothing came back" is
    indistinguishable from "nothing was sent" and from "still working".
14. **Hand-delivery has no receipt.** The documented fallback (`SendMessage` to
    a standing pane) is explicitly described in the protocol as producing no
    task folder, no result block and no automatic paste-back. It worked on
    2026-08-27 because a human watched it. It is a vanish point too.

The shape of the list: **eleven of the fourteen are silent by construction, not
by bug.** The system reports failures it encounters *inside* the pipeline and
is blind to every failure that prevents entry to the pipeline. An ack designed
against this list has to be emitted by the *receiver* on receipt, before any
parsing or validation, and it has to be visible to the orchestrator in the
orchestrator's own runtime, not pasted into a surface that may not be the one
the orchestrator is on.

## 5. Is there an ack path, even in principle

**In principle yes, in practice no, and never to a terminal orchestrator.**

The designed path is the `<NEXUS_EXECUTION_RESULT>` block, which the adapter
types back into the same chat box it read from. It carries both layers the
protocol describes: adapter machinery (`ok`, `ready`, `spawned`, `state`) and
the worker's own `report.status`. That is a genuine result channel and it does
carry failures, including spawn-time ones.

Its four limits, all OBSERVED in the source:

- It is **the same channel as the input**, so any fault that blinds the reader
  also silences the writer. There is no out-of-band path.
- It only exists **after** a directive has been observed, deduped and parsed. It
  cannot say "I saw something addressed to me and rejected it".
- It is **browser-only**. `send_response` is a Playwright `fill()` plus a click.
  There is no stdout, no file, no socket and no message-bus emitter. Nothing in
  the codebase can deliver an ack to a Claude Code terminal pane.
- It is **not durable**. No queue, no retry, no record of an ack that failed to
  land.

The gap this project should close is narrower and more specific than "build an
ack": there is no **receipt**, meaning no signal emitted at the moment of
observation, before any validation, addressed to the dispatcher in the
dispatcher's own runtime, that says "I have this, id X". Everything the current
system emits is a *result*, and a result is a statement about work that already
started.

## 6. Secrets

Looked at, never opened. No secret material was read, printed, copied or moved.

- Mac, `~/.nexus/recovery-keys/`: one file, `nexus-another-project-preserve-20260825.key`
  (65 bytes, mode 600). Existence noted only.
- Mac, `~/.nexus/preservation/nexus-another-project-preserve-20260825/`: a `.dmg` and its
  `.sha256`. Not opened.
- second-host, `~/.nexus/secrets/` (mode 700): `downstream-upload.keystore` and
  `keystore.properties`. Filenames only.

Note for the bridge design: `~/.nexus` is a shared namespace holding both task
working directories and Android release signing material, on two hosts. A
broker that routes work between runtimes and creates task folders under
`~/.nexus/tasks` is one path-handling bug away from a worker with a working
directory adjacent to the upload keystore. Worth an explicit boundary in Phase
4 rather than an assumption.

## UNVERIFIED

- I did not observe the machine on 2026-08-27. "The adapter was not running" is
  reconstructed from artifacts (empty registry directory, browser profiles and
  registry both last touched 2026-06-14, zero `agent_prompt.md` anywhere on
  either host, no processes, no `nexus-*` tmux session). The artifacts agree and
  I know of no reading in which it ran, but it is a reconstruction.
- I did not run the adapter's 364-test suite and did not execute any part of it.
  Behavioral claims about `process_cycle`, `send_response`,
  `seed_dedup_from_state` and `execute_directive` are read from source, not
  measured.
- Vanish points 5, 6, 7, 9 and 10 are read from code paths, not reproduced. They
  are plausible failure modes with cited lines, not observed incidents.
- I did not inspect Rohan's claude.ai browser history, so I cannot say whether a
  browser orchestrator tab was open on 2026-08-27. It would not change the
  conclusion, since no adapter process was there to read it.
- `~/.claude/history.jsonl` on second-host matched the directive grep. I did not
  read it, so I do not know whether it records adapter use or only chat text.

## Where I think the brief is framed wrongly

Three things, offered as challenges rather than corrections.

**"Silent failure is the thing the new system exists to prevent" understates
it.** The failure here was not that a dispatch failed silently. It is that the
transport had been dead for over two months while a document describing it as
alive was carried into a new runtime and followed. Every error path in the
adapter works. What is missing is not error reporting, it is **liveness**: no
component of NEXUS ever asserts that a counterpart exists. Build the receipt,
but build the heartbeat with it, or the bridge will have the same hole with
better naming, exactly as feared.

**The autopsy's most useful finding may not be about the adapter at all.** The
document said the adapter watches the chat. The orchestrator read that and
believed it, then behaved as if a system existed, and no observation contradicted
it for forty minutes at a time. The real defect is that **a protocol document
was the only source of truth for a runtime capability**, with nothing checking
it against reality. Whatever the bridge builds, the claim "runtime X can
receive a dispatch" should be a **measurement the broker takes**, not a sentence
in a markdown file. That is also, I think, the strongest argument for the
project's own Phase 0 discipline.

**"It replaces the current NEXUS adapter" is probably the wrong relationship.**
The adapter is a competent, tested piece of work with a real architecture
(state machine, error vocabulary, report contract, topology routing). Its
weakness is one specific and replaceable component: DOM scraping as a transport,
chosen because the orchestrator was on a Max-plan web chat rather than the API,
which `NEXUS_HANDOFF.md` names as a deliberate tradeoff. Layers 1 through 9 of
its pipeline are transport-independent. Reusing them behind a real message bus
is likely cheaper than a rewrite, and it means the disagreement property this
project actually cares about arrives sooner.

