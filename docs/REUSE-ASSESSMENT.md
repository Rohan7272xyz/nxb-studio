# Reuse Assessment: how much of the existing NEXUS is transport-independent

Task: nxb-004. Author: Worker 3. Date: 2026-08-28. Method: read-only, plus a
test run on a scratchpad copy (never on second-host, see section 5).
Subject: `/home/operator/nexus` on `second-host`.

Nothing on second-host was modified, started or stopped. The adapter was not run.
No secret material was opened. Claims are labeled OBSERVED (a command was run
and its output read) or INFERRED.

## Headline, including a correction to my own nxb-003 claim

In nxb-003 I wrote "layers 1 through 9 of its pipeline are transport-independent."
**That claim was measured this task and it is too generous. I was counting one
transport when there are three.**

| Transport | Where it lives | Layers coupled to it |
|---|---|---|
| A. Orchestrator ingress and egress: browser DOM | `web_adapter.py` | 10 only |
| B. Worker spawn: local process, tmux, `$PATH` | `runner.py`, and a `which()` preflight in `spawn_task` | 5, 6 |
| C. Report return: a filesystem shared with the worker | `runtime.py`, `collector.py`, `waiter.py` | 2, 7, 8 |

My nxb-003 statement is correct about transport A and silent about B and C.
Layers 1 through 4 and 9 are genuinely independent of all three. Layers 5 and 6
are the local-process transport, and for a broker whose entire purpose is
dispatching to *different runtimes*, that is the single most important layer to
replace, not reuse. Layers 2, 7 and 8 assume the worker writes two files to a
path the broker can read, which is a transport assumption nobody in this project
has named yet, including me.

So the honest answer to "is reuse cheaper than a rewrite" is: **yes, but the
reusable part is smaller and differently shaped than I implied.** What survives
a transport swap is the *contract layer*, about 1,700 lines with 155 passing
tests. What does not survive is both the browser transport and the local-process
transport, about 1,600 lines, plus roughly 2,300 lines of operator surface
(dashboard, launcher, CLI) that this project has no use for.

## 1. The pipeline, layer by layer

Numbering follows their own `NEXUS_HANDOFF.md` so a future orchestrator can
cross-reference it.

| # | Layer | Module | Entry point | Side of the boundary |
|---|---|---|---|---|
| 1 | Directive parse, validate, dedup | `parser.py`, `validation.py`, `state.py`, `errors.py` | `parse_directive(text)`, `DirectiveState.check/register` | core |
| 2 | Task runtime, folder and prompt | `runtime.py` | `create_task(directive, tasks_dir)` | core, but assumes transport C |
| 3 | Report contract and validator | `report.py` | `validate_task_report(...)` | core |
| 4 | `agent_prompt.md` template | `runtime._AGENT_PROMPT_TEMPLATE` | rendered by `create_task` | core |
| 5 | Runner, tmux adapter | `runner.py` | `spawn_task(task_dir, adapter=None)` | **transport B** |
| 6 | Runner guardrails | `runner.py` | inside `spawn_task` | **transport B** |
| 7 | Report collector | `collector.py` | `collect_report(task_dir)` | core, but assumes transport C |
| 8 | Waiter | `waiter.py` | `wait_report(task_dir, ...)` | core, but assumes transport C |
| 9 | Compose 1 to 8 | `orchestrator.py` | `execute_directive(directive_file, ...)` | core |
| 10 | Playwright web adapter | `web_adapter.py` | `run_web_adapter(config, ...)` | **transport A** |
| -- | Operator surface | `dashboard.py`, `launcher.py`, `registry.py`, `routing.py`, `cli.py` | `nexus <subcommand>` | out of scope for a broker |

**Where exactly transport ends.** There is a clean answer, and it is better than
I expected: the browser transport does not import the core, it **subprocesses**
it. OBSERVED, `web_adapter.py:382-486`, three call sites and nothing else:

```python
[sys.executable, "-m", "nexus", "execute-directive", directive_file,
 "--tasks-dir", tasks_dir, "--state-db", state_db]          # fan out, no --wait
[sys.executable, "-m", "nexus", "execute-directive", ..., "--wait", ...]  # blocking variant
[sys.executable, "-m", "nexus", "collect-report", task_dir]  # fan in
```

Each returns one JSON object on stdout, or `{ok:false, error_type, error}` on
stderr, and `_run_nexus_json` never raises. **The seam is already a process
boundary with a JSON contract**, not a Python API you would have to prise apart.
That is the most important structural fact in this report and it is the strongest
argument for reuse.

## 2. Per-layer verdict: genuinely independent, or only apparently

The decisive measurement. OBSERVED: I copied the tree to a machine where
Playwright is **not installed** and imported every module.

```
playwright installed here: False
nexus.errors        import OK   playwright_loaded=False
nexus.validation    import OK   playwright_loaded=False
nexus.parser        import OK   playwright_loaded=False
nexus.state         import OK   playwright_loaded=False
nexus.runtime       import OK   playwright_loaded=False
nexus.report        import OK   playwright_loaded=False
nexus.collector     import OK   playwright_loaded=False
nexus.waiter        import OK   playwright_loaded=False
nexus.orchestrator  import OK   playwright_loaded=False
nexus.routing       import OK   playwright_loaded=False
nexus.registry      import OK   playwright_loaded=False
nexus.runner        import OK   playwright_loaded=False
nexus.web_adapter   import OK   playwright_loaded=False
nexus.cli           import OK   playwright_loaded=False
```

Every module, including `web_adapter` and `cli`, imports with no Playwright
present. OBSERVED: there is exactly **one** Playwright import statement in the
entire codebase, `web_adapter.py:841`, inside the body of `run_web_adapter`. Zero
at module scope. The other apparent hits in a naive grep are docstrings and CLI
help text.

Then I ran the core end to end with no transport at all:

```
create_task -> ['agent_prompt.md', 'directive.md', 'logs.txt', 'status.json', 'task.json']
state: CREATED
agent_prompt.md bytes: 4912
```

Layer-by-layer, against the five specific tests you asked for:

| Layer | Imports Playwright | Touches page state | Assumes a DOM | Assumes one orchestrator | Assumes text in, text out | Assumes input and output are the same channel | Verdict |
|---|---|---|---|---|---|---|---|
| 1 parser, validation, state, errors | no | no | no | no | **yes**, parses a text block | no | independent, with a caveat below |
| 2 runtime | no | no | no | **yes**, no orchestrator identity in `task.json` | no | no | independent of A and B, **coupled to C** |
| 3 report | no | no | no | no | **yes**, parses a text block | no | independent, same caveat |
| 4 prompt template | no | no | no | no | yes, it is a text template | no | independent. Zero chat or browser wording |
| 5 runner | no | no | no | no | no | no | **this is transport B** |
| 6 guardrails | no | no | no | no | no | no | **this is transport B** |
| 7 collector | no | no | no | no | no | no | independent of A and B, **coupled to C** |
| 8 waiter | no | no | no | no | no | no | independent of A and B, **coupled to C** |
| 9 orchestrator | no | no | no | no | no | no | independent. 127 lines, pure composition |
| 10 web_adapter | **yes** | **yes** | **yes** | no | **yes** | **yes** | transport A |

Notes on the columns that matter most.

**"Assumes input and output are the same channel."** You were right that this is
the one to watch. It is true in exactly one place, `web_adapter.WebAdapter`,
whose `read_page_text` and `send_response` both hold `self.page`. Nothing below
layer 10 has any opinion about where a result goes. `execute_directive` returns a
dict and does not deliver it anywhere. This is good news: the structural limit I
flagged in nxb-003 is confined to the layer we are replacing anyway.

**"Assumes text in, text out."** Layers 1 and 3 parse directives and reports out
of prose with boundary tags. That is transport-independent in the sense that any
channel can carry text, but it is a *format* inherited from DOM scraping. Over a
real message bus you would send structured objects and most of `parser.py` (227
lines) becomes unnecessary. Counted as reusable below, but flagged: reusing it is
a decision to keep a text-block wire format you no longer need.

**"Assumes one orchestrator."** OBSERVED: `task.json` metadata is `task_id`,
`target_agent`, `action`, `repo_path`, `summary`, `directive_hash`, `state`,
timestamps and paths. There is **no orchestrator, origin or host field anywhere
in the task model**. Multi-orchestrator isolation is achieved entirely by giving
each adapter a separate `--tasks-dir` and `--state-db`. Consequences: no shared
view across orchestrators, no cross-orchestrator dedup, and two orchestrators
that ever share a tasks root can collide on `task_id` and get
`TaskAlreadyExistsError`. This is your Phase 3 in one sentence and it is a real
gap, not a stylistic one.

**Transport B is hardcoded in three separate places that must stay in sync.**
OBSERVED in `validation.py` and `runner.py`:

```python
VALID_TARGET_AGENTS = ("claude_code", "codex")            # validation.py:13
AGENT_COMMANDS = {"claude_code": "claude", "codex": "codex"}   # runner.py:41
AGENT_ARGS = {"claude_code": ["--dangerously-skip-permissions"], "codex": []}  # runner.py:53
```

Adding a runtime means editing three tables in two modules, and there is no test
asserting they agree.

## 3. The one seam they already built, and why it is the right shape but the wrong type

OBSERVED, `runner.py:158`:

```python
class RunnerAdapter:
    name = "abstract"
    def spawn(self, task, agent_command):
        raise NotImplementedError
```

with `TmuxAdapter(RunnerAdapter)` as the only implementation and
`spawn_task(task_dir, *, adapter=None, ...)` accepting an injected one. The test
suite uses a `FakeRunnerAdapter` throughout, so the seam is exercised, not
aspirational.

This is genuinely encouraging and it is also the place I would most warn you
about. The seam's **shape** is right: pluggable per-runtime spawner, adapter
metadata merged verbatim into `task.json`. Its **type** is wrong for this
project, for two reasons.

First, the signature is `spawn(task, agent_command)` where `agent_command` is a
*shell string* built by `resolve_agent_invocation`. A runtime reached over a
socket, an HTTP API, `SendMessage`, or a cloud session has no shell command. The
abstraction is "local terminal multiplexer", not "runtime".

Second, and more concretely, `spawn_task` runs a PATH preflight **above** the
adapter, `runner.py:475-486`:

```python
agent_command = resolve_agent_command(task.metadata["target_agent"])
if which(agent_command) is None:
    raise AgentCommandMissingError(...)
adapter = adapter or TmuxAdapter(...)
runner_meta = adapter.spawn(task, resolve_agent_invocation(...))
```

A `RemoteRuntimeAdapter` would raise `AgentCommandMissingError` before its
`spawn()` was ever called, because the binary is not on the broker's PATH. So the
seam as built cannot accept a non-local runtime without changing the function
that dispatches to it. That is a small change, perhaps ten lines, but it means
"the seam already exists" is not quite true and you should not plan as if it is.

## 4. Seams table: what a new transport must satisfy

This is the artifact to specify against without re-reading the codebase.

| Seam | Contract | Direction | Satisfied by | Changes needed for a bus-based broker |
|---|---|---|---|---|
| **S1 Ingress** | a directive with 5 headers plus a body, reaching the broker | transport to core | today: `extract_all_directives(page_text)` | **replace entirely.** New transport delivers a directive object or block; nothing below cares how |
| **S2 Dispatch** | `execute-directive <file> --tasks-dir X --state-db Y [--tmux-session Z]`, one JSON object on stdout, `{ok:false,error_type,error}` on stderr, never raises | transport to core | `orchestrator.execute_directive` via `cli.cmd_execute_directive` | **reuse as is.** Drop `--tmux-session`, add an origin field |
| **S3 Spawn** | `RunnerAdapter.spawn(task, agent_command) -> dict` merged into `task.json` | core to runtime | `TmuxAdapter` | **generalize.** Signature must lose `agent_command`; move the PATH preflight into the adapter |
| **S4 Report write** | worker writes `final_report.md` plus `status.json` to two absolute paths | runtime to core | `_AGENT_PROMPT_TEMPLATE` | **replace for remote runtimes.** Local workers can keep it |
| **S5 Report read** | `collect-report <task_dir>` returns `{ready, task_id, state, report}` or `{ok:false,...}` | core to transport | `collector.collect_report` | **reuse the shape, replace the source.** It is `os.path.join(task_dir, ...)` today |
| **S6 Egress** | a result block delivered to the dispatcher | core to transport | `format_result_block(result)` plus `send_response` | **split.** `format_result_block` is pure and reusable, `send_response` is Playwright |
| **S7 Dedup** | `task_id` is the primary key; a repeat is rejected | core | `state.DirectiveState`, SQLite | **reuse.** Add an orchestrator column for Phase 3 |
| **S8 Receipt** | *does not exist* | -- | -- | **new.** This is nxb-003's finding: emit at S1 before S2, addressed to the dispatcher's runtime |
| **S9 Liveness** | *does not exist* | -- | `registry.py` is discovery for a dashboard, not a heartbeat | **new** |

S1, S3, S4 and S6 are the transport swap. S2, S5, S7 are reusable as written.
S8 and S9 are what this project is actually for and neither exists in any form.

## 5. The tests: what they actually cover

OBSERVED. I did **not** run anything on second-host. I `rsync`ed a copy of the tree
(excluding `.venv`, `.git`, `__pycache__`) to a scratchpad on the Mac and ran it
there with `PYTHONDONTWRITEBYTECODE=1`, so second-host was untouched and the
original tree gained not even a `.pyc`. I read the suite first to confirm this was
safe: it uses `FakeRunnerAdapter`, a `_FakePage` double, and patched
`shutil.which`, it never shells out to tmux, never binds a port, and the five
Playwright smoke tests skip cleanly on `ImportError`.

```
Ran 366 tests in 0.323s
FAILED (failures=1, errors=1, skipped=5)
```

| Bucket | Modules | Tests | Share |
|---|---|---|---|
| Contract core, survives any transport swap | parser 26, state 7, runtime 8, report 36, collector 21, waiter 19, orchestrator 10 | **127** | 35% |
| Transport A, browser | web_adapter 90, smoke 5 | **95** | 26% |
| Transport B, local process and tmux | runner 40, launcher 10 | **50** | 14% |
| CLI surface, mixed | cli 41 | 41 | 11% |
| Operator surface | dashboard 25 | 25 | 7% |
| Cross-cutting, reusable but not core | routing 18, registry 10 | 28 | 8% |

Then the measurement that matters most for your question. Running **only** the
core modules, importing no transport at all:

```
Ran 155 tests in 0.094s
OK
```

The contract layer is independently testable, passes clean, and takes under a
tenth of a second. That is the reusable asset, and it is real.

Three honest caveats:

- **The two non-passing tests.** `PageFileResolutionTests.test_absolute_page_file_is_taken_as_is`
  fails on macOS only, because `/var` is a symlink to `/private/var` and the test
  compares an unresolved path to a resolved one. It is an artifact of where I ran
  it, not a defect on Linux. `ReadinessWaitTests.test_falls_back_when_content_never_stabilises`
  errors with `StopIteration`: the test hands the poll loop 10,000 fake pane
  captures with `ready_poll=0.0` and a 0.05 second budget, and on fast hardware
  the loop exhausts the iterator before the clock runs out. **That one is a
  genuine latent flake in their suite**, wall-clock dependent, and it will bite
  whoever runs this on newer hardware. Minor, but it is theirs, not mine.
- **`validation.py` has no dedicated test module.** OBSERVED: there is no
  `tests/test_validation.py`. Its 84 lines are covered only indirectly through
  parser tests. It is the module holding `VALID_TARGET_AGENTS`, which is exactly
  what you will edit to add a runtime.
- **"364 tests" in their handoff, 366 methods counted.** Immaterial, noted so the
  next reader does not chase it.

## 6. State DB and task folder layout, and how coupled they are

OBSERVED.

**State DB.** `state.py`, 101 lines, one SQLite table:

```sql
CREATE TABLE processed_directives (
  task_id TEXT PRIMARY KEY, directive_hash TEXT, target_agent TEXT,
  action TEXT, summary TEXT, processed_at REAL)
```

Default `~/.nexus/state.db`, overridable with `--state-db`. **Zero browser
coupling.** Its one design assumption relevant to you is that `task_id` is
globally unique within a database, and isolation between orchestrators is
achieved by handing each one a different database file. There is no origin
column, so a shared database across runtimes would give you dedup but not
provenance.

**Task folder.** `runtime.create_task`, default root `~/.nexus/tasks`, one
directory per `task_id` containing `task.json`, `directive.md`,
`agent_prompt.md`, `status.json`, `logs.txt`, and later `final_report.md`.
Refuses to overwrite an existing `task.json`. **Zero browser coupling**, and the
prompt template contains no chat or browser wording at all: I grepped it, and its
only references to an orchestrator are "the orchestrator will read status.json".

The coupling is not to the browser, it is to the **filesystem as the report
channel**, and it is load-bearing in three layers. `collect_report(task_dir)` is
a pure function of a directory. That makes it beautifully testable and it makes
it wrong for any worker that does not share a filesystem with the broker. If the
bridge is going to dispatch to a Codex cloud session or a machine across the
tailnet, S4 and S5 need a second implementation, and that is not a small edit,
it is a parallel path through layers 2, 7 and 8.

Relevant to your Phase 4, and repeated from nxb-003 because it has not changed:
`~/.nexus` on second-host also holds Android release signing material. OBSERVED,
filenames only: `~/.nexus/secrets/downstream-upload.keystore`,
`~/.nexus/secrets/keystore.properties`. Nothing opened. A broker whose default
tasks root is a sibling of that directory deserves an explicit boundary.

## 7. What they already knew, so we do not rediscover it

From their `NEXUS_HANDOFF.md` "Known red flags / gaps", verbatim in substance:

1. Live ops state drifts from code. The running adapter usually predates the
   newest code and needs a restart to pick up features.
2. Routing loop safety is structural, not absolute. Acyclic topologies cannot
   loop; cyclic ones rely on a per-session message cap and dedup.
3. Real-surface selectors are starter-only (`"_starter_only": true` in
   `claude-ai.json`), and there is no live-DOM CI.
4. Orchestrator composition lives in the chat, not the API. The dashboard mirrors
   worker data but the orchestrator's reasoning is only in its browser tab. They
   name this as a deliberate choice to stay on the Max plan rather than the API.
5. State-machine transitions past `REPORT_READY` (`REPORT_SENT_TO_WEB`,
   `WAITING_FOR_NEXT_DIRECTIVE`, `DECOMMISSIONED`) are **reserved, not written by
   code**. Decommission tears down a tmux session rather than marking tasks.
6. No transactionality between the state DB and the filesystem. No daemon mode
   beyond the adapter loop.

Their `CLAUDE.md` adds three rules they call load-bearing: NEXUS owns the task
state machine and agents only ever write `status.json` and `final_report.md`;
every CLI error is `{ok, error_type, error}` with a stable vocabulary; and
`_AGENT_PROMPT_TEMPLATE` and the `report.py` validators are tied together with a
test that pipes the generated prompt through the real validator.

Two of these are worth carrying into the bridge as they stand. Rule 1 is the
reason their report contract is trustworthy: the worker cannot mark its own task
complete, it can only claim, and the collector adjudicates. Rule 3 is a pattern
worth stealing outright: **a test that generates the prompt and validates it with
the production validator** is the cheapest possible guard against contract drift,
and it is exactly the class of check that would have caught the protocol-document
drift that caused nxb-003.

Item 4 deserves emphasis. Their gap list already says the orchestrator lives in a
browser chat by choice. That choice is the root of the failure I autopsied, it is
documented as a tradeoff rather than a defect, and it is the assumption this
project exists to remove.

## 8. Recommendation, argued both ways

### The strongest case for a rewrite

I want to make this properly, because I am the person who said "reuse" first and
that is a bias, not an analysis.

1. **You would be inheriting the format that the failure was made of.** A
   directive is five headers and a body parsed out of prose with boundary tags
   because it had to survive being scraped off a web page. Over a message bus you
   send an object. Reusing layer 1 means keeping 227 lines of `parser.py`, plus a
   greedy tag-pairing routine with its own vanish points (nxb-003 items 5 and 6),
   to solve a problem the new transport does not have.
2. **The core's most load-bearing assumption is the wrong one for this project.**
   Layers 2, 7 and 8 assume the worker and the broker share a filesystem. Your
   stated goal is dispatching across runtimes, which is precisely the case where
   they do not. So the thing I called reusable is coupled to a transport in its
   middle, not at its edge.
3. **You would inherit a half-finished state machine.** `action: continue` and
   `decommission` validate but do nothing. Three `TaskState` values are reserved
   and never written. Their own gap list says so. Half-implemented enums in a
   contract are worse than absent ones because they read as capabilities.
4. **Comprehension tax on stateless workers.** 1,700 lines of someone else's code
   with docstrings asserting invariants ("load-bearing, do not break") is
   expensive for a team where each worker gets one directive and no memory. A
   500-line purpose-built core that a worker can read in full in one directive
   may be cheaper in worker-hours than a 1,700-line inheritance nobody holds
   entirely in context.
5. **Sunk cost, named.** I read this code yesterday, rated it competent, and said
   so to you. Rating it again today is not independent. Weight this report
   accordingly.

### The case for reuse

1. **The seam is already a process boundary with a JSON contract.** OBSERVED, not
   inferred: transport A never imports the core, it subprocesses
   `python -m nexus execute-directive` and `collect-report` and parses stdout.
   You can write a new transport that shells out to exactly those two commands
   and have a working end-to-end path today, without touching a line of the core.
   That is not a refactor, it is a substitution.
2. **The core is measurably independent and measurably tested.** 155 tests, all
   passing, 0.094 seconds, with no transport module imported and Playwright not
   installed. Very few "reusable core" claims survive that test. This one did.
3. **The expensive asset is not the code, it is the contract.** The report schema,
   the `error_type` vocabulary, the rule that agents may not set their own task
   state, and a test that validates the generated prompt with the production
   validator are the product of real use across many tasks. Rewriting produces
   new code and the *same* contract, at best.
4. **`RunnerAdapter` plus `FakeRunnerAdapter` means the spawn seam is exercised,
   not aspirational.** The generalization it needs is roughly ten lines plus a
   signature change.
5. **Reuse gets you to disagreement sooner**, which is the property you said the
   project exists for. A rewrite spends its first weeks reproducing a report
   contract instead of getting an Opus orchestrator and a GPT worker to disagree.

### What I would do

**Reuse the contract layer, replace both transports, and take none of the
operator surface.** Concretely:

- **Take as is**, roughly 1,050 lines with 127 tests: `errors.py`, `report.py`,
  `state.py`, `collector.py`, `waiter.py`, `orchestrator.py`, plus
  `runtime.py`'s task layout and prompt template. Plus about 120 pure lines
  lifted out of `web_adapter.py` (`extract_all_directives`, `directive_hash`,
  `format_result_block`, `DirectiveDedup`, lines 50 to 171) which have no
  Playwright in them at all.
- **Take as a specification, reimplement the wire format**: `parser.py` and
  `validation.py`. Keep the field set, the `task_id` safety regex and the error
  types. Do not keep tag-scraping if your transport delivers structured messages.
- **Generalize**: `runner.py`'s `RunnerAdapter`, with `agent_command` removed
  from the signature and the PATH preflight pushed down into the local adapter.
- **Do not take**: `web_adapter.py` transport half, `dashboard.py`,
  `launcher.py`, `cli.py`, roughly 2,900 lines. `registry.py` and `routing.py`
  are interesting prior art for Phase 3 and the message bus but are built for a
  browser-per-orchestrator world; read them, do not import them.
- **Build new**: S8 receipt and S9 liveness. Neither exists in any form and they
  are the project.

If forced to a binary I choose **reuse**, and the reason is item 2 of the reuse
case: I set out to measure a claim I had made and it survived a test designed to
break it. A rewrite would spend its first phase reconstructing a contract that
already passes 127 tests in a tenth of a second, and it would do so while the
actual novel work, the receipt and the heartbeat, waits.

But I want the size of the claim to be right this time: **reuse is worth roughly
1,050 lines and 127 tests, not "layers 1 through 9".**

## UNVERIFIED

- I ran the suite on a **copy on the Mac** under Python 3.14, not on second-host
  under its own Python 3.12 venv. Their pass count on their machine is unmeasured
  by me. The macOS path failure is environment-specific and would not occur there;
  the readiness flake is timing-dependent and might not reproduce on that
  hardware.
- I did not execute `spawn_task` against real tmux, `run_web_adapter` against a
  real browser, or any end-to-end dispatch. Every claim about transport behaviour
  is read from source, plus the fake-driven tests.
- Effort figures ("roughly ten lines", "1,050 lines") are counts of what exists
  plus my judgement of what changes. They are estimates, not measurements.
- I did not review `dashboard.py` (970 lines) or `cli.py` (1,082 lines) closely,
  only their imports, subcommand structure and lazy-import behaviour. My
  recommendation to discard them is based on scope, not on a defect review.
- I did not check whether the git history of `~/nexus` contains anything relevant.
  It is not a git repository under a path I examined; I did not look for one.

## Where I think you may still be framing this wrongly

**"Transport" is doing too much work as a word, and it hid two of the three from
both of us.** I gave you a one-transport model in nxb-003 and you built a task
around it. The system has an ingress transport, a spawn transport and a report
transport, and they fail differently: ingress failed silently because nobody was
listening, spawn would have failed loudly at tmux, and report would have failed
by polling a directory forever. An ack designed for one of these does not cover
the other two. I would name all three in the spec and require a receipt at each,
rather than "the ack".

**The reuse question may be less decisive than it feels.** Both answers converge
on the same first deliverable. Reuse means writing a new S1 and S6 against
`execute-directive` and `collect-report`; rewrite means writing S1 and S6 against
something you define. Either way the next thing built is a transport with a
receipt, and the core question can be deferred until after it works once. If
nxb-001 and nxb-002 come back saying the two runtimes want different spawn
mechanics, that will settle the runner question with evidence rather than
judgement. I would not spend an orchestrator turn deciding reuse-versus-rewrite
before those land.

**The most reusable thing in that repository is not code.** It is `CLAUDE.md` rule
3: a test that renders the production prompt template and validates it with the
production validator, so the two cannot drift. That pattern, generalized, is the
answer to the deeper defect in nxb-003, where a document was the only source of
truth for a capability. A broker that publishes a contract should have a test that
takes its own published contract and runs it through its own validator. That is
one test, it is cheap, and it is the structural fix for the class of failure that
started this project.
