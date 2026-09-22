# nxb-082: checkpoint then reset, and the other three levers

2026-09-12. Rohan: "explore how we can integrate Obsidian even more so that
we can save hella on context." Approved for build the same evening. Four
levers, each sized against the Pact run before it was built. The vault and
the caps are from nxb-081 (`docs/CONTEXT-STORE-nxb-081.md`).

## The four terms, measured

| term | measured on Pact (1,364M input) | lever |
| --- | --- | --- |
| context above a 100K ceiling | 421M (31%), against 117M above 160K | checkpoint to the vault, then a 100K default ceiling |
| files workers read to orient | 1,440 reads, 967 markdown, 416 code | a map note per project |
| status-style operator and chairman turns | 59 turns, 1,224 requests, 150M (11%) | an Obsidian Base over the vault |
| state-note updates that rewrote the whole note | about 6K output tokens each | `context patch` for one section |

## 1. Checkpoint then reset

The runtime's compaction is opaque: the vendor's prompt writes a summary
nobody can read or correct, and the pane carries on from it. That is what
made a low ceiling unsafe. Now, when a pane's context passes 80 percent of
its ceiling:

1. nxb types an unmarked operator note asking the pane to write a
   CHECKPOINT NOTE (goal, task ids, decisions, done with paths and shas, what
   remains, exact next step; at most 8,000 characters) with
   `nxb context put --key rigs/<rig>/checkpoints/<pane>`, then print
   `[NXB-CHECKPOINT <name>]`.
2. nxb waits for both the marker and the file. If either is missing after
   the deadline, nothing is reset (`rig_checkpoint_unconfirmed`).
3. nxb clears the pane (rule and role re-typed for Codex, verified) and types
   the continuation: for a worker mid-task a MARKED directive carrying the
   SAME task id, so the worker validates it as it validated the original and
   reads its checkpoint first; for an orchestrator an unmarked note.

The gauge is the runtime's own transcript, read from its last 256 KB: a
Claude session's last `usage`, a Codex rollout's last `token_count` (which
also names the window: 258,400 on gpt-6-astra). No tokens are spent reading it.

```
python3 -m nxb rig health --session S            # context_tokens, fraction
python3 -m nxb rig checkpoint --session S        # one pass over the rig
python3 -m nxb rig checkpoint --session S --worker "S W" --force
python3 -m nxb rig watch --session S --interval 60   # the detached watcher
```

`rig watch` is the watcher a fleet should have had: it reads the gauge and
checkpoints what is over the line, and types nothing else. It is not
started for you; run it detached per rig, as the Pact watchers were.

With the checkpoint in place the default ceiling on both runtimes is now
100,000 tokens (was 200K Claude, 160K Codex). Per-agent `context_limit`
still overrides it; the Claude floor is 100K.

### Measured after the first live run (nxb-082.1)

`claude --autocompact N` names a WINDOW, not a trigger. With
`--autocompact 100000`, pact-dev Builder 1 (Opus 5, claude 2.1.270)
compacted at 67,173 tokens of context, a few file reads into its first
task: Claude Code compacts about 33K below the window it is given. So the
runtime now receives the ceiling PLUS a margin (45K on Claude, 20K on
Codex, capped at the model's window) as its backstop, and nxb's own
checkpoint at 80 percent of the ceiling is what fires first. With the
100K default: checkpoint at 80K, vendor compaction at about 112K if the
watcher missed. `runtime_backstop()` in `nxb/rig.py`.

### The floor, and the tool schemas in it (nxb-082.2)

Explaining that compaction produced a second number. A fresh interactive
Claude pane's first request carried 42,684 tokens; the same pane launched
with `--tools Bash,Read,Edit,Write,Glob,Grep` carried 23,449; dropping the
MCP servers changed nothing (their schemas are deferred, about 400 tokens).
The difference is the schemas of built-in tools a rig pane never uses:
Agent, Artifact, Workflow, Skill, the cron and design tools, web fetch and
search. About 19K tokens on every request of every pane, and 19K of the
ceiling the work cannot use. Rig panes now launch with the core set; a
draft can say `tools: all` or name a list. The incident write-up is in the
vault at `notes/incidents/2026-09-12-builder1-compaction`.

## 2. Map notes

`maps/<project directory name>`, at most 12,000 characters: every module and
entry point, what each is for, how to build and test, the gotchas. The
orchestrator brief checks `nxb context map --session S` and, if MISSING,
makes its first directive the writing of one. When it exists, every
directive's ORIENT FIRST sentence names it too: read it instead of exploring,
and say in your report if it is wrong.

## 3. The dashboard

A new vault gets `NXB.base`, an Obsidian Base with four table views over the
frontmatter nxb writes: tasks (cards by rig, worker, summary), state notes,
checkpoints, reports. Open the vault folder in Obsidian and "where are we"
costs nothing. nxb writes the file once and never overwrites it, so your
edits to the views stay.

## 4. Section patches

`nxb context patch --key rigs/S/STATE --section "Done" --file f` replaces one
heading section (any level, matched by text) or, with `--append`, adds to
it; a missing section is appended at the end. The note's cap still applies
to the result. The brief now updates the state note this way and never
rewrites it whole. Same over MCP as `nxb_context_patch`.

## Where the vault lives

`nxb context relocate --to ~/Vellum/NXB` moves the vault into a folder
inside an Obsidian vault and records the path in `~/.nxb/vault.path`, which
every nxb process (the Studio service, each MCP server, the shell) reads, so
no environment variable is needed. `NXB_VAULT` still overrides.

## Projection

Baseline 1,364M; after nxb-079 roughly 450M to 500M; with the nxb-081 store
roughly 300M; with these four levers roughly 120M to 150M. Still a
projection from measured terms, verified only by the next real programme.

## Not done

- The watcher is per rig and started by hand. A Studio toggle to run it for
  a standing rig would be the natural next step.
- A checkpoint replaces the runtime's compaction only when the watcher gets
  there first (80 percent of the ceiling, against the vendor's own trigger
  nearer the window). A pane that fills faster than the watcher's interval
  still compacts the vendor's way; the interval is the knob.
- Map notes are written by a worker and kept by the orchestrator; nothing
  measures whether a map is stale except a worker saying so.

## Measured on the second live run (nxb-082.3)

2026-09-12, 11:10 PM to 11:56 PM, pact-dev: a Fable lead and two Opus
builders on two small page changes. The work was done on disk inside an
hour; the hour after that went to the checkpoint pass itself. Six defects,
all in the mechanism, all fixed the same night (FINDINGS RIG-35, RIG-36).

| what happened | why | now |
| --- | --- | --- |
| the lead confirmed its note in six passes running and was refused `rig_pane_busy` six times, at a full 140K-context request per pass, and reached 101 percent | the reset was tried two seconds after the marker, while the turn was still ending, and the next pass asked again | a pane whose marker is on screen over a note newer than its last reset is OWED the reset and is never asked again; the reset waits up to 120 s for the pane to go idle, and a pane still mid-turn keeps its note for the next pass |
| the rig went unwatched for eleven minutes; Builder 1 reached 104 percent and Builder 2 reached 108 and was compacted by the vendor | one 300 s wait per pane, in series | every full pane is asked before any waiting, under one clock |
| Builder 2 printed its marker a minute after the deadline and sat idle for twenty minutes | the next pass read it under the threshold and skipped it | owed resets do not consult the gauge |
| a worker asked for 8,000 characters wrote 8,713 and spent seven full-context requests trimming | the request named the cap as the limit | the request asks for about 8,000 and the vault accepts up to 12,000; cut sections, never count |
| `rig health` showed `last_checkpoint_at` null after three real checkpoints | the pass saved a stale copy of the record after each | the stamp and a healed session id are merged into a fresh load |
| an operator draft left unsent in the lead's composer would have turned `/clear` into a message | Claude Code appends typed text to the draft | `reset_pane` empties a Claude composer with Ctrl-U first |

Also that evening, on ht-android-v2 (five Codex panes): a client attached
at 92 columns squeezed the worker panes to 22 columns, Codex truncated its
composer placeholder to "Ask Codex to do anyt", and every fresh dispatch
was refused `rig_pane_not_ready` after `/clear`, 28 times. The ready marker
is now the prefix.

And one that is a rule, not code: an orchestrator that superseded a task
whose worker had the fix done and the suite running, because a WAITING
looked idle. WAITING now carries `last_activity_s` from the worker's own
transcript, and `--supersede` refuses `task_worker_active` inside five
minutes of it unless `--force` (RIG-35).

What the operator sees when it works: a worker prints its marker and stops;
within a minute its pane is cleared and it is typing again from its own
note at about 25K. Builder 1 was the first pane reset this way by the
fixed pass, at 11:56 PM, from a note it had written four minutes earlier
and that the old pass had already given up on.

## The morning after (nxb-082.4)

2026-09-13, 11:30 AM. The pact-dev rig had been standing and quiet since
3:20 AM: both tasks filed, both builders idle, the watcher's log eight
hours long. Two defects came out of reading that log rather than out of
anything going wrong (FINDINGS RIG-41, RIG-42).

| what the log showed | why | now |
| --- | --- | --- |
| `Builder 1=?` in every line from 3:14 to 11:32 AM, 490 lines of it | the pane was relaunched at 3:13 AM and never asked anything, and Claude Code writes no transcript until a session is asked something | a pane the registry vouches for, with nothing answered, reads **0 percent**, not `?`. `?` now means only that the gauge cannot find the pane, which is the one thing an operator scans the log for |
| both builders read `?` again at 11:42 AM, the minute after they were cleared | `/clear` writes the transcript IMMEDIATELY, holding only `custom-title`, `agent-name`, `mode` and `bridge-session`, so the file's absence was the wrong test for a fresh session and its presence was the wrong test for a used one | a transcript the tail read WHOLE with no answered request in it is zero, whether the pane was just cleared or its first turn is still in flight |
| nothing at all about the 1:10 to 1:40 AM stall, the worst of the night | the rig watched the rig; the machine underneath it was swapping 25 of 26 GB behind eight simulators booted by other sessions, and no rig readout has ever named memory, swap, load or simulators | every watch line ends with `mem 3.2G, swap 2.8G, load 4.3, 1 sim, 7 orphan companions`, and `rig health` carries the same block. `MACHINE STRAINED` is prefixed only on critical pressure, swap at or above 8 GB, or load at or above twice the core count |
| two builders at 39 and 43 columns, the RIG-37 condition, reported as widths in `rig health` and nowhere else | an operator client attached at 83 columns shrinks every pane of a 240-wide rig | the watcher names narrow panes **and the client widths that caused them**, on the first pass and whenever the set changes, then stops. A grievance repeated once a minute is not a report |

Two smaller things measured the same morning and now depended on. The
session registry's `tmux` field carries the PANE ID, which is a stricter
key than the declared name: it cannot collide across two rigs and it is
right during the seconds before a rename lands, so the gauge resolves by
pane first and by name second, and where two records claim one pane the
newer `startedAt` wins. Which of the rig's record and the registry is
STALE was measured both ways on consecutive days, the registry fresher on
the 12th and the rig record fresher at 11:42 AM on the 13th, so the gauge
now prefers neither by rule and takes whichever names the newer
transcript. And `kern.memorystatus_vm_pressure_level` sat at
`warn` for ten unbroken minutes on a Mac with 3 GB free, no swap growth and
a load of 3.5 on ten cores, which is a working machine; a watcher that
shouts on `warn` is a watcher nobody reads.

Then the rig went back to work at 11:45 AM and showed the pass its own
limit. Builder 1 read 43 percent at 11:50:47, 72 percent at 11:51:47 and
102 percent at 11:54:18 on a 140K ceiling: it crossed the 80 percent line
entirely between two passes, and the level rule never saw it. Everything
after that worked, the request went in, the pane wrote its note, the owed
reset finished it at 11:55:18 and Builder 1 came back at 59 percent, but
103 percent of 140K is about 8K short of where Claude Code's own
compaction fires behind a 185K backstop. Shortening the interval does not
fix it: the pane rose 40K inside that minute, and a checkpoint takes about
three more, measured request at 11:52, PENDING at 11:54, reset at 11:55:18.

So a pass now projects. It keeps the previous reading in the watch loop's
memory and asks a pane that its own observed rate would carry past the
CEILING within four minutes, the interval plus the measured cost of a
checkpoint, even when it is under the threshold. Only above half the
ceiling, because a pane with more room than that has another pass in hand
whatever it is doing, and only against the level test: a worker with
nothing outstanding is still skipped, since its next dispatch resets it for
free and a builder the operator is talking to must not be cleared out from
under him. Against the measured sequence the rule fires at 72 percent, one
pass earlier, and stays silent at 43 percent and at a steady 72 (RIG-43).

Reconstructing the same hour from Builder 1's transcripts rather than
from the watcher's one-minute samples showed the larger thing. **Asking a
pane for a checkpoint costs about 35K of the context it is meant to
save.** Asked at 100,503 tokens it peaked at 143,970 before its reset;
asked at 114,055 it peaked at 146,631. Rises of 43K and 33K on a 140K
ceiling, and they are not waste: the pane finishes the turn it was in,
writes a note of up to 12,000 characters, files it with a shell command
and prints its marker, and every one of those is a full-context request.

A flat 80 percent threshold therefore lands a 140K pane at about 145K and
a 100K pane at about 115K. That is the arithmetic behind a symptom already
in this file: 100K Opus panes were compacted by the vendor four times in
one night and took five resets on one task, which had been read as the
ceiling being too small when it was the threshold not allowing for its own
cost. The threshold is now derived per pane, `(ceiling - 35,000) /
ceiling`, never above 0.8 and never below the rate floor: 140K asks at 75
percent, 100K at 65, 150K at 77, and a Codex 258K window is unchanged at
80. Below about 70K of ceiling the floor binds and the pane will still
overshoot, which is the honest limit of a small ceiling (RIG-44).

One thing this morning did not explain: two lines at 11:47 and 11:48 AM
read `Builder 2=?` and then resolved on their own, and nothing recorded
which branch of the gauge produced them. A `?` now carries the gauge's own
reason with it, in the watch line and in `rig health`, so the next one
names itself instead of being diagnosed from scratch.

Left standing, for the operator: seven `idb_companion` daemons were still
running with one simulator left on the machine. They are counted in the
machine line as orphans and nothing kills them.

## The afternoon, when the fix became the fault (nxb-082.4)

Two more, both from watching the morning's own changes run on a working
rig (FINDINGS RIG-45, RIG-46).

**A clear that landed after its proof window stranded a worker.** At
1:37:56 PM, under 11 GB of swap and three simulators, Builder 2 was asked
for a checkpoint, wrote its note at 1:40:31 PM and printed its marker. The
pass typed `/clear`, the session id did not rotate inside RIG-39's 20
second proof window, and the reset refused `rig_reset_unconfirmed` and
typed nothing more, which is exactly right: it could not vouch for the
pane. The clear then landed a moment later. Builder 2 sat empty at 0
percent, idle, holding a task issued at 1:19 PM, with its note safe on
disk and nothing to set it going again.

Nothing would have recovered it. `_owed_reset` keys on the marker being on
screen and the clear had erased it; `checkpoint_requested_at` was stamped
1:38 PM, so every pass for fifteen minutes read PENDING and did nothing,
after which it read 0 percent and was skipped as below the threshold. It
was restarted from outside the watcher between 1:42 and 2:19 PM, so the
recovery has not yet run on a real stranded pane.

An unproven clear is not an unsent one. The reset half and the
continuation half are now separate. On a `rig_reset_unconfirmed` refusal
the pass stamps `reset_unproven_at` and clears the pending stamp, and a
later pass continues the pane from its own note. The condition is derived
from state, not from that flag, deliberately: the pane that produced the
finding was stranded before the flag existed, and a recovery that only
knows about faults recorded since it shipped is not a recovery. A pane
holding a task, not busy, whose gauge reads fresh with nothing yet asked
of that session, whose note is newer than its last reset and at least two
minutes old so it cannot race a dispatch just typed, is continued and
named in the watch line as stranded.

**And the morning's rate rule was reserving the same headroom twice.**
Between 2:39 and 3:58 PM Builder 2 was checkpointed twelve times in a
hundred minutes, six of them below its own ask-line, at 61, 68, 71, 70, 59
and 59 percent. At about 35K an ask, the rule meant to stop a pane
overrunning its ceiling was spending most of a ceiling to prevent it. The
error is arithmetic: RIG-44 already reserves 35K below the ceiling for
what the ask costs, and RIG-43 then projected four minutes of rate at the
CEILING on top of that. The rule now asks the honest question, whether one
more pass would carry the pane past the line it would be asked at anyway:
one interval, against the ask-line. It still fires at 72 percent on the
sequence that motivated it, and leaves a pane at 59 percent rising 15K a
minute alone (RIG-46).
