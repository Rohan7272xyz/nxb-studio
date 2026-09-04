# nxb — compose a fleet of AI agents, then bring it to life in tmux

Draw the agents you want on a canvas. Press a button. They become real
terminal panes — named, enrolled and running — one per agent, each a live
Claude Code or Codex session you can watch and talk to.

The point is not throughput. It is **disagreement you can attribute**: an Opus
worker and a GPT worker reaching the same answer by different routes is
evidence; two instances of one model agreeing is variance.

---

## FOR THE AI AGENT READING THIS

You are setting this up for your operator. Work through the phases in order.

**Three rules, and they matter more than the steps:**

1. **Verify, never assume.** Every phase says how to check it worked. Run the
   check. This project exists because a document once claimed a capability
   that had been dead for two months and nothing was positioned to notice.
2. **Report what you observed, not that it passed.** If a step fails, say
   which one and paste the output. Do not work around it silently.
3. **Stop and ask** at any step marked **ASK**. Those spend the operator's
   money or launch processes on their machine.

---

### Phase 0 — check the ground

```sh
python3 --version                 # need 3.9+
tmux -V                           # required; the fleet lives in tmux
command -v claude || echo "NO CLAUDE"
command -v codex  || echo "NO CODEX"
```

**Interpret it:**
- No `python3` or no `tmux` → stop. Tell the operator: `brew install tmux`
  (macOS) or their package manager. Everything else waits on this.
- **At least one** of `claude` / `codex` is required. Both is better: with one
  runtime you have automation, with two you have cross-vendor checking, which
  is the reason this exists.
- There are **no third-party Python packages**. If you are reaching for `pip`,
  re-read this line.

### Phase 1 — put it on the path

```sh
export NXB_LEDGER="$HOME/.nxb/ledger.db"
export PYTHONPATH="/absolute/path/to/this/repo${PYTHONPATH:+:$PYTHONPATH}"
python3 -m nxb contract >/dev/null && echo "nxb is importable"
```

Append those two `export` lines to the operator's shell profile
(`~/.zshrc` or `~/.bashrc`) so they persist. Use the **absolute** path to
this clone.

`NXB_LEDGER` must be absolute and has **no default, deliberately**. A ledger
resolved against the current directory means two shells disagree about whether
a piece of work already happened. That was a real defect here.

**Check:** `python3 -m nxb contract` prints JSON. If it prints
`No module named nxb`, `PYTHONPATH` is wrong.

### Phase 2 — run the tests

```sh
PYTHONPATH= python3 -m pytest -m "not spawns_children" -q
```

Expect **400+ passed**. Note the leading `PYTHONPATH=` — it is not a typo. It
clears the variable for this command only, so `tests/` resolves to this
repo's own package.

If `pytest` is missing: `pip install pytest`. It is needed only for the tests,
never at runtime.

**A red suite here means stop and report.** Do not proceed to launch agents on
someone's machine with a failing suite.

### Phase 3 — the studio

Recommended on macOS — install it once as an always-on user service:

```sh
python3 -m nxb studio install
```

It starts at login, launchd restarts it after a crash, and the process no
longer occupies a terminal. The existing Studio token, drafts, and rigs are
preserved. Check or manage it with:

```sh
python3 -m nxb studio status
python3 -m nxb studio restart
python3 -m nxb studio uninstall   # preserves token, drafts, ledger, and logs
```

The foreground form remains useful for development or non-macOS hosts:

```sh
python3 -m nxb studio
```

It prints a URL carrying a token and opens a browser. Everything below can
also be done from the command line; the studio is the visual way.

**It is served from 127.0.0.1 and guarded**, because it launches agents with
permission prompts disabled: loopback bind only, a token required on every
request including the page load, a loopback-only `Host` check against DNS
rebinding, and constant-time comparison. **Never bind it to a network
interface.** The token persists in `~/.nxb/studio.token` (mode 600) so the
page can be pinned as an app; `--fresh-token` rotates it.

To make it a real app: open the URL in Safari → **File → Add to Dock**. On
Chrome or Brave, `python3 -m nxb studio --app` gives a chromeless window.

Studio drafts are durable files under `~/.nxb/studio-drafts/`, not private
browser state. The same NXB MCP server exposes catalog, validate, save, list,
get, and recoverable-delete tools, so **any MCP-speaking LLM can put a complete
workflow on the canvas in one tool call**. An open Studio imports those changes
within five seconds. Draft tools never launch agents; **Bring it to life stays
the operator's gate**.

### Phase 4 — **ASK** before the first fleet

Standing up a fleet launches real agent sessions that consume the operator's
plan quota. **Ask before doing it**, and ask what shape they want.

Then either compose it on the canvas and press **Bring it to life**, or:

```sh
python3 -m nxb rig up --session demo --orchestrator codex --workers cc:1,cx:1 --dir ~
```

`--workers` is `runtime:count` pairs — `cc` for Claude, `cx` for Codex.
`--orchestrator` takes either runtime, or `none`.

**Check it, and check it properly:**

```sh
python3 -m nxb rig workers --session demo    # every worker enrolled=true?
tmux attach -t demo                          # look at the panes
```

`READY` is a statement about the **rig** — that every pane booted, was named
and was enrolled. It says nothing about whether the agent inside can reach its
model. **Read the panes.** A rig came up READY here once while a worker sat on
a 400 for an unsupported model.

### Phase 4b — check the assumptions hold

```sh
python3 -m nxb doctor
```

Run this now, and again after any runtime update. nxb reads screens, parses
prose and passes flags, and a CLI release can void any of that silently.
`DRIFT` means an assumption no longer holds and a human should look at what
the runtime does now. `--deep` also boots each runtime to verify its readiness
marker and costs one Claude turn.

### Phase 5 — hand it work

Talk to the orchestrator pane in plain language:

> Ask CC Worker 1 and CX Worker 1 how many files are in ~/Documents, then tell
> me whether they agree.

It knows how to do the rest: it was given a brief at launch telling it how to
list its fleet, mint task ids, dispatch and collect. Underneath, each dispatch
is three commands you can also run yourself:

```sh
python3 -m nxb mint    --worker "demo CC Worker 1"
python3 -m nxb rig send --worker "demo CC Worker 1" --task-id <id> --message "..."
python3 -m nxb rig collect --worker "demo CC Worker 1" --task-id <id>
```

### Phase 6 — shut down

```sh
python3 -m nxb rig down --session demo
python3 -m nxb revoke --all      # optional: invalidate outstanding task ids
```

---

## HOW IT WORKS, IN FOUR IDEAS

**1. The operator owns the roster.** A worker is a pane the operator created
and named. Nothing else can add to that list. Ask for a worker that does not
exist and the broker **refuses** and tells you how to create one — it will
never quietly spawn a substitute. That refusal is the product, not an error
path.

**2. A task id is a permission slip.** Minting one runs the roster check, and
the id names exactly one worker. The worker validates its own id before acting
and refuses an id minted for somebody else. Names carry their rig
(`demo CC Worker 1`), so two fleets can hold a "CC Worker 1" and no slip can
reach the wrong one.

**3. Typing is the transport, for both runtimes.** nxb does not use Claude's
socket or `codex queue`. It types the directive into the pane, identically for
both, so the vendor asymmetry leaves the system instead of being patched
forever. Automated input carries a marker; **unmarked input is the operator
talking** and is treated normally, which is how you keep typing to your own
panes.

**4. Honest by construction.** `WAITING` is not an answer. A worker still
working and a worker that refused look identical from outside, so `collect`
returns the pane and says it does not know, rather than guessing. Where a
number cannot be obtained it is reported absent with the reason, never as
zero.

## WHAT IT DOES NOT DO

- **It does not dispatch work from the studio.** By design: the studio
  architects fleets, tmux is where work happens, and the human gate stays in
  front of the panes.
- **It is not a security boundary.** The worker-side check is a model
  following its own rule. It removes drift, not attack. Anything on the
  machine that can type is the operator as far as this is concerned.
- **Agents run with permission prompts disabled**, because that is what makes
  a watched fleet usable. Understand that before standing one up.

## LAYOUT

| path | what |
|---|---|
| `nxb/` | the broker: rig, roster, task ids, typing transport, studio server |
| `tests/` | 400+ tests; more test code than product code |
| `contract/` | the published contract, with tests asserting the code matches |
| `docs/OPERATOR-NOTE-nxb.md` | the human guide; **read this next** |
| `HANDOFF.md` | ~90 sections of hard-won findings. A later section sometimes corrects an earlier one from hundreds of lines away, so search for a topic's other mentions before acting on any one of them |
| `FINDINGS.json` | every defect found, with an owner and what would close it |
| `ledger/LEDGER.md` | task history |

State lives outside the repo, in `~/.nxb/`: the ledger, Studio drafts, rig
records, launch briefs, saved personas and the usage cache.
