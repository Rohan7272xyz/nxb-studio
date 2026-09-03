# Runtime ground truth: Claude Code

Task `nxb-001`. Worker 1. Measured 2026-08-28 against **Claude Code 2.1.250** on
macOS (darwin 25.5.0), user `rohan`.

Everything below was produced by running commands and reading real output. Where
a fact comes from documentation or from reading the shipped binary rather than
from observed behaviour, it says so. Where a probe was inconclusive it says
UNVERIFIED rather than guessing.

Confidence is one of MEASURED (I ran it and saw it), READ (I read it in the
binary or `--help` but did not exercise it), or UNVERIFIED.

**Version-pin warning.** Several findings below are internal behaviours of a
specific build. Re-run the probes in `evidence/nxb-001/` after any Claude Code
upgrade before trusting them.

---

## 0. The short version for a specifying orchestrator

1. `claude -p` is the spawn primitive. It blocks, exits 0 on success and 1 on
   failure, and with `--output-format stream-json` it emits a `system/init`
   event **before any model call**. That init event is the real spawn ack.
2. Every session, including headless `-p` ones, binds a unix socket at
   `/tmp/cc-socks/<pid>.sock`. An arbitrary non-agent process can connect to it
   and inject a turn. I did this from a bare Python script and got a reply.
3. The socket protocol has a genuine **delivery receipt** (`peer_message_status`)
   and a genuine **completion callback** (`peer_idle_notice`). Both correlate by
   `msg_id`. This is the ack the project needs, and it already exists.
4. Silent drops are real and have named causes. Every drop I induced was
   invisible to a naive sender and visible in the recipient's debug log.
5. `sessionId` is **not** stable. `/clear` changes it. The short `[ref]` is
   stable across `/clear` and `/rename`. The orchestrator's inference on
   2026-08-27 was exactly backwards.
6. `claude mcp serve` executes `Bash` for any local process with no permission
   prompt. Treat it as a bypass surface, not as a transport.

---

## 1. SPAWN

**Answer.** There are three programmatic spawn paths. Only the first is suitable
as a broker primitive today.

### 1a. `claude -p` (print / headless). MEASURED.

```
claude -p "<prompt>" --model haiku --output-format json
```

Blocks until the turn completes. Exit 0 on success, 1 on failure.

Output formats (`--output-format`): `text` (default, bare result string),
`json` (one result object), `stream-json` (newline-delimited events).
`stream-json` in print mode requires `--verbose`.

Observed `text` run:

```
$ time (claude -p "Reply with exactly the word PONG and nothing else." --model haiku)
PONG
EXIT=0
2.516 total
```

### 1b. `claude --bg "<task>"` (background agent). MEASURED.

Returns immediately (1s), exit 0, and prints a handle:

```
$ claude --bg "Say BGDONE and stop." --model haiku
backgrounded · b51cd800
  claude agents             list sessions
  claude attach b51cd800    open in this terminal
  claude logs b51cd800      show recent output
  claude stop b51cd800      stop this session
```

`--bg` and `-p` are mutually exclusive and the CLI says so clearly:

```
$ claude --bg -p "Say BGDONE." --model haiku
EXIT=1
--bg and --print conflict: --print never starts the interactive session that
`claude agents` attaches to, so the job would be unattachable.
```

Lifecycle is then readable from `claude agents --json --all`, which reports
`"state": "done" | "failed"` plus a `status` of `idle`/`busy`. This is a real
spawn ack (you get an id synchronously) but the **result** is only retrievable
as terminal output via `claude logs <id>`, not as structured data. That makes it
weak for a broker that needs a parseable return value.

### 1c. Interactive session in a pty (tmux). MEASURED.

Needed only if the target must stay alive between dispatches. See section 3.

### What a FAILED spawn looks like from the caller. MEASURED.

| Failure | Exit | stderr | stdout (json) |
|---|---|---|---|
| Unknown model | 1 | `[claude-code:unrecognized_model] {"model":"no-such-model-xyz",...}` | `is_error: true`, `terminal_reason: "api_error"`, `api_error_status: 404`, human-readable `result` |
| Unknown flag | 1 | `error: unknown option '--not-a-flag'` | none, argument parsing fails before startup |
| Nonexistent `--add-dir` | **0** | none | normal successful answer |

**Trap, and it is a false green.** `--add-dir /definitely/not/here` is silently
ignored. The spawn succeeds and answers normally. A broker cannot rely on the
exit code to tell it that the working-set it asked for was actually granted.

**Trap, and this one is worse.** On the unknown-model failure the result object
still carries `"subtype": "success"` while `"is_error": true`. `subtype` is
**not** a failure discriminator. Use `is_error`, `terminal_reason`, and the
process exit code.

Confidence: MEASURED.

---

## 2. ACK. Does the caller learn it actually started?

**This was the most important question and the answer is yes, on three separate
levels, all of which already exist in the runtime.**

### 2a. Start ack: the `system/init` event. MEASURED.

With `--output-format stream-json --verbose`, the first line is emitted before
any model call:

```json
{"type":"system","subtype":"init","cwd":"...","session_id":"fcc9b4f8-...",
 "tools":[...],"mcp_servers":[...],"model":"claude-haiku-4-5-20251001",
 "permissionMode":"default","claude_code_version":"2.1.250",
 "messaging_socket_path":"/tmp/cc-socks/63067.sock",
 "capabilities":["interrupt_receipt_v1","interrupt_cancel_queued_v1","msg_lifecycle_v1"], ...}
```

This is a positive, machine-parseable "I started, here is who I am, here is
where to reach me". A spawn that produces no init line within a timeout did not
start. **This is what the failed adapter should have been asserting on.**

Note it also hands you the model actually resolved, the permission mode actually
in force, and the socket address, all of which are things an orchestrator
otherwise guesses.

### 2b. Delivery receipt: `peer_message_status`. MEASURED.

When you inject a message over the socket and the recipient does not accept it
immediately, the recipient **sends a receipt back to your own socket**:

```json
{"type":"control","action":"peer_message_status","status":"held",
 "reason":"Your message is held for the recipient user's approval before it reaches
           their Claude session (permission-mode parity).",
 "from":"uds:/tmp/cc-socks/78050.sock",
 "orig_msg_id":"a367df0f-46d3-4468-b2cf-0f28bfadc8c2",
 "msgV":1,"msg_id":"d6c525c9-..."}
```

Correlation is by `orig_msg_id`. The status vocabulary, read from the binary and
partially exercised, is: `held`, `denied`, `expired`, `delivered`, `refused`,
`dropped`. `dropped` additionally carries `drop_reason` and `dropped_msg_ids`.
Each has a fixed human-readable `reason` string. (Vocabulary: READ.
`held`: MEASURED.)

**The receipt is conditional and this is the single biggest trap in the whole
protocol.** The recipient only sends it if your `from` address is a
well-shaped socket path inside its own socket namespace. When I sent
`"from":"uds:probe"` the recipient logged:

```
[uds-messaging] hold-receipt skipped: reply address unshaped or outside our
socket namespace (uds:probe)
```

and I got nothing. **A sender with no real inbox is structurally incapable of
being told that its message failed.** That is very likely the shape of the
0-for-7 silent failure. The fix is not a retry or a timeout, it is that the
broker MUST bind and listen on its own `/tmp/cc-socks/<name>.sock` before it
sends anything.

### 2c. Completion callback: `notify_when_idle` / `peer_idle_notice`. MEASURED.

Send:

```json
{"type":"control","action":"notify_when_idle","from":"uds:<your.sock>","msg_id":"<id>"}
```

Receive, when the recipient's turn ends:

```json
{"type":"control","action":"peer_idle_notice","orig_msg_id":"5221d9db-...",
 "state":"idle","finished_at":1787931629782,
 "from":"uds:/tmp/cc-socks/42713.sock","from_mode":"prompting",
 "msgV":1,"msg_id":"b98b8925-..."}
```

**Warning, and this one will bite.** `state: "idle"` means *the recipient's turn
ended*, not *the work you asked for finished*. In my probe the notice fired at
10.8s on a task that was still running a 25-second backgrounded shell command;
the session had merely gone briefly idle between turns and only produced its
real answer later. Treating `peer_idle_notice` as completion is exactly the
false green that HANDOFF rule 8 warns about. It is a liveness signal, not a
completion signal. Completion still has to be asserted against the artifact.

### 2d. How to detect a launched-but-never-started agent. MEASURED.

In order of strength:

1. No `system/init` line within a few seconds of spawn. Definitive.
2. `connect()` to `/tmp/cc-socks/<pid>.sock` refused. See the liveness trap below.
3. `claude agents --json` does not list the session.

**Liveness trap.** The socket file **outlives the process**. After my probe
sessions exited, six stale `.sock` files remained in `/tmp/cc-socks/`. Existence
of the file proves nothing:

```
$ python3 udsprobe.py /tmp/cc-socks/10067.sock ...   # pid 10067 is dead
CONNECT_FAIL ConnectionRefusedError [Errno 61] Connection refused
$ # live session
CONNECT_OK (live listener)
```

A `connect()` probe is a valid liveness check and a directory listing is not.
The runtime does exactly this internally (a 250ms connect with a `live`/`dead`
verdict) and reaps stale sockets it finds.

**Trust-gate trap.** An interactive session in an untrusted directory **binds its
socket before the trust prompt is answered**. I observed a session sitting on
"Is this a project you created or one you trust?" with a live, connectable
socket. It is reachable and completely unable to work. `claude agents --json`
did not list it by name until the prompt was cleared, so cross-check the
registry, not just the socket.

---

## 3. MESSAGING A RUNNING AGENT FROM A NON-AGENT PROCESS

**Answer: yes, fully, and I proved it from a bare Python script.**

`/tmp/cc-socks/<pid>.sock` is a per-session unix domain socket. The filename is
the **process id** of the `claude` process. Newline-delimited JSON, one object
per line.

The runtime prints its own injection recipe into the debug log:

```
[uds-messaging] Listening: /tmp/cc-socks/73856.sock
[uds-messaging] Inject messages (auth line optional here):
  { echo '{"type":"auth","token":"'"$CLAUDE_CODE_MESSAGING_TOKEN"'"}';
    echo '{"type":"user","message":{"role":"user","content":"hello"}}'; } |
  socat - UNIX-CONNECT:/tmp/cc-socks/73856.sock
[uds-messaging] ... a connection that sends no complete line within 30000 ms is closed
```

### Message shape (MEASURED)

```json
{"type":"user",
 "message":{"role":"user","content":"<text>"},
 "from":"uds:/tmp/cc-socks/<your-broker>.sock",
 "uuid":"<uuid>","msg_id":"<uuid>",
 "priority":"now"|"next"|"later",
 "session_id":"<recipient session id>"}
```

`priority` defaults to `next` if absent or unrecognised. `session_id` is
optional but see the stale-id trap in section 4. `file_attachments` is also
accepted (READ, not exercised).

### Proof of round trip (MEASURED)

A Python script with no relationship to Claude Code delivered a turn into a live
interactive session, which processed and answered it:

```
$ python3 broker.py /tmp/cc-socks/82077.sock "NXB PROBE 7: reply with exactly the word EXTERNAL7..."
LISTENING /tmp/cc-socks/nxb-76661.sock
SENT to /tmp/cc-socks/82077.sock

# recipient debug log:
[uds-messaging] Routed user message to queue (priority=next): NXB PROBE 7: ...

# recipient terminal:
❯ Another Claude session sent a message:
  NXB PROBE 7: reply with exactly the word EXTERNAL7 and nothing else.
⏺ I received a message from another Claude session with an unusual request...
```

### Four things the broker design has to know

1. **Provenance is asserted, not verified.** The sender was a Python script. The
   recipient was told "Another Claude session sent a message" and given the
   standard peer-trust preamble about teammates working on the user's behalf.
   `from` is self-declared. Anything local that can write to the socket inherits
   peer trust. Section 7.
2. **There is no content reply channel.** The recipient's answer went to its own
   terminal. The socket returns only `control` frames (status and idle notices).
   To actually retrieve a worker's output the broker must read the session
   transcript or use a `-p` session whose stdout it owns.
3. **Print-mode sessions accept but discard.** A message injected into a busy
   `-p` session is accepted (`Routed user message to queue (priority=next)`) and
   then never processed, because `-p` exits at the end of its turn. Long-lived
   targets must be interactive.
4. **The 30s first-line deadline.** Connect only when the payload is ready.

### Auth (partially UNVERIFIED)

An `{"type":"auth","token":"..."}` first line is supported. On this macOS build
auth was **optional**: every probe succeeded without it. Child processes inherit
`CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_CODE_MESSAGING_TOKEN` (32 chars) in
their environment, which is how a spawned child talks back to its parent
session. The binary shows a mode where auth is REQUIRED and the session refuses
to run an inbox no peer can authenticate to. **I did not exercise the
auth-required path.** Do not assume the broker can stay anonymous on other
platforms or under other settings.

---

## 4. IDENTITY

This is where the 2026-08-27 mistake came from, and the truth is the inverse of
what was assumed.

Two different identifiers exist and they have opposite stability properties.

| | `sessionId` (uuid) | short `[ref]` |
|---|---|---|
| Where | `claude agents --json`, `system/init`, stream events | `ListAgents` output |
| Survives `/clear` | **NO, it changes** | **YES** |
| Survives `/rename` | yes | **YES** |
| Survives process restart | no | no (process-scoped) |
| Is it a prefix of the other | **NO** | **NO** |

### Measured, on one session, pid 82077 held constant

```
BEFORE /clear
  ListAgents:          NXB-TARGET [9be3bf]
  agents --json:       82077  93395b11-0dae-4fcb-a927-6450699c4985  NXB-TARGET

AFTER /clear
  ListAgents:          NXB-TARGET [9be3bf]          <-- ref UNCHANGED
  agents --json:       82077  367f4e3d-2a9f-4051-9bb1-29e5d33706c4  <-- sessionId CHANGED
  socket:              /tmp/cc-socks/82077.sock     <-- unchanged

AFTER /rename to NXB-RENAMED
  ListAgents:  NXB-RENAMED [9be3bf] · says it was NXB-TARGET until 10s ago
```

Note the ref is not a prefix of the sessionId in either direction: session
`93395b11...` has ref `9be3bf`; Worker 1's session `40a04431...` has ref
`00cfa6`.

**So: a changed ref does not mean a session was cleared. It means the process
restarted.** A `/clear` leaves the ref, the pid, the socket and the name all
intact and silently rotates the sessionId underneath.

The runtime is also helpful about renames, annotating "says it was X until 10s
ago", which a broker can use to follow an identity across a rename.

### The trap this creates, and it is a silent one. MEASURED.

`session_id` in an injected message is validated against the recipient's
*current* session. After a `/clear` a cached id is stale and the message is
dropped:

```
[WARN] [uds-messaging] Dropping user message: session_id mismatch
  (got "93395b11-0dae-4fcb-a927-6450699c4985",
   expected "367f4e3d-2a9f-4051-9bb1-29e5d33706c4")
```

The sender saw nothing (my `from` was unshaped, so no receipt). **A broker that
caches sessionId at dispatch time will silently 0-for-N every worker that has
been cleared since.** Given that Rohan clears panes by hand and a pane cannot
clear itself, this is not a hypothetical.

Recommendation for Phase 3: address workers by **ref plus pid**, re-resolve
`sessionId` from `claude agents --json` immediately before each send, or omit
`session_id` entirely (it is optional, and omitting it removes the mismatch
failure mode at the cost of losing the guard against messaging a rotated
session).

### Discovery surface. MEASURED.

`claude agents --json` needs no TTY and returns the full registry:

```json
{"pid":44948,"cwd":"/Users/rohan","kind":"interactive",
 "startedAt":1787855705586,"sessionId":"40a04431-...","name":"Worker 1","status":"busy"}
{"id":"b51cd800","kind":"background","sessionId":"b51cd800-...",
 "name":"Say BGDONE and stop.","status":"idle","state":"done"}
```

`kind` is `interactive` or `background`. `status` is `idle`/`busy`. Background
sessions additionally carry `state` (`done`/`failed`). `--all` includes completed
background sessions. Socket path is derivable as `/tmp/cc-socks/<pid>.sock`.

---

## 5. STRUCTURED OUTPUT

**Answer.** The strongest contract is `--output-format json` plus `--json-schema`.

### Schema-validated output. MEASURED.

```
$ claude -p "What is 2+2? Answer with the number and a one word confidence." \
    --model haiku --output-format json \
    --json-schema '{"type":"object","properties":{"answer":{"type":"integer"},
                    "confidence":{"type":"string"}},
                    "required":["answer","confidence"],"additionalProperties":false}'
```

yields a dedicated validated field alongside the string result:

```json
"result": "{\"answer\":4,\"confidence\":\"Certain\"}",
"structured_output": {"answer": 4, "confidence": "Certain"}
```

Use `structured_output`. Do not re-parse `result`.

### The result envelope. MEASURED.

Useful fields: `is_error`, `subtype`, `terminal_reason`, `stop_reason`,
`api_error_status`, `session_id`, `result`, `structured_output`,
`permission_denials`, `total_cost_usd`, `usage`, `num_turns`, `duration_ms`,
`modelUsage`, `subagent_stats`.

`subagent_stats` is worth noting for a broker: it reports `spawned`, `completed`,
`failed`, `killed` and `refused` counts for any subagents the session ran, which
is a cheap cross-check that delegated work actually happened.

### Failure shapes. MEASURED.

| Situation | exit | `is_error` | `subtype` | `terminal_reason` |
|---|---|---|---|---|
| Success | 0 | false | `success` | `completed` |
| Unknown model | 1 | true | **`success`** | `api_error` (+ `api_error_status: 404`) |
| SIGINT mid-tool | (killed) | true | `error_during_execution` | `aborted_tools`, `result: null` |
| Unknown flag | 1 | n/a | no JSON at all | n/a |

Interrupt is clean and machine-detectable: SIGINT to the claude process still
produces a final result record with `terminal_reason: "aborted_tools"` and a
null result.

**Process-identification trap.** Under `command claude ...` (and any similar
wrapper) the first matching pid is a `/bin/sh /usr/bin/command` wrapper, not the
agent. I initially signalled the wrapper and the agent ran happily to completion,
which briefly looked like "SIGINT is ignored". It is not; I had the wrong pid.
The broker must track the actual `claude` pid, which is also the one that names
the socket.

### Permission denials. UNVERIFIED.

`permission_denials` is present in every envelope and was `[]` in all my runs. I
tried to force a denial with `--disallowedTools Bash`, but the model declined to
attempt the destructive-looking command at all and answered conversationally, so
no denial was recorded. **I did not observe a populated `permission_denials`
array and cannot state its element shape.** Worth one more probe with a benign
tool that the model will certainly call.

---

## 6. MCP

**Answer: yes, but not as a way to drive an agent.**

`claude mcp serve` starts a stdio MCP server. MEASURED:

```json
{"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},
 "serverInfo":{"name":"claude/tengu","version":"2.1.250"}}}
```

- `tools/list` works. 26 tools: `Agent`, `TaskOutput`, `Bash`, `Read`, `Edit`,
  `Write`, `NotebookEdit`, `WebFetch`, `ReportFindings`, `WebSearch`, `TaskStop`,
  `Skill`, `DesignSync`, `EnterWorktree`, `ExitWorktree`, `SendMessage`,
  `ListAgents`, `Workflow`, `CronCreate`, `CronDelete`, `CronList`,
  `ScheduleWakeup`, `RemoteTrigger`, `Monitor`, `PushNotification`, `ToolSearch`.
- `prompts/list` and `resources/list` both return `-32601 Method not found`.
- Capabilities advertise `tools` only. No sampling.

**The important distinction.** This exposes Claude Code's **tools** to an
external MCP client. It does not expose a Claude Code **agent**. There is no
sampling capability, so an MCP client cannot ask this server to think. As a
common substrate across runtimes it gives you a shared *tool* layer, not a
shared *agent* layer. If the cross-runtime plan assumed MCP would let one
orchestrator drive a Claude Code agent, that assumption is wrong.

**However**, `SendMessage` and `ListAgents` are exposed as MCP tools, and both
work over MCP. MEASURED:

```
ListAgents via MCP -> "Peer sessions (11): Worker 2 [908cd0] · interactive · idle ...
                       NXB-TARGET [9be3bf] · interactive · idle · tmux nxb:@0.%0 ..."
```

So an external MCP client *can* reach into the session mesh indirectly. That is
a real cross-runtime path and it is worth Phase 2 attention. It is also a
permission problem. Section 7.

---

## 7. PERMISSIONS, AND WHERE WORK REFUSED IN ONE CONTEXT COULD BE DONE IN ANOTHER

### Modes. READ from `--help`, spot-checked.

`--permission-mode`: `acceptEdits`, `auto`, `bypassPermissions`, `manual`,
`dontAsk`, `plan`. Set at spawn time. Related flags: `--allowedTools`,
`--disallowedTools`, `--tools`, `--dangerously-skip-permissions`,
`--allow-dangerously-skip-permissions`, `--restricted`, `--safe-mode`,
`--add-dir`, `--settings`, `--setting-sources`.

`--restricted` is the strongest documented confinement: removes command-running
tools and WebFetch unless `--tools` names them, ignores user/project/local
settings, confines file tools to the working directories, and **refuses
bypassPermissions**.

The mode actually in force is reported in `system/init` as `permissionMode`, so
a broker can verify rather than assume.

### The good news: cross-session injection already has an anti-laundering gate. MEASURED.

The runtime enforces **permission-mode parity** on inbound peer messages. Logic,
read from the binary and confirmed by probe: the recipient classifies itself as
`bypass` (if mode is `bypassPermissions`, or `plan` with bypass available) or
`prompting`. Then:

- recipient `prompting`, sender asserts nothing -> **accept**
- recipient `bypass`, sender asserts nothing -> **hold**, cause `no-mode-asserted`
- sender asserts a mode that differs -> **hold**, cause `mode-mismatch`
- unrecognised recipient mode -> **hold**, fail-closed

Measured against a `--permission-mode bypassPermissions` session:

```
[cross-session-inbound] held inbound peer message (1 held, cause=no-mode-asserted):
  from=uds:/tmp/cc-socks/nxb-78147.sock "NXB PROBE 5: say EXTERNAL5"
receipt -> status "held", reason "...held for the recipient user's approval
                                  before it reaches their Claude session
                                  (permission-mode parity)."
```

So an external process **cannot** silently push work into a bypass-mode session.
It is held for a human. That is a deliberate boundary and the broker must not try
to route around it.

I attempted to assert `from_mode` on a `type:"user"` message and it made no
difference (still `no-mode-asserted`). Reading the binary, `from_mode` is parsed
only on `notify_when_idle` control frames on this build, and the user-message
mode path sits behind an internal gate. **Why claude-to-claude peer messages into
a bypass session are accepted while an external process is held is UNVERIFIED.**
I observed the outcome (Orchestrator 1's message reached this bypass-mode
session, carrying `from-mode="bypass"` in its envelope) but did not capture that
wire frame, so I cannot state the mechanism.

### The bad news, and this is the finding Rohan should see. MEASURED.

**`claude mcp serve` executes `Bash` with no permission prompt and no mode gate.**

```
tools/call Bash {"command":"echo NXB_MCP_BASH_OK; id -un"}
-> {"stdout":"NXB_MCP_BASH_OK\nrohan","stderr":"","interrupted":false}
```

I checked that this is a property of the surface and not of this user's config:
`~/.claude/settings.json` has no `defaultMode` and an empty `allow` list;
`settings.local.json` has 59 narrowly-scoped allow entries and nothing matching
`echo ...; id -un`. There is no interactive client, so nothing can prompt, and
the call simply runs as the user.

Consequences for the design:

1. Any local process that can exec `claude mcp serve` gets unprompted shell
   execution as the user. It is a bypass surface.
2. Therefore it is a **laundering path**: work refused inside a `--restricted`
   or prompting-mode session can be completed by shelling out to
   `claude mcp serve` and calling `Bash`. The parity gate on the UDS path
   (which is well designed) does not cover this route.
3. The broker must never expose `mcp serve` as a transport, and Phase 4 should
   treat "can this component exec `claude mcp serve`" as a privilege in itself.

Flagging per instruction: this is a boundary the design has to respect, and it
is Rohan's call, not the orchestrator's.

### Provenance is not authenticated. MEASURED.

The `from` field is self-declared. A bare Python script was announced to the
recipient as "Another Claude session". A broker that relays between runtimes will
be trusted as a peer by every recipient. Sender identity needs to be established
by the broker, because the runtime does not establish it. There is peer-pid
verification machinery in the binary (`verifiedPeerPid`, `verifiedPeerProcStart`,
ancestry and start-token checks) but I did not determine what it gates. UNVERIFIED.

---

## Probes I deliberately did not run

- **Auth-required inbox.** Would have meant changing messaging settings on a
  machine with live worker sessions and a release in review. Described, not run.
- **Forcing a populated `permission_denials`.** My one attempt did not trigger a
  denial; I did not escalate to a tool the model would certainly call, to avoid
  burning quota. The weekly limit was at 89% during this task.
- **Anything under `~/downstream-project`, main, or production.** Out of scope by
  directive. All probes ran in a scratch directory and two disposable tmux
  sessions, both torn down.

## Reproduction

Probe scripts and captured logs are in `evidence/nxb-001/`:
`t5.log` (hold plus receipt), `t7.log` (external injection routed),
`t9.log` (notify_when_idle), `k1.jsonl` (SIGINT result envelope),
`B.json` (result envelope), `mcp.out` (MCP surface).

Re-derive the wire contract at any time by running any session with
`--debug-file <path>` and grepping `uds-messaging`. The runtime prints its own
socket path, its injection recipe, and the reason for every drop or hold. That
log is the single highest-value diagnostic on this runtime and the failed
adapter would have been debugged in minutes with it.
