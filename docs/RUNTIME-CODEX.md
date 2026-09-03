# Runtime probe: Codex

Task: nxb-002. Author: Worker 2. Date: 2026-08-28. Host: this Mac (`/Users/rohan`).

Every claim is labeled OBSERVED (I ran a command and read its output),
INFERRED (reasoned from observations), or UNVERIFIED (could not measure).
Documentation is cited only where I say so, and never presented as observation.

Probes ran in `/private/tmp/claude-501/.../scratchpad/codex-probe`.
Nothing in `~/downstream-project`, `main`, production or App Store Connect was touched.

**Version under test: `codex-cli 0.150.1`.** Everything below is version-specific.
Re-run the probes before trusting this against a different build.

---

## Summary for a future orchestrator

Codex is **usable right now**. The note "Codex down" is stale; see Q0.

Three things matter more than the rest:

1. **`codex exec` hangs silently if you leave stdin open.** This is the single
   biggest spawn hazard. Always redirect stdin from `/dev/null`. See Q2.
2. **`codex queue` exit 0 does NOT mean delivered.** It is a write to a local
   SQLite table with no liveness check and no reply path. It is a false green
   in exactly the sense HANDOFF rule 8 warns about. See Q3.
3. **The real bidirectional path is MCP**, not `queue`. `codex mcp-server`
   exposes `codex` and `codex-reply`, both returning `{threadId, content}`
   synchronously. It works, and it is marked deprecated. See Q3 and Q6.

---

## Q0. Is it installed and usable?

**Answer: yes, fully. The "Codex down" note is not true of this host today.**

OBSERVED:

```
$ which codex
/Users/rohan/.local/share/mise/installs/node/lts/bin/codex
$ codex --version
codex-cli 0.150.1
```

`codex doctor` returns **22 ok, 1 idle, 0 warn, 0 fail**. Selected rows:

```
  auth      auth is configured        stored auth mode  chatgpt   stored API key false
  websocket connected (HTTP 101 Switching Protocols) · 15s timeout
  reachability active provider endpoints are reachable over HTTP
  config    loaded                    model  gpt-5.6-sol · openai
  state     databases healthy         active rollouts 263 files · 856.69 MB
  sandbox   restricted fs + restricted network · approval OnRequest
```

The one non-ok row is idle, not failed: `app-server not running (ephemeral mode)`.
That matters for Q4 and is covered there.

Auth is ChatGPT OAuth (`~/.codex/auth.json`, `auth_mode: chatgpt`, no API key).
INFERRED: usage bills against Rohan's ChatGPT plan, not an API key, so there is
no per-call cost meter a broker can read, and plan rate limits apply. The error
taxonomy includes `usageLimitExceeded`, so a broker must expect plan-limit
failures that an API-key runtime would not produce.

A live end-to-end turn confirms the model actually answers. OBSERVED:

```
$ codex exec --json --skip-git-repo-check -s read-only \
    -c model_reasoning_effort="low" -o lastA.txt \
    "Reply with exactly the word PONG and nothing else." < /dev/null
{"type":"thread.started","thread_id":"01a048f1-1448-7183-a360-8733cbc20dca"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"PONG"}}
{"type":"turn.completed","usage":{"input_tokens":15042,"cached_input_tokens":9984,
 "cache_write_input_tokens":0,"output_tokens":6,"reasoning_output_tokens":0}}
EXIT=0 SECS=5
```

**Model identity is not what the config says, and this matters to this project.**
OBSERVED: `~/.codex/config.toml` sets `model = "gpt-5.6-sol"`, but every thread
my probes created recorded `model = gpt-5.6-luna` in `~/.codex/state_5.sqlite`.
In the last two hours the `threads` table holds both: `gpt-5.6-luna` 6 rows,
`gpt-5.6-sol` 3 rows. UNVERIFIED: why they differ (alias resolution, routing,
or an A/B). **Consequence: the disagreement thesis depends on knowing which
model answered. Pin `-m` explicitly on every spawn and record the value the
thread actually recorded, not the one you asked for.**

Baseline defaults, OBSERVED from config: `model_reasoning_effort = "max"`,
`approvals_reviewer = "user"`, `/Users/rohan` is `trust_level = "trusted"`.
Note that `max` is stored as `xhigh` on the thread row.

Confidence: high.

---

## Q1. Spawn

**Answer: `codex exec` is the non-interactive entry point. It is blocking,
streams JSONL to stdout with `--json`, and returns a meaningful exit code.**

Minimum viable spawn, OBSERVED to work:

```
codex exec --json --skip-git-repo-check -s <mode> \
  -C <workdir> -m <model> -o <last-message-file> "<prompt>" < /dev/null
```

Flags that matter, OBSERVED from `codex exec --help` and confirmed in use:

| Flag | Effect |
|---|---|
| `--json` | JSONL event stream on stdout |
| `-o, --output-last-message <FILE>` | final agent message written to a file |
| `--output-schema <FILE>` | JSON Schema constraining the final response |
| `-s, --sandbox <MODE>` | `read-only`, `workspace-write`, `danger-full-access` |
| `-C, --cd <DIR>` | working root |
| `--add-dir <DIR>` | extra writable roots |
| `--skip-git-repo-check` | required outside a git repo |
| `--ephemeral` | do not persist session files |
| `-c key=value` | override any config.toml key |

**Exit codes, OBSERVED:**

- `0` turn completed
- `1` turn failed (model/provider error), and also a `queue` target that does not resolve
- `2` CLI usage error (bad flag), before anything is spawned

**Flag surfaces are inconsistent between subcommands. This is a real trap.**
OBSERVED:

- `codex exec` **rejects** `-a/--ask-for-approval`, which top-level `codex` accepts:
  `error: unexpected argument '-a' found`, exit 2.
- `codex exec resume` **rejects** `-s/--sandbox`, which `codex exec` accepts:
  `error: unexpected argument '-s' found`, exit 2. Use `-c sandbox_mode=...` there.

A broker must not assume a flag valid on one subcommand is valid on another.

**What a failed spawn looks like to the caller.** OBSERVED, invalid model:

```
$ codex exec --json ... -m "definitely-not-a-real-model-xyz" -o lastF.txt "hi" < /dev/null
{"type":"thread.started","thread_id":"01a048f9-3fb4-7c81-a79f-3d9b46a3c02c"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for
 `definitely-not-a-real-model-xyz` not found. Defaulting to fallback metadata; ..."}}
{"type":"turn.started"}
{"type":"error","message":"{\"type\":\"error\",\"status\":400,\"error\":{\"type\":
 \"invalid_request_error\",\"message\":\"The '...' model is not supported when using
 Codex with a ChatGPT account.\"}}"}
{"type":"turn.failed","error":{"message":"..."}}
EXIT=1
```

Two things to note, both OBSERVED:

- **`thread.started` is still emitted on a run that fails.** It is an ack of
  "process launched, thread created", not of "work will succeed".
- **The `-o` file is NOT created on failure.** Absence of the output file is a
  reliable failure signal; an empty file is not the same thing.

Confidence: high.

---

## Q2. Ack, and the silent-start failure

**Answer: the ack is the `thread.started` JSONL event, and it is a good one.
It is the first line on stdout, arrives before any model work, and carries the
thread id you will need for everything else.**

```json
{"type":"thread.started","thread_id":"01a048f1-1448-7183-a360-8733cbc20dca"}
```

A caller that reads stdout line by line and waits for `thread.started` with a
timeout has a genuine started/not-started signal. Recommended rule: **if
`thread.started` has not arrived within N seconds, the spawn did not take.**

### The failure mode this project must design against

**`codex exec` blocks on stdin if the caller leaves stdin open, and produces
nothing at all.** This is the "launched but never began" case, and it is silent.

OBSERVED, stdin held open by a live pipe:

```
$ sleep 200 | codex exec --json --skip-git-repo-check -s read-only \
    -c model_reasoning_effort="low" -o lastB.txt "Reply with exactly PONG..." > B.jsonl 2> B.err
```

After 70+ seconds: `B.jsonl` is **0 bytes**, `lastB.txt` does not exist, and
`ps` confirms the process is still alive:

```
LIVE: 64842 .../bin/codex exec
LIVE: 64839 sleep 200
```

stderr contains only `Reading additional input from stdin...`. No error, no
event, no exit. A caller waiting on process exit waits forever. A caller
waiting on `thread.started` waits forever. Nothing distinguishes this from a
slow model except a timeout.

OBSERVED, a second and different bad outcome with a FIFO holding stdin open:
the turn **did** run to completion and `lastH.txt` contained `PONG`, but the
process **still had not exited after 75 seconds**. So the same root cause
produces two distinct symptoms: never-starts, and completes-but-never-exits.

INFERRED, from `codex exec --help`: this is by design. The help says
"If stdin is piped and a prompt is also provided, stdin is appended as a
`<stdin>` block". Codex waits for EOF that a careless spawner never sends.

**Rule for the broker: every Codex spawn must redirect stdin from `/dev/null`.**
OBSERVED: with `< /dev/null` the identical command exits 0 in 5 seconds.

Note that `Reading additional input from stdin...` is printed to stderr in the
healthy case too, so it is **not** a diagnostic of the hang. Do not key on it.

**This does not explain the 7-of-7 failure on 2026-08-27.** Worker 3's
`docs/ADAPTER-AUTOPSY.md` establishes that the adapter drove a browser DOM and
never had a path to a terminal at all, and was not running. My finding is an
independent trap that would bite Phase 1 if the broker shells out naively.
I am flagging it as new, not as the root cause.

**Detecting launched-but-never-began, recommended:** require `thread.started`
on stdout within a timeout; treat its absence as a failed spawn and kill the
child. Do not use process liveness, and do not use the `-o` file, since in the
FIFO case the file was written while the process still hung.

Confidence: high on the `/dev/null` fix and on the never-starts case. Medium on
why the FIFO case diverged from the pipe case; I measured both but did not
isolate the mechanism.

---

## Q3. Messaging a running agent

This is the question the web search got wrong, so it is worth being precise.

### `codex queue` exists, and it is fire-and-forget

**The surface is real.** OBSERVED: `codex queue --thread <THREAD> --message <TEXT>`,
where `--thread` takes a "Session UUID or exact session name".

**But exit 0 does not mean delivered.** OBSERVED, queueing to a thread whose
process exited minutes earlier:

```
$ codex queue --thread 01a048f1-1448-7183-a360-8733cbc20dca --message "PROBE: are you there?"
Queued message 01a048f3-37f7-7210-8761-593abbcc901e for thread 01a048f1-....
QUEUE_EXIT=0
```

The message went into `~/.codex/queue_1.sqlite`, table `queued_items`, and sat
there. OBSERVED:

```
id                                    thread_id                             payload
01a048f3-37f7-7210-8761-593abbcc901e  01a048f1-1448-7183-a360-8733cbc20dca  {"UserInput":{"content":[
                                                                            {"type":"text","text":
                                                                            "PROBE: are you there?"...
```

**What it does validate:** that a rollout exists on disk. OBSERVED:

```
$ codex queue --thread 00000000-0000-0000-0000-000000000000 --message "..."
Error: failed to queue session message: thread/queue/add failed: failed to read thread:
 invalid thread-store request: no rollout found for thread id 00000000-... (code -32603)
EXIT=1

$ codex queue --thread nxb-002-no-such-session-xyz --message "..."
Error: No active session found matching 'nxb-002-no-such-session-xyz'.
EXIT=1
```

Note the asymmetry, OBSERVED: a **UUID** resolves against the on-disk rollout
store, so it succeeds for dead threads. A **name** resolves against active
sessions. So `queue` by name at least implies a live session; `queue` by UUID
implies nothing about liveness.

### It does not reach a session mid-task

OBSERVED. I started a `codex exec` turn whose first step was `sleep 60`, read
its `thread_id` from `thread.started`, and queued a message while the turn was
demonstrably still running (the agent had already emitted "Starting the
requested 60-second command now").

```
TID=01a048f8-0dfe-7420-b10d-422fa57dd16a
INJECT_AT=11:23:31
Queued message 01a048f8-0f60-7d32-80ee-0d08e1de0f76 for thread 01a048f8-....
QUEUE_EXIT=0
```

The running turn never saw it. The row was **still in `queued_items`**
afterwards, undelivered. The agent's messages were only
`Starting the requested 60-second command now.` and
`The command is still running; waiting for it to finish.`

**Conclusion: `codex queue` is store-and-forward for a LATER turn, not
mid-task delivery, and it has no reply path whatsoever.** The caller gets a
message id, not a response.

### The real bidirectional path is MCP

**This works, and it is the thing to build on.** OBSERVED, driving
`codex mcp-server` over stdio with hand-written JSON-RPC:

```
tools/call codex      -> {"threadId":"01a048f7-5ff4-7a93-a469-a8b38add7a08","content":"READY"}
tools/call codex-reply-> {"threadId":"01a048f7-5ff4-7a93-a469-a8b38add7a08","content":"ZEBRA-41"}
```

The first call spawned a session with the prompt "Remember this secret token:
ZEBRA-41. Reply with exactly the word READY." The second call passed only
`threadId` and "What was the secret token?". It answered `ZEBRA-41`.

That proves three things at once: a message reaches an existing session, the
session's context survived, and **the reply comes back synchronously in the
`tools/call` result**. Same `threadId` across both calls.

**Caveat, and it is important: this is not mid-turn steering.** `codex-reply`
starts a NEW turn on an idle thread. I did not test `codex-reply` against a
thread with a turn in flight. UNVERIFIED: what happens if you do. The binary
contains an error string `activeTurnNotSteerable`, which INFERRED suggests the
attempt is rejected rather than queued, but I did not trigger it.

### The `@` mention claim

**Not supported as described.** The claim was "`@` mentions to reference other
Codex tasks".

OBSERVED, from strings in the binary: `UserInput::Mention` is a serde variant
carrying 2 elements alongside `byte_range` and `placeholder`, sitting in the
same enum as `Text`, `Image`, `LocalImage`, `Audio`, `Skill`. INFERRED: mentions
are **inline text annotations** over a span of the user's message, the same
shape used for file, app and skill references, not a task addressing mechanism.
There is a `mentions_v2` feature flag and a `codex_app_mentioned` analytics event.

There is also a source path string `tui/src/task_mentions.rs`, so something
called task mentions plausibly exists **in the TUI**. UNVERIFIED: its semantics.
Either way it is a TUI input affordance. `codex exec` and `codex queue` expose
no mention parameter, so **a broker cannot use it**, whatever it does.

Verdict on the hypothesis: `codex queue` is REAL but much weaker than it sounds.
`@` mentions for referencing other tasks are NOT confirmed and are not
reachable from a non-interactive caller. Reporting the search result as
unreliable was the right instinct.

Confidence: high on queue semantics and on the MCP round trip. Medium on the
mention interpretation, which rests on strings plus docs, not on a driven test.

---

## Q4. Identity

**Answer: the UUID is the only stable address. Names drift and must not be used.**

OBSERVED. Thread ids are UUIDv7-shaped, e.g.
`01a048f1-1448-7183-a360-8733cbc20dca`, minted at `thread.started` and stable
for the life of the thread. The same id appeared in `thread.started`, in
`~/.codex/state_5.sqlite`, in `queued_items.thread_id`, and as `threadId` in the
MCP result. **One id space across all the surfaces.** That is good news.

**Names are auto-generated from content and are rewritten as the session runs.**
OBSERVED in `~/.codex/session_index.jsonl`, 4 of 8 sampled ids carry more than
one name over time:

```
01a048e0-5e20-7863-add8-61871e7dbbd5
   NAME: <NEXUS_DIRECTIVE> { "task_id": "nexu
   NAME: Verify HEAD reflog artifact origin
01a03b50-32b7-7f21-87d8-0a25a9d4561e
   NAME: did you finish this task i believe y
   NAME: Resume iOS test foundation
```

Since `codex queue --thread` accepts "exact session name", **addressing by name
is a live hazard**: the name you captured at spawn may no longer match, and
worse, could in principle match a different session later. Address by UUID.

The `threads` table does carry `name`, `agent_nickname` and `agent_role`
columns, so a settable identity may exist through some surface.
UNVERIFIED: whether a caller can set them at spawn time. No `codex exec` flag does.

**Stability across restarts:** rollouts persist on disk (263 active rollout
files, 856 MB) and `codex exec resume <uuid>` resolves a dead thread's UUID, so
ids survive process death. OBSERVED indirectly: `codex queue` succeeded against
a thread whose process had exited, which requires the id to still resolve.

**`codex agents` is not usable by a broker.** OBSERVED:

```
$ codex agents < /dev/null
ERROR: stdin is not a terminal
```

It is a TUI browser over the shared app-server daemon, and that daemon is not
running on this host. OBSERVED: `codex app-server daemon version` returns
`failed to connect to /Users/rohan/.codex/app-server-control/app-server-control.sock:
No such file or directory`, and doctor reports `app-server not running (ephemeral mode)`.

**I did not start the daemon.** Starting a shared, persistent, machine-wide
daemon while Rohan has live Codex sessions and a release in review is a state
change I am not willing to make unilaterally. `codex app-server daemon start`
and `codex remote-control start` exist and are the obvious next probe. That is
a decision for Rohan, and it belongs with the Phase 4 permission work.

Confidence: high on UUID stability and name drift. The daemon path is UNVERIFIED
by choice, not by obstacle.

---

## Q5. Structured output

**Answer: `--output-schema` plus `-o`. It works and it is the best path.**

OBSERVED. Schema file:

```json
{"type":"object","properties":{
  "verdict":{"type":"string","enum":["PASS","FAIL"]},
  "confidence":{"type":"number"},
  "notes":{"type":"string"}},
 "required":["verdict","confidence","notes"],"additionalProperties":false}
```

```
$ codex exec --json ... --output-schema schema.json -o lastSC.txt \
    "Is 2+2 equal to 4? Give your verdict." < /dev/null
$ cat lastSC.txt
{"verdict":"PASS","confidence":1.0,"notes":"2 + 2 = 4."}
EXIT=0
```

Clean, conforming JSON. This is how the broker should demand a worker report.

The JSONL stream is separately parseable and well structured. Event types
OBSERVED: `thread.started`, `turn.started`, `item.started`, `item.completed`,
`turn.completed`, `turn.failed`, `error`. Item types OBSERVED:
`agent_message`, `command_execution`, `error`. A `command_execution` item
carries `command`, `aggregated_output`, `exit_code`, `status`. `turn.completed`
carries a full `usage` block.

### What failure and refusal look like

- **Model/provider failure:** `turn.failed` with `error.message`, plus a
  top-level `{"type":"error"}`, exit 1, and no `-o` file. OBSERVED, see Q1.
- **Interruption:** UNVERIFIED. I did not send SIGINT to a live turn. The
  binary contains `RecoverTurn`, `SuspendTurnAndShutdown` and `abortReason`,
  so a distinct shape likely exists, but I did not measure it.
- **A refused approval / sandbox denial is INVISIBLE in the event stream.**
  This is the finding that matters here, and it is bad news for a broker.

OBSERVED. Under `-s read-only` I asked the agent to write a file. The write was
genuinely blocked and the file was unchanged, but the **entire** JSONL stream was:

```
thread.started
turn.started
item.started    item_0  command_execution  cmd = "/bin/zsh -lc 'cat .../sbx/target.txt'"
item.completed  item_0  command_execution  exit 0
item.completed  item_1  agent_message
turn.completed
```

`grep -c TAMPERED S.jsonl` returns **0**. The denied write never appears as an
event at all. The only trace of the denial is inside the agent's prose:

```
WRITE_BLOCKED
`zsh:1: operation not permitted: /private/tmp/.../sbx/target.txt`
```

**Consequence: a broker cannot detect "this worker was blocked by its sandbox"
by parsing the stream. It would have to read the prose, which is exactly the
kind of inference that produces false greens.** If the broker needs to know
whether work was refused, the directive must require the worker to report it in
a schema-constrained field, and the broker must verify the intended effect
independently rather than trusting a clean event stream.

Confidence: high. I verified the absence three ways: grep, a full event dump,
and the unchanged file on disk.

---

## Q6. MCP

**Answer: both directions work. Codex consumes MCP servers, and Codex can act
as an MCP server another process drives. The server side is deprecated.**

### Codex as an MCP server

OBSERVED, `codex mcp-server` over stdio:

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",
 "capabilities":{"tools":{"listChanged":true}},
 "serverInfo":{"name":"codex-mcp-server","title":"Codex","version":"0.150.1"}}}
```

Two tools, OBSERVED from `tools/list`:

| Tool | Purpose | Key inputs | Output schema |
|---|---|---|---|
| `codex` | start a session | `prompt` (required), `model`, `sandbox`, `approval-policy`, `cwd`, `config`, `base-instructions`, `developer-instructions` | `{threadId, content}` |
| `codex-reply` | continue a session | `prompt` (required), `threadId` | `{threadId, content}` |

`sandbox` accepts `read-only | workspace-write | danger-full-access`.
`approval-policy` accepts `on-request | never`. `config` is a free-form object
that overrides `config.toml`. This is a richer spawn surface than `codex exec`
exposes as flags, and it returns a thread id and the reply in one call.

**It prints a deprecation warning on every start.** OBSERVED on stderr:

```
warning: `codex mcp-server` is deprecated and will be removed in a future release.
```

INFERRED: the successor is `codex app-server` (`--listen stdio:// | unix:// | ws://`),
which the ChatGPT desktop app already drives. OBSERVED: a running
`/Applications/ChatGPT.app/Contents/Resources/codex app-server --listen stdio://`
process. `codex app-server generate-json-schema` and `generate-ts` exist to
generate the protocol bindings. **Recommendation: build against `app-server`,
not `mcp-server`, and treat `mcp-server` as a working reference implementation
that will be removed.**

### Codex as an MCP client

OBSERVED: `~/.codex/config.toml` configures `[mcp_servers.node_repl]` and
`[mcp_servers.computer-use]`; doctor reports `2 server (2 stdio) · 1 disabled`.
`codex mcp` manages external MCP servers. Servers can be injected per-invocation
with `-c mcp_servers.<name>={...}`, which the desktop app does on its own
command line. So the broker could expose itself to a Codex worker as an MCP
server without touching the user's config file.

**Assessment for the project: MCP is a genuine common substrate, and it is the
strongest cross-runtime candidate found here.** Two caveats. First, the Codex
server side is deprecated. Second, per-turn granularity: `tools/call` is
request/response and blocks until the turn ends, so it gives you a reply path
but not a progress stream, unlike `codex exec --json`.

Confidence: high, both directions driven and observed.

---

## Q7. Permissions and sandbox

**This section is for Rohan. It is the part the design must not decide on its own.**

### Modes and how they are set

OBSERVED. Sandbox: `read-only`, `workspace-write`, `danger-full-access`, set with
`-s` on `codex exec` (but NOT on `codex exec resume`, see Q1) and with the
`sandbox` field on the MCP `codex` tool.

Approval policy: `on-request`, `never`. Set with `-a` on top-level `codex`, and
with `approval-policy` on the MCP tool.

### Enforcement is real

OBSERVED. Under `-s read-only`, a write was refused with
`zsh:1: operation not permitted` and the target file was unchanged. Not advisory.

The recorded policy is concrete. OBSERVED from `state_5.sqlite`, `-s read-only`:

```json
{"type":"managed","file_system":{"type":"restricted","entries":[
 {"path":{"type":"special","value":{"kind":"root"}},"access":"read"}]},
 "network":"restricted"}
```

`-s workspace-write` expands to the cwd plus **`/tmp` and `$TMPDIR`** as
writable, and the repo's `.git`, `.agents`, `.codex` as read-only. Worth knowing
that `/tmp` is writable in that mode.

### Things that would let refused work get done here

I am flagging these, not exercising them. **I did not run any of them.**

1. **`codex exec` has no approval policy at all.** OBSERVED: every thread my
   probes created recorded `approval_mode = never`, including the ones where I
   passed no approval flag, because `codex exec` rejects `-a`. **In `exec` mode
   the sandbox is the only boundary; there is no human in the loop by
   construction.** A broker that dispatches through `codex exec` is dispatching
   to an agent that can never ask.
2. **`--dangerously-bypass-approvals-and-sandbox`** removes both boundaries at
   once. It is accepted by `codex`, `codex exec`, `codex exec resume` and
   `codex queue`. NOT RUN.
3. **`--dangerously-bypass-hook-trust`** runs hooks without persisted trust. NOT RUN.
4. **`--approve-for-me`** routes approvals through automatic review under
   `workspace-write`, i.e. an agent approving on the human's behalf. NOT RUN.
5. **`-c` can override anything**, including `sandbox_mode` and
   `shell_environment_policy.inherit=all`, so any flag-level restriction the
   broker sets can be undone by a config override in the same command line.
   There is no flag that says "and nothing may loosen this".
6. **Rohan already runs `codex --yolo` habitually.** OBSERVED: three live
   `codex --yolo` processes at probe time. UNVERIFIED: exactly what `--yolo`
   maps to; it is not in `codex --help`. INFERRED from name and context that it
   is a bypass alias. **Worth Rohan confirming**, because if the broker inherits
   that habit the boundary is gone before the design starts.

**The laundering risk, stated plainly.** A Claude Code worker that is denied an
action by its own permission settings could have the same action performed by
dispatching it to a Codex worker spawned with `danger-full-access` and
`approval_mode = never`, and, per Q5, **the denial-vs-success distinction would
not appear in the event stream the broker parses.** The broker must not let a
worker choose its own target runtime's sandbox. That policy belongs to Rohan.

Encouraging note for Phase 4: enterprise-managed config keys exist in the
binary, including `allowedApprovalPolicies`, `allowedSandboxModes`,
`allowedPermissionProfiles`, `defaultPermissions` and `allowManagedHooksOnly`.
UNVERIFIED whether they are usable outside a managed enterprise deployment, but
if they are, they are a machine-level ceiling that a per-invocation flag cannot
raise. That is a much stronger primitive than broker-side discipline.

Confidence: high on what the modes are and that they enforce. The bypass paths
are documented-and-not-run by choice.

---

## Unprompted finding: Codex already has a native multi-agent layer

Not asked for, and relevant enough to report.

OBSERVED, `codex features list`:

```
multi_agent          stable   true
multi_agent_v2       stable   false
steer                removed  true
collaboration_modes  removed  true
enable_fanout        removed  false
send_async_message   removed  false
remote_control       removed  false
```

`multi_agent` is **stable and enabled**. OBSERVED, agent-facing tool names in
the binary: `spawn_agent`, `send_input`, `resume_agent`, `wait_agent`,
`close_agent`, `send_message`, `followup_task`, `interrupt_agent`,
`list_agents`, with a `codex_collab_agent_tool_call_event` analytics event and
an `InterAgentCommunication` type.

It is in real use on this host. OBSERVED, `state_5.sqlite`:

```
CREATE TABLE thread_spawn_edges (
    parent_thread_id TEXT NOT NULL,
    child_thread_id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL);
rows: 59
```

and doctor reports rollout sources `vscode=158, subagent:thread_spawn=59, cli=46`.

**Why this matters to NEXUS Bridge.** Codex already solved spawn, address,
wait, interrupt and inter-agent messaging **within its own runtime**, with a
parent/child edge table and a status column, which is close to the ledger this
project is designing. It does not solve the cross-runtime problem, which is the
whole point of the project, and INFERRED these are tools exposed to the model
rather than CLI commands, so a broker cannot drive them from outside without
going through the app-server. But the identity and edge model is worth copying
rather than reinventing, and `wait_agent` / `interrupt_agent` are evidence that
someone has already had to solve the ack and cancellation problems here.

UNVERIFIED: whether `spawn_agent` and friends are reachable through the
app-server protocol from an external process. That is the single highest-value
follow-up probe, and it needs the daemon question in Q4 settled first.

---

## Recommended spawn recipe

Everything below is OBSERVED to work as written.

```bash
codex exec \
  --json \                                  # JSONL events on stdout
  --skip-git-repo-check \                   # if workdir is not a repo
  -s read-only \                            # or workspace-write; NOT on `exec resume`
  -m "<explicit model>" \                   # pin it; do not trust the config default
  -C "<absolute workdir>" \
  -c model_reasoning_effort="low" \
  --output-schema report-schema.json \      # force a parseable report
  -o "<run>/last-message.json" \
  "<self-contained directive>" \
  < /dev/null \                             # MANDATORY. see Q2.
  > "<run>/events.jsonl" 2> "<run>/stderr.txt"
```

Caller-side checks, in order:

1. Wait for `{"type":"thread.started"}` on stdout with a timeout. No event means
   the spawn did not take; kill the child. Do not infer from process liveness.
2. Record the `thread_id`. Address by UUID only, never by name.
3. On exit, check the code: 0 completed, 1 turn failed, 2 usage error.
4. Confirm the `-o` file exists. Absent means failure.
5. Scan the stream for `turn.failed` and `{"type":"error"}`.
6. Do **not** assume a clean stream means the work was permitted. Verify the
   intended effect independently. See Q5.

---

## Which question was wrong to ask

Q3 as posed assumed the interesting mechanism was `codex queue`. It is not.
`queue` turned out to be the weakest surface of the three I found: no delivery
guarantee, no mid-task reach, no reply path. **The question that should have
been asked is "what does the app-server protocol expose", because that is what
the ChatGPT desktop app drives, it is what `mcp-server` is being deprecated in
favour of, and it is the only surface plausibly reaching the native
multi-agent tools.** I did not probe it because starting the daemon is a
machine-wide state change I would not make unilaterally with a release in
review. Recommend that as nxb-002.1, with Rohan's explicit go-ahead on starting
the daemon.

Secondarily, Q0's premise ("Rohan's notes say Codex down") was stale and cost
nothing to check, which is the argument for keeping Q0 first in every future
runtime probe.

---

## Probe hygiene

- All probes ran in a scratch directory. No repo, no production, no ASC.
- Two messages were injected into `~/.codex/queue_1.sqlite` during Q3 testing,
  both addressed to threads I created. Both were removed afterwards;
  `SELECT COUNT(*) FROM queued_items` returns 0. No stray probe processes remain.
- Rohan has live `codex --yolo` sessions on this host. **No probe targeted, queued
  to, resumed, forked or signalled any session I did not create.**
- I did not start the app-server daemon, did not enable remote control, did not
  change `config.toml`, and did not run any `--dangerously-*` flag.
- Total model spend: seven short turns at low reasoning effort, largest single
  turn 39,745 input / 481 output tokens.
