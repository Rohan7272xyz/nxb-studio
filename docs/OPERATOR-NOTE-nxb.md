# nxb: what it is and how to turn it on

For Rohan. Nothing here requires reading the source.

## The two commands

Run each once. `--scope user` matters: without it Claude Code registers the
server against whatever directory you were standing in, and it then works only
there. Tested on 2026-08-28, both added, connected, called, and removed again.

```sh
claude mcp add --scope user nxb \
  --env NXB_LEDGER=$HOME/.nxb/ledger.db \
  --env PYTHONPATH=$HOME/dev/nexus-bridge \
  -- $(which python3) -m nxb.mcp

codex mcp add nxb \
  --env NXB_LEDGER=$HOME/.nxb/ledger.db \
  --env PYTHONPATH=$HOME/dev/nexus-bridge \
  -- $(which python3) -m nxb.mcp
```

Check it took: `claude mcp list` should show `nxb ... ✔ Connected`.
To undo either: `claude mcp remove --scope user nxb` / `codex mcp remove nxb`.

**Use an absolute python path if `which python3` might differ later.** The one
tested resolves through mise, and if that moves the server stops starting.

## The three tools

- **`nxb_dispatch`** — hand it a directive and a runtime (`claude_code` or
  `codex`); it starts a fresh worker, waits, and returns that worker's report.
- **`nxb_collect`** — fetch a past outcome by its `dispatch_key`. Safe to call
  repeatedly; reading consumes nothing.
- **`nxb_pending`** — outcomes nobody has collected. The alarm. It reports a
  count, so an empty list and a firing alarm do not look alike.

**The worker cannot see your conversation.** It gets only the directive, so
every path, precondition and acceptance criterion has to be inside it. That is
not a limitation to work around; it is what makes the worker's answer
independent of your framing.

## The ledger

`NXB_LEDGER` is where state lives. It must be **absolute** and there is
deliberately no default: a path relative to a working directory means two
sessions disagree about whether a piece of work already happened, which is a
real defect this had and no longer does. `$HOME/.nxb/ledger.db` is a fine
choice. It is created on first use.

## What a dispatched worker can do

Plain words, measured by reading the worker's own startup report rather than
trusting the flags passed to it.

**Default grant, which is what you get unless you ask otherwise:**

- **No shell.** No Bash, no code execution, no web fetch, no cron, no workflows.
- **None of your connected accounts.** Gmail, Drive and Calendar are dropped.
- It runs in **its own scratch directory**, not in any repo of yours.
- **It cannot reach your other sessions.** No SendMessage, no ListAgents, no
  spawning sub-agents, no cron, no push notifications, no remote triggers.
- It **can** read and write files in its scratch directory, and search the web.

Measured by reading the worker's own startup report: **9 tools**, 0 connected
MCP servers, versus 32 tools and 3 servers for an unrestricted session. The 9
are Read, Write, Edit, Glob, Grep, NotebookEdit, WebSearch, Skill and
ReportFindings.

**Why this matters given how you run things.** Your agents run in bypass mode,
so a session that receives a message acts on it without asking you. A worker
that could message your fleet would be a way for a dispatched task to make your
other sessions do things. It was measured doing exactly that on 2026-08-28, and
that is what this ban is for.

**If a future update adds a new tool of that kind, the dispatch FAILS rather
than quietly widening.** nxb reads back what the worker actually holds and
refuses to use it if anything on the ban list survived. You will see
`grant_violation` naming the tool.

**If a task genuinely needs a shell**, ask for it in the tool call:
`grant: "shell"`. That restores commands and the runtime's own tooling. It is
a deliberate choice each time, it is recorded in the outcome, and it is never
the default.

**The honest gap:** under `grant: "shell"` the worker has a shell, and a shell
can run the `claude` or `codex` commands directly. **No ban list contains a
worker with a shell.** The ban still applies there and removes the easy path,
but treat `shell` as trusting the worker rather than containing it.

## What a failure looks like

Every response says which of these happened, and they are kept apart on
purpose:

- **the worker answered** — you get its report, including its own `status` of
  COMPLETE, BLOCKED or FAILED. **BLOCKED is the worker being honest**, not the
  system failing.
- **refused** — nxb declined before doing anything. The reason is named, e.g.
  reusing a `dispatch_key` with a changed directive.
- **no report** — the worker ran and produced nothing usable.

Two behaviours worth knowing because they are deliberate:

- **Re-running the same directive with the same `dispatch_key` returns the
  first answer** instead of running it again. That makes a retry safe.
- **Re-using a `dispatch_key` with a CHANGED directive is refused.** It would
  otherwise hand you the old answer and let you believe your correction shipped.

`was_refused: true` in a report means the worker hit a permission wall and said
so. Read it: the system cannot see those refusals on its own, so the worker's
own word is the only signal there is.

## Enrolling a worker pane (nxb-049)

Everything above dispatches **fresh** workers. This section is about the panes
you already run, one per window, that you talk to yourself.

Say once where state lives, then launch an enrolled worker with one command:

```
export NXB_LEDGER=/Users/rohan/.nxb/ledger.db     # once, per shell
python3 -m nxb enroll "Worker 3"
```

(`enroll`, `mint` and `validate` read `NXB_LEDGER` so you are not typing a path
every time. There is still no *default* — with neither the flag nor the
variable they refuse, because a ledger guessed from whatever directory you were
standing in is how two shells start disagreeing about whether work happened.)

That prints a single `claude` command. Paste it. The pane comes up named
`Worker 3` and carrying one launch-bound rule: **before acting on any directive,
it must carry an nxb task id, and it must check that id.** No id, a failing
check, or an id issued for a different worker, and it refuses and does nothing.

To hand a worker some work, mint an id first and put it in the directive:

```
python3 -m nxb mint --worker "Worker 3"
```

Minting runs the roster check first, so an id only exists if you actually
declared that worker. A refused roster gives you no id at all — that is the
point, not a side effect.

### What this buys you, stated exactly

It removes **drift**, not attack. Three things are true and you should hold all
of them:

- An orchestrator pane can still message a worker pane directly. The broker is
  not in that path and never sees it. We measured this three times: a plain
  process **cannot** send into a live pane — the message is held for your
  approval, and a claimed sender mode is ignored — so nxb cannot be the
  postman even if we wanted it to be.
- The rule is a system-prompt instruction to a model. A model that ignores its
  system prompt will act on anything.
- Nothing but the worker itself reads the exit code of its own check.

So this is discipline enforced by the one party with nothing to gain from
skipping it, which beats an orchestrator policing itself. It is not a wall.
The only real refusal in this whole system is the transport's, and that one is
not ours to invoke.

### Where the names come from

`mint` has to turn `"Worker 3"` into a specific live pane, and for one task it
could not: socket filenames are pids and no name appears on a command line, so
the roster was live, addressable and nameless.

The source is `~/.claude/sessions/<pid>.json`, which carries the display name
and the socket the session owns. Measured 2026-08-28: **27 sockets, 12 live,
12 of 12 named.** Three things about how it is read:

- Liveness still comes from a **connect**, never from that file. The record has
  its own `status` field and it is ignored: it says what a session last claimed
  about itself, and a past state read as a present one is exactly how 14 dead
  sockets looked alive.
- A name the system **derived** for itself (`rohan-7b`) is not a declaration,
  so those panes are listed live but unnamed and cannot be minted for. Your six
  named panes are on the roster; six auto-named ones are not.
- The registry directory also holds `.key` files. Those are secret material and
  nxb never opens them; only `*.json` is read, and a test asserts it.

So a pane you did not name cannot receive an id, which is the roster ceiling
doing its job rather than an inconvenience.

### Codex cannot hold an enrolled worker

Verified, not assumed: `codex` has no `--name`, no `--append-system-prompt`,
and no way to inject instructions through `-c`. Its only instruction channel is
a project-scoped `AGENTS.md`, which is the read-it-and-hope shape this project
exists to replace. So `nxb enroll --runtime codex` **refuses**, with the reason
`runtime_cannot_enroll`, rather than pretending to enrol and producing a pane
that silently obeys anyone. Codex remains fully usable as a dispatched worker;
it just cannot be a *named, enrolled* one.

## The pane rig: standing up a scenario (nxb-050)

One command builds Scenario 2 — a Codex orchestrator on top, four workers
below, two Claude and two Codex, every one named, the Claude ones enrolled:

```
export NXB_LEDGER=/Users/rohan/.nxb/ledger.db
python3 -m nxb rig up --dir /Users/rohan/workspace
tmux attach -t nxb
```

`--dir` is where the panes work. `--session` names the tmux session (default
`nxb`). To take it down: `python3 -m nxb rig down`.

### Clearing every pane, which you have been doing by hand

```
python3 -m nxb rig clear
```

A pane cannot clear itself, so this has been a manual step all day, once per
pane. It now works for **both** runtimes. Clearing does not change a Codex
pane's thread id, so a cleared worker is still addressable.

### Two things it refuses, on purpose

**A directory neither runtime trusts.** Both Claude and Codex ask before
working in an unfamiliar directory, in different words, and trust is per exact
path — `/Users/rohan` being trusted does *not* cover
`/Users/rohan/dev/nexus-bridge`. The rig will not answer that dialog for you:
granting trust loads project-local config, hooks and exec policies, and that is
your decision. It stops, names the pane, and tells you to answer it once. As of
today `~/workspace` is trusted by both; this repo is trusted by neither.

**A session that already exists.** Those panes may be running your work, so it
refuses rather than replacing them.

### How a directive reaches a worker: nxb types it

nxb does **not** use each vendor's own messaging to dispatch. It types the
directive into the pane, the same way for Claude and Codex, and every typed
directive carries a marker and a minted task id:

```
[NXB-AUTOMATED] task_id=nxbt-... worker='CX Worker 1' :: <the directive>
```

Every worker, on both runtimes, runs the same rule: **if a message is marked,
it must carry a task id that validates, or refuse and do nothing. If it is not
marked, it is you typing, and it is treated normally.**

```
python3 -m nxb mint --worker "CX Worker 1"
python3 -m nxb rig send --worker "CX Worker 1" --task-id nxbt-... --message "..."
```

You do not name the tmux session: `mint` counts every rig recorded next to
the ledger, and `send` finds the one rig standing. `--session` exists for the
day two rigs stand at once, and `send` refuses with both names rather than
guessing. (An earlier version assumed a session literally named `nxb`; when
the standing rig was `nxb-s2`, the refusal blamed the roster. RIG-4.)

### Getting the answer back

`send` types and returns immediately. To read what the worker said:

```
python3 -m nxb rig collect --worker "CX Worker 1" --task-id nxbt-...
```

Every automated directive now ends by asking the worker to print
`[NXB-DONE <its task id>]` as its last line, and `collect` returns everything
between the directive and that marker. The marker carries the task id, so an
answer is tied to the directive that asked for it and a stale reply on the
same pane cannot be mistaken for this one.

Three answers, and the middle one is the point:

- **ANSWERED** (exit 0) the marker for this task is on the pane; you get the
  text, including the worker's own `validate` call, which is your evidence the
  id check actually ran.
- **WAITING** (exit 4) no marker yet. **A worker still thinking and a worker
  that refused and correctly did nothing else look identical from outside**,
  so this never guesses: it hands you the pane tail to read. `dispatch_seen`
  tells you whether the directive landed at all. Collecting again costs
  nothing.
- **REFUSED** (exit 3) no such rig, or no such worker.

WAITING is deliberately not exit 0, so a script cannot mistake an answer that
has not arrived for one that has.

**Why this exists:** until 2026-09-03 there was no collect at all. `send` typed
and returned, and reading the reply was left to whoever remembered to look.
Rohan asked the right question in the middle of a demonstration: if the worker
got it wrong, who catches that? Nothing did. RIG-5.

Only the delivery of the rule differs: Claude gets it at launch through
`--append-system-prompt`, Codex has it typed in as its first message once it
has a name.

**Verified live on 2026-08-28, three cases per runtime, all six as designed:**

| what was sent | Claude worker | Codex worker |
|---|---|---|
| marked, valid id for that worker | ran the check, then acted | ran the check, then acted |
| marked, id minted for a *different* worker | refused, named the reason | refused, named the reason |
| unmarked | acted, as the operator | acted, as the operator |

### Two things to hold about this

**Unmarked input is trusted as you.** That is the design — it is how you keep
being able to type to your own panes — but it means anything on this machine
that can type is you, as far as the rule is concerned. `codex queue` still
reaches a Codex pane and nothing gates it; it simply arrives unmarked, so it is
treated as you rather than as a dispatch. Reachability is no longer the
question. This is drift control, not a wall.

**The two runtimes hold the rule differently, and one is weaker.** Claude's
rule arrives as a system prompt: structurally above every later message,
impossible to un-read. Codex's is typed as a first message, and a first message
can be argued with, outweighed by later context, or pushed out of the window.
It held across the three cases above. Whether it survives a fifty-turn session
is **not measured** — see RIG-3. Do not assume the two are equivalent because
the wording is.

## What this does not do

It starts **fresh workers**. It does not talk to your existing Claude Code
panes, which hold context a new worker does not. Those remain a different
thing, reached the way you reach them today.

Enrolment (above) reaches named panes you launch yourself, but only for the
task-id discipline. Existing panes already running stay as they are.

## The orchestrator drives it, not you (nxb-054)

Everything above is the plumbing. You are not meant to type it.

The rig's top pane is the orchestrator seat, and until 2026-09-03 it was
handed the WORKER rule -- so the seat built to drive the fleet had never been
told that `mint`, `rig send` or `rig collect` exist. It now gets a brief at
stand-up that carries:

- how to list its own fleet: `python3 -m nxb rig workers`
- the three dispatch steps, mint then send then collect
- **the ceiling**: those workers are the only ones that exist, neither it nor
  nxb can create one, and if a task needs a worker that is not there it must
  STOP AND ASK you rather than substitute another or quietly do the work
  itself
- **WAITING is not an answer.** Never report one it did not collect.
- when asked to verify, dispatch to workers on DIFFERENT runtimes, because two
  workers of the same runtime agreeing is weak evidence

So your interface is a sentence to the top pane. The commands are its job.

To brief a pane in a rig that is already standing, without rebuilding:

```
python3 -m nxb rig orchestrate --worker "Orchestrator"
```

## Finishing up

```
python3 -m nxb rig down --session nxb
python3 -m nxb revoke --all          # optional: invalidate outstanding ids
```

Task ids do not expire and are not consumed when used, so they stay valid
until revoked. `revoke` takes one id, `--worker <name>`, or `--all`, and tells
you how many it actually revoked so revoking nothing cannot look like success.

**Name the session explicitly on `down`.** tmux resolves a session target by
PREFIX, so a bare `nxb` once matched and killed a rig actually named `nxb-s2`
while reporting the name `nxb`. nxb now uses exact matching internally, but the
habit is worth keeping.

## Composing a fleet, and running more than one (nxb-060)

The shape is yours. `--workers` takes `runtime:count` pairs (`cc` and `cx` are
accepted short forms), and `--orchestrator` says who drives:

```
python3 -m nxb rig up --session lab --orchestrator cc --workers cx:3 --dir ~/dev
python3 -m nxb rig up --session solo --orchestrator none --workers cc:1
python3 -m nxb rig up --workers cc:2,cx:2 --orchestrator codex     # scenario2
```

A Claude orchestrator works and gets the same brief a Codex one does. Until
today it would have launched carrying the WORKER rule, because role was
honoured on the Codex path only and every rig so far happened to put Codex in
that seat.

### Two rigs at once

Give each one a `--session` and they do not touch. Verified with both
standing: separate tmux sessions, separate panes, separate rosters, and each
orchestrator's brief names its own rig in every command it runs.

**A worker's name carries its rig**, so there is no collision to worry about:

```
nxb Orchestrator   nxb CC Worker 1   nxb CX Worker 1  ...
lab Orchestrator   lab CX Worker 1   lab CX Worker 2  ...
```

Use the full name, exactly as `rig workers` reports it. A bare `CX Worker 1`
names nobody now. In exchange, `--session` is never needed to say WHO you
mean, because no two workers anywhere share a name:

```
python3 -m nxb mint --worker "lab CX Worker 1"   # no --session required
```

This started as a refusal: an ambiguous name was detected and rejected. Rohan
asked why the name was ambiguous in the first place, which is the better
question. A refusal that fires during ordinary use is a design admitting it
could not make the bad state impossible. The refusal is still there and can no
longer fire in normal use -- it now only catches a regression in the naming
itself.

### Where a pane's rule actually lives

`~/.nxb/briefs/<session>--<name>.txt`, and the launch command reads it. It
used to be embedded in the command itself, which was typed into a shell -- and
a terminal silently drops input past about 1024 bytes. The worker rule was
1014. Ten bytes of headroom, recorded nowhere, so the next sentence anyone
added would have truncated every Claude worker's rule without a word. The
orchestrator brief at 3891 bytes had already crossed it, which is how it was
found. Reading it from a file makes the typed command ~150 bytes no matter how
long the rule grows, and the brief is now a file you can open and read.

## The studio: compose a fleet visually (nxb-062)

**What it is, in three sentences.** The studio is a page nxb serves from your
own machine where you draw the fleet you want: drag orchestrators and workers
onto a canvas, say which vendor each one runs, and name the rig. Press Bring
it to life and those boxes become real terminal panes in tmux, each one a
running Claude or Codex session that is named, enrolled, and ready to take
work. It is a control surface for agents you own: nothing runs that you did
not place on the canvas, and the panel on the right shows every fleet that is
currently standing so you can tear one down when you are done with it.

```
python3 -m nxb studio          # a browser tab
python3 -m nxb studio --app    # a chromeless window, if you have Chrome/Brave
```

It prints a URL with a token and opens it.

### Making it a real app

On this Mac there is only Safari, and Safari has the better answer anyway:
open the URL and choose **File > Add to Dock**. You get an entry in
`~/Applications`, a Dock icon, its own window with no browser chrome, and a
place in Cmd-Tab -- the same mechanism behind the Gmail and YT Music apps
already there.

**The token is persistent so that this works.** Add to Dock freezes a start
URL, so a token that rotated every run would turn yesterday's icon into a 403.
It lives 0600 in `~/.nxb/studio.token`; `--fresh-token` rotates it if it ever
ends up somewhere it should not be.

**Keys, once it is a standalone window:** Cmd+T new tab, Cmd+W close tab,
Cmd+1..9 switch tabs, Cmd+Enter bring the current tab to life. In an ordinary
browser tab the browser owns Cmd+T and Cmd+W and wins; in an app window there
is no tab strip to own them.

**Tabs, one per rig.** Like Ghostty's. Each tab holds its own rig name, working
directory, layout and canvas, so you can design several fleets and switch
between them. A tab's dot goes green when that rig is actually standing. Tabs
survive a page reload; they are drafts in your browser, not state on disk.

**A palette you drag from.** Four kinds down the left -- Claude worker, Codex
worker, Claude orchestrator, Codex orchestrator. Drag one onto the canvas to
place it there, or click it to drop one in the middle. Drag placed nodes to
rearrange, and click a node's × to remove it. One orchestrator per rig; a
second is refused rather than silently replacing the first.

Then **Bring it to life**. The rig stands up in tmux the same way `rig up`
does, because it *is* `rig up`. If that rig is already standing the button
becomes **Rebuild** and tears it down first. Standing rigs are listed
alongside, refreshing every few seconds, with a tear-down button each.

**The page reports its own errors.** Its first version rendered an empty
canvas and said nothing, which is indistinguishable from an empty design.
Anything that throws now lands in the log strip at the bottom, and a test runs
the page's script through a parser so a syntax error cannot ship a board that
never loads.

**Why it is served from your machine and not a link.** A page hosted anywhere
else cannot reach 127.0.0.1: browsers block it, and a hosted artifact runs
under a policy that forbids it outright. So nxb serves the page itself and it
talks to its own origin. Nothing leaves the laptop.

**It is guarded, because it spawns unsandboxed agents.** "Only on localhost"
is not a boundary: every page in your browser can send requests to 127.0.0.1,
and a malicious one would enjoy standing up a `--yolo` fleet on your machine.
So: bound to loopback only, a fresh token per run required on every request
including the page load, the `Host` header must be a loopback name (which is
what stops a stranger's domain from resolving to your machine and inheriting
this origin), and the token is compared in constant time. Do not bind it to a
network interface.

**What the diagram controls, stated plainly.** Node positions are for your
head. The pane arrangement comes from the layout selector. What becomes a rig
is the composition: how many workers, of which runtime, under which
orchestrator. The page says so on itself, because a diagram that looks like it
is wiring things up while the wiring happens elsewhere is exactly the
"presents as configuration, functions as a comment" gap this project exists to
close.

### Composing agents individually (nxb-065)

Each node on the canvas is an agent you configure, not a tally. Select one and
the Inspector gives you:

- **Name** -- yours. `API Worker`, not `CX Worker 2`. It is prefixed with the
  rig, so the pane is `atlas API Worker`.
- **Role** -- worker or orchestrator. One orchestrator per rig; a second is
  refused.
- **Provider** -- Claude or Codex. You can also drop a provider chip onto an
  existing node to switch it.
- **Model** and **Reasoning** -- free text with suggestions; these reach the
  real flags: `--model` and `--effort` for Claude, `-m` and
  `-c model_reasoning_effort` for Codex. Leave one empty and no flag is passed
  at all, so the runtime uses its own config -- and the placeholder names
  exactly what that is (`default: opus[1m]`), read from your `settings.json`
  and `config.toml`, so you can see what you would be overriding.
- **Working directory** -- per agent, falling back to the rig's.
- **Startup instructions** -- typed into the pane once it is up, **as you,
  unmarked**. They are you briefing your own pane, so they carry no marker and
  no task id; marking them would misrepresent them and make the worker refuse
  its own setup.

**The suggestion lists are read, not written.** Codex's models come from your
`~/.codex/config.toml`; Claude's aliases from its `--help`. Both fields are
free text, because a hardcoded list here once offered `gpt-5.6` and a live
pane answered `model is not supported`. A suggestion I get wrong costs you a
retype; a closed picker I get wrong blocks a value that works.

**Nothing in the Inspector is decoration.** Every control was checked against
the runtime's own `--help` before it shipped, and anything the backend cannot
honour is either absent or refuses out loud with the reason -- Pane preview
says so rather than drawing an invented picture of a tmux layout.

### What the studio is for, ruled by Rohan

**It architects workflows. It does not run them.** You compose a fleet, stand
it up, and then go to tmux and work there. The studio deliberately cannot
dispatch work or collect answers: the human gate belongs in front of the
panes, not behind a browser button that could send work while you are looking
at something else.

So the honest division is: **studio = design and stand up. tmux = work.**

### Editing an existing rig, and what the chips mean

Any rig in the Live rigs panel has an **open** button that pulls it into a tab
-- names, runtimes, roles, models and efforts read back from the rig itself,
not from anything the page remembered. That works for rigs you stood up from
the command line too.

Each node carries one of three chips:

- **draft** -- drawn, never stood up.
- **live** -- its pane is running.
- **edited** -- its pane is running, but you have changed the drawing since.
  Hover it to see the name it is actually running under. Rebuild to apply.

Tearing a rig down clears those stamps, so a tab never claims panes that are
gone.

**A rig that is down keeps its record**, which is what makes it re-openable.
When you no longer want it listed, the × on a down rig forgets it (or
`python3 -m nxb rig forget --session <name>`). Forgetting a rig that is
STANDING is refused: it would leave a running fleet with no record naming its
panes.

### Undo, and the two confirmations

`Cmd+Z` undoes, `Shift+Cmd+Z` redoes. One undo covers one edit, not one
keystroke -- text fields snapshot when you focus them.

Both destructive actions ask first and say what is lost: tearing a rig down,
and rebuilding one that is already standing.

### Usage, so you can design against headroom (nxb-070)

Always on in the top bar, with the full breakdown under the **Usage** tab.

**What is real, and what is not.** Measured before any of it was built,
because a made-up usage figure is worse than none when you are choosing which
vendor carries a fleet:

- **Codex plan usage is real.** Every rollout records `used_percent`, the
  window length and when it resets. That is read from your newest session.
- **Claude plan usage is real, and costs a turn to ask for.** Nothing is
  written to disk, but `claude -p "/usage"` answers headlessly with *more*
  than Codex records: session, weekly, and per-model. So it is a **button**
  (`↻` next to the claude figure), never a poll -- each refresh is a full
  Claude turn, and polling quota to measure quota is not free. The reading
  always shows its age, because a percentage with no timestamp cannot be
  weighed.
- **Token counts are real for both**, from the transcripts each runtime
  writes, split into today / 7 days / all time.

**Cache reads are shown apart from input on purpose.** 97.7% of your all-time
Claude total is cache reads, which do not cost what input costs. One combined
number would be alarming and nearly meaningless. Nothing is converted to
money, because consumption here may be plan quota rather than per-token
billing.

The scan reads about 3.2 GB the first time (~5s, on a background thread, the
bar says "counting…") and is instant afterwards.

### Roles, and the persona library

The **Role / startup instructions** box on any agent takes a prompt like
*"Act as an adversarial auditor for audit Builder. Challenge every claim."*

**Where it lands depends on the runtime, and the panel tells you which:**

- **Claude** carries it in its system prompt, bound at launch. A later message
  cannot argue it away.
- **Codex** gets it typed as a standing rule when the pane comes up, because
  it has no way to bind one at launch. That is the weaker form and it is
  labelled as such.

**The library grows by use.** Press **save** next to the box to keep a role,
and it appears in the picker for every future agent. After a rig goes up, any
role you used that is not yet saved is offered once -- and never re-offered
once it is in the library.

They live as markdown in `~/.nxb/personas/`, one file per role. That is
deliberate: they are prose you wrote, so you should be able to open, edit,
grep and copy them without this tool.

