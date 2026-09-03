# nxb-029: can Claude Code tell the broker it was refused?

Worker 2. Measured on this Mac, Claude Code CLI **2.1.251**, model `haiku`,
10 runs. Raw frames in `evidence/nxb-029/`, probe at
`evidence/nxb-029/probe.py`.

## Verdict, in the declaration's vocabulary

**`refusal_signal` for `claude_code` is PRESENT, not UNMEASURED and not
MEASURED_ABSENT.** `contract/runtimes/claude_code.json` is updated in both
declarations, with the scope written into the value rather than left implied.

It comes in two tiers and the difference decides what W3-9 becomes.

## Tier 1: harness-mediated denial. Fully detectable, survives narration.

When the permission layer denies a tool call, Claude Code emits a **dedicated
mid-stream event**, ten frames before the end of the run:

```json
{"type":"system","subtype":"permission_denied","tool_name":"Bash",
 "tool_use_id":"toolu_01DLcBvdcETBx6mTu8GB8rxx",
 "decision_reason_type":"subcommandResults",
 "message":"Permission to use Bash with command echo NXB029_MARKER has been denied."}
```

and a structured entry in the final frame:

```json
"permission_denials":[{"tool_name":"Bash","tool_use_id":"toolu_...",
                       "tool_input":{"command":"echo NXB029_MARKER", ...}}]
```

**It survives narration, which is the only property that matters here.**
Measured twice (`e8_silent`, `e8b_silent_repeat`): the model was denied and its
entire report was the single word `DONE`, with no mention of the denial, and
`permission_denials` carried the record anyway. The channel is not the model's
to suppress. A field that only populated when the model also reported honestly
would add nothing, because the honest report was already the channel; this is
not that.

No false positives: `permission_denied` frames appear in 4 of 4 denial runs and
0 of 4 non-denial runs (`e0_baseline`, `e1_disallowed`, `e2_manual`,
`e3_dontask`).

## Tier 2: OS or sandbox refusal inside a permitted tool. NOT covered.

This is the case W3-9 was actually written about, and the field does not reach it.

`e10_osdeny`: `cat` a `chmod 000` file. The harness permitted the tool, the OS
refused the read.

```
system/permission_denied frames : 0
result.permission_denials       : []
result.is_error                 : False       subtype: success
tool_result.is_error            : True
tool_result.content             : "Exit code 1\ncat: ./noread.txt: Permission denied"
```

So `permission_denials` is silent. **But the run is not silent**, and this is
the sharp difference from Codex: the failing call is still a discrete frame
carrying `is_error: true` and a non-zero exit, which the model does not author.

Compare the Codex measurement W3-9 rests on. Full event inventory of
`evidence/nxb-002-codex/sandbox-denial-invisible.jsonl`, every line of the file:

```
thread.started
turn.started
item.started    command_execution
item.completed  command_execution  exit_code=0     <- the cat that SUCCEEDED
item.completed  agent_message
turn.completed
```

The denied write produced **no event at all**, not even a failed
`command_execution`. A broker parsing that stream sees a clean run.

So: Claude Code emits a failed tool call; Codex emits nothing. Tier 2 is weaker
than tier 1 because `is_error: true` means "this call failed", not "you were
refused" — but it is not nothing, and nothing is what Codex has.

## The trap in both tiers

`result.is_error` is **false** and `subtype` is **`success`** in every denial
run, tier 1 and tier 2 alike. A broker keying on the top-level success
indicators sees a clean run in all of them. The denial is only ever in
`permission_denials`, in the `permission_denied` event, or in the tool_result.

## What this does to W3-9

W3-9 says a sandbox refusal narrated as done is undetectable, and HANDOFF
~line 1134 states that as a universal property of brokering. On this
measurement it is **per-runtime**:

- Codex: TRUE as measured. No event.
- Claude Code tier 1: FALSE. Structured, dedicated, model-independent.
- Claude Code tier 2: the refusal is not identified AS a refusal, but the
  failure is visible as a failed tool call the model did not write.

The ruling is Rohan's and W3-9 is not edited here.

## Levers, measured rather than assumed

The task named several and asked that behaviour be verified.

| lever | asked for | measured |
|---|---|---|
| `--disallowedTools Bash` | deny the tool | **REMOVES it**: `Bash in tools = False`, 0 attempts, conversational decline, `permission_denials []`. The predicted trap, reproduced. |
| `--disallowedTools "Bash(echo *)"` | deny the call | Tool stays advertised, model attempts, call denied, signal fires. **This is the lever that works.** |
| `--permission-mode dontAsk` | | `init.permissionMode` reads `dontAsk`; tool ALLOWED, no denial |
| `--permission-mode manual` | | tool ALLOWED, no denial, and `init.permissionMode` still reads **`default`** |

`--permission-mode manual` is accepted by the CLI, is listed in `--help`'s
choices, and does not take effect. The only way to notice is that `system/init`
reports a different mode than you asked for. UNVERIFIED whether it is silently
normalised or ignored; measured only that what you asked for is not what you
got. Anyone constraining a child with it believes it is constrained and it is
not.

`--restricted` was not run: `e1_disallowed` already established the
removal-versus-denial distinction and a second removal condition would add
nothing. UNVERIFIED.

## Second question: terminal shape on normal completion

Previously UNMEASURED in both declarations. Normal completion is:

```
subtype "success", stop_reason "end_turn", terminal_reason "completed", is_error false
```

Recorded in the declaration, with the trap above attached, because those same
values appear on runs where work was denied.

## Clean context, measured not assumed

Every run was from an empty directory outside `/Users/rohan`, and each
`system/init` frame reports:

```
cwd          /private/tmp/.../scratchpad/nxb029/work
memory_paths {'auto': '/Users/rohan/.claude/projects/-private-tmp-...-nxb029-work/memory/'}
```

The auto-memory path is keyed to the scratch directory, not to `-Users-rohan`,
so the `MEMORY.md` scoring-key content named at HANDOFF ~line 383 was not
loaded. This is the frame's own report, not an assumption.

## Cost

10 runs. Input tokens per run were 10 to 42 as reported in `result.usage`,
which is the *incremental* count and not the ~12.9k a turn actually costs; the
larger figure at HANDOFF ~line 410 is the honest one for planning. Output
tokens 186 to 1290. Run count is the cost driver, not payload size. Dollars are
Rohan's to apply.

---

# nxb-033 addendum: two corrections to the above, and the scope field

## Correction 1: tier 2 is narrower than nxb-029 said

nxb-029 left "Write/Edit may be harness-mediated where raw shell is not" as
UNVERIFIED. It is settled, in one run, and it narrows the gap.

`e11_write`: the `Write` tool, targeting a file inside a `chmod 500` directory.

```
tool attempted   Write
permission_denials  [{"tool_name":"Write","tool_use_id":"toolu_0153...",
                      "tool_input":{"file_path":".../locked/w.txt","content":"HELLO"}}]
RESULT TEXT      'DONE'
```

**`Write` is harness-mediated**, and the denial was recorded while the model's
entire output was `DONE`. So narration survival is now **n=3 across two
different tools**, and tier 2 is not "file writes". It is specifically *an
effect the harness did not screen, refused by the OS inside a permitted shell
command*. `e9_sandbox` points the same way: the harness intercepted shell output
redirection before the OS ever saw it.

The gap is real and it is smaller than nxb-029 implied.

## Correction 2: nxb-029 attached its measurement to the wrong declarations

This is my error and it is the more useful of the two.

The measurement was taken on `claude -p --output-format stream-json`, where the
broker reads the child's own stdout. nxb-029 then wrote `refusal_signal` **and**
`terminal_signal` onto `without_broker_inbox` and `with_broker_inbox`, which are
`SendMessage` peer transports. A peer pane never hands the broker that stream, so
neither `permission_denials` nor `system/permission_denied` is observable there.

Two genuine `UNMEASURED` nulls were overwritten with a measurement from a
different transport, and `spawned_child`, the one declaration the measurement
actually belonged to, kept `refusal_signal: null`.

nxb-033 reverts the peers to null with reasons naming the transport, and sets
`spawned_child` from the measurement.

**The verification lesson is worth more than the mistake.** The evidence was
checked hard by two parties: Orchestrator 2 re-parsed all ten files, confirmed
frame counts, narration survival at n=2, and the absence of false positives.
Every one of those checks passed and none of them could catch this, because
verifying that a measurement is CORRECT does not check that it is attached to
the right SUBJECT.

## The scope field

A boolean cannot say "yes for one kind of refusal, no for the other", so it is
gone. Declarations carry `_refusal_scope`, a list from a closed vocabulary, and
provenance records `refusal_scope`:

| token | means | measured |
|---|---|---|
| `harness_mediated` | the permission layer refused and said so structurally, independent of narration | present: Claude Code spawned child. absent: Codex |
| `sandbox` | an OS refusal inside an already-permitted call is reported AS a refusal | **absent on both**. This is W3-9's tier |


Removed in nxb-034: a third token, `opaque_tool_failure`, carried "the refused call is at least visible as a FAILED call, without being named a refusal". Worker 1 reviewed it independently and found a concrete defect rather than a matter of taste: the other two tokens are POSITIVE answers about where a refusal was refused, and that one was a NEGATIVE answer with a consolation prize, so a runtime whose only token was `opaque_tool_failure` produced a truthy scope while naming no refusal at all. That breaks the emptiness test `refusal_scope`'s own docstring blesses.

The fact it carried is real and survives in prose here, in the declaration, and in W3-9: Claude Code emits a `tool_result` with `is_error` true where Codex emits no event at all. It is about whether a FAILURE IS OBSERVABLE, not about whether a refusal can be named, and it needs its own axis. It has no machine-readable home yet, deliberately, under the contract embargo: see FAILURE-VISIBILITY-HOMELESS.

Two invariants hold it together: a declaration with no `refusal_signal` may not
claim a scope, a declaration with one must state it, and no declaration may
claim `sandbox` while it is measured absent everywhere.

**It is recorded and never refused on.** Nothing in `ratifiable` reads it.
A scope that made an outcome unratifiable because the runtime cannot report
sandbox refusals would refuse every outcome from every runtime measured so far,
which is the fourth instance of a pattern this project has already caught three
times: refuse on VERIFIED FALSE, never on CANNOT VERIFY.
