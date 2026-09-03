# nxb-010: H2 built against Codex, and three refusals died

Task: nxb-010. Author: Worker 3. Date: 2026-08-28.
Built: H2, broker to runtime spawn, against Codex. 48 tests passing.
Not built: H3, H4, canary, provenance, permission boundary. `codex app-server`
not started. **`contract/contract.json` not modified** (see section 2).
Tags: **[M]** measured, **[A]** assumption, **[H]** hole.

## 0. An incident I caused, first

At approximately 12:03 I ran `pkill -f "codex exec"` to clean up what I believed
were my own stray children after a test hung. **That pattern matched Worker 1's
nxb-009 run and killed it**, because its shell wrapper carried the same string.
I did not check what the pattern would match before running it.

Damage, bounded and reported to Orchestrator 1 within two minutes: Worker 1's
run had read the contract and reached an early todo item; `codexwork/` contained
only the two input files, so no implementation was lost, no state corrupted, and
the blind test was **not** contaminated because the Codex thread never produced
code and never saw anything under `nxb/`. Recovery is a re-run.

It is in this report and not only in a message because it produced the most
concrete refusal in the task. See F-15b in section 5.

## 1. Which runtime, and what rejecting the other costs

**Codex.** Four reasons, in order of weight.

1. **H2's whole job is proving the start signal, and only Codex has a measured
   one.** `thread.started` is machine-readable, arrives before any model work,
   and carries the id everything else needs [M: nxb-002]. Building H2 against
   Claude Code without a broker inbox would have re-run F-1 and taught nothing
   new: the runtime declares a null `start_signal`, so registration refuses and
   there is no spawn to observe.
2. **It produces the number you asked for.** Time-to-start needs repeated real
   spawns against a real runtime. Section 3.
3. **It exercises measured rules that broker code has never run.** F-13's stdin
   trap and F-14's `-o` asymmetry were facts in a document until this task.
4. **Cost of the alternative.** Claude Code's H2 over the peer mesh requires
   binding a socket into `/tmp/cc-socks/`, a live namespace holding ten of
   Rohan's running sessions. That is a user-visible state change with real blast
   radius and nobody authorised it. Declining to do that unilaterally is the
   same call as not starting `app-server`.

**What rejecting Claude Code costs:** the `peer_message_status` receipt path
stays unexercised, so the one runtime with real delivery-receipt machinery is
still unproven in code. That is the next H2, and it needs either authorisation
to bind an inbox or the variant below.

**A finding that partly dissolves your Phase 2 constraint.** You wrote that
Claude Code has no content reply channel, so a broker must own stdout or read
the transcript. True for **messaging an existing session**. Not true for
spawning: a broker that spawns its own `claude -p` child owns that child's
stdout exactly as it owns Codex's. **The missing content channel is a property
of peer-messaging, not of the runtime.** So for H2 both runtimes have the same
shape, own-the-subprocess, and the asymmetry only appears when reaching a
session you did not spawn. That is worth knowing before adapter shape is fixed.

## 2. H2 forced a contract change in its first minute

`contract.json` defines `receipt.hop` with `"enum": ["H1"]`. An H2 receipt
cannot validate. You told me to report rather than make such a change, so:

**Reported, not made.** `contract/contract.json` is byte-identical
(`git diff --stat` empty). H2's schemas live in a new `contract/h2.json`, which
is additive: nxb-009's blind implementation sees exactly what it saw before.

**The defect for the merge queue: a closed enum in a v1 schema blocks the v2
that was always planned.** `hop` was written as a fixed set on the day only one
hop existed. When nxb-009 reports, widen it and merge `h2.json` in.

## 3. The number nobody had

Real spawns, this Mac, `codex-cli 0.150.1`, `-m gpt-5.6-luna -s read-only`,
trivial prompt, `model_reasoning_effort=low`.

| | seconds to `thread.started` |
|---|---|
| cold, first spawn of the session | **0.685** |
| warm, n=6 | 0.094, 0.118, 0.106, 0.096, 0.142, 0.167 |
| warm min / max / mean / median | 0.094 / **0.167** / 0.120 / 0.112 |

**Spec assumption A-023 was 30 seconds. Observed warm max is 0.167s and cold is
0.685s: the assumption was 44x to 320x too generous.**

An over-long start timeout is not a free safety margin. **It is exactly how long
a hung spawn holds a slot before the trap is detected**, and section 4 shows the
trap is real and produces zero bytes. Recommendation, marked as extrapolation:

**[A] Set `start_timeout` to 5 seconds.** That is 30x the observed warm max and
7x the cold observation, leaving room for a cold binary, a slow network, or a
loaded machine, while detecting a hang in five seconds rather than thirty. The
data behind it is n=7 on one machine with one prompt size on a warm cache, so it
is an informed number, not a measured bound.

**What H2 could NOT produce: F-5's staleness budget.** That number is how often a
runtime goes stale *while idle*, and a spawn hop cannot observe idleness by
construction. It needs the canary running over days. **[H]** It remains the
project's oldest unmeasured number and the reason F-5 is still intolerable.

## 4. The F-13 trap, reproduced and defeated

[M: nxb-002] said `codex exec` hangs forever if the caller leaves stdin open. I
exercised it deliberately with a never-EOF pipe:

```
result: started=False  reason=no_start_signal_within_timeout  killed=True
        exit_code=0  out_present=False
wall: 8.01s  (budget was 8s)
bytes the trapped child produced: 0
```

Confirmed in every particular: zero bytes, no `thread.started`, and the child
alive until killed. The adapter's `subprocess.DEVNULL` prevents it; the trap only
appears when deliberately requested.

**And note `exit_code: 0`.** See F-16b.

## 5. Refusals that died on contact

Three, and the first two are the task's real output.

### 5.1 F-15 was structurally incapable of firing. Twice.

F-15 says: no start signal within `start_timeout` means kill the child. The
obvious implementation checks the clock between reads and then calls a blocking
`readline()` on the child's stdout.

**Against the F-13 trap the child emits zero bytes, so `readline()` blocks
forever and the clock is never consulted again.** My first implementation hung
for **two minutes on an eight second budget** and was only stopped by the tool
harness. A timeout that cannot fire is not a timeout, and the refusal was
structurally incapable of firing against the exact trap it was written for.

Fixed with `selectors`, so every read is bounded by the remaining budget. Re-run:
8.01s against an 8s budget, killed cleanly.

**Then the same bug turned up a second time.** `drain()` had an identical bare
`readline()` under a wall-clock budget, and I only noticed because an unrelated
test failure made me reread the file. **I had fixed the bug where it bit me and
left it where it had not bitten me yet.** Both are now non-blocking.

**Spec consequence: F-15 needs a clause it does not have.** "Kill the child on
timeout" is unimplementable as written. The rule must say **the wait must be
non-blocking**, because the natural implementation of the refusal is one that
cannot enforce it.

### 5.2 F-15b: kill only what you hold a handle to

Written from section 0. The obvious way to satisfy "kill the child" when you have
lost track of it is a pattern kill, and **a pattern kill on a machine running
several agents reaps other tenants' work, silently, with no error**.

**New clause: a broker may kill ONLY processes it holds a direct handle to, never
by command-line pattern.** Enforced rather than documented: a test parses every
module's AST and fails if `pkill` or `killall` appears in any string literal
outside a docstring.

That test's first version scanned raw text and failed on the comment explaining
why we never pattern-kill. **A grep-shaped check produced a false red on the
sentence describing the rule it was enforcing**, which is a small live
demonstration of why this project distrusts checks that pattern-match prose.

### 5.3 F-16b: a killed spawn exits 0

F-16 bans process liveness as evidence. Contact added a sharper case:

[M] A child SIGINTed for missing its start signal **exits 0**. A broker keying on
the exit code sees success for a process it just killed for never starting.

**Only two signals are truthful here: the presence of `thread.started`, and the
absence of the `-o` file.** The exit code is not a third. F-14's "reliable in one
direction only" generalises: **the exit code is reliable for a turn that ran and
meaningless for one that never began**, and the capability declaration must say
which of those a signal covers, not merely which direction it is reliable in.

## 6. Refusals that survived contact

| refusal | evidence |
|---|---|
| **F-13** stdin from `/dev/null` | trap reproduced only when explicitly requested; default path never hangs |
| **F-14** `-o` absence is failure, presence is not success | absent on the trapped run, present on every healthy one, never named `ok` |
| **F-6 analogue at H2** receipt before judgement | the H2 receipt is emitted on `thread.started`, before anything knows whether the turn will succeed |
| **F-7 analogue** no verdict in a receipt | `h2_receipt.forbidden_fields` includes `success`; tested |
| **parent_not_accepted** | a REFUSED H1 dispatch cannot become work. The old system had no equivalent: a directive that failed validation simply vanished |
| **spawn_once** | a second spawn for the same H1 receipt is REFUSED, not silently deduplicated. Proven on the live run |
| **R-030** pin the model | `-m` on every command, asserted by test |

End to end against live Codex: H1 `OBSERVED` to H2 `STARTED` in 0.141s, drain
clean (`turn.completed`, exit 0, `-o` present), second spawn attempt `REFUSED:
already_spawned`.

## 7. New vanish points

| # | vanish point | status |
|---|---|---|
| 20 | **A timeout implemented around a blocking read.** The refusal exists, is tested against payloads that arrive, and cannot fire against the silence it was written for | **CLOSED here**, and it is a spec defect: F-15 as written invites this implementation |
| 21 | **Pattern-based process cleanup reaps other tenants.** Silent, no error, and the victim learns only from its own missing output | **CLOSED here** by F-15b and an AST test. **OPEN in general**: nothing prevents a future adapter from shelling out |
| 22 | **A killed child reports success.** Exit 0 after SIGINT means an exit-code-keyed broker records a false green for work that never started | **CLOSED here** by keying on start signal and `-o` absence |

## 8. The sol/luna divergence does not currently reproduce

[M] this Mac, 2026-08-28, on the live end-to-end thread
`01a04920-2172-7123-b578-9b73fc3742d1`:

```
PINNED by broker  : gpt-5.6-luna
RECORDED by thread: gpt-5.6-luna
~/.codex/config.toml: model = "gpt-5.6-luna"
```

Config, pin and recorded identity all agree. **I am not calling nxb-002 wrong.**
I did not see the config when they read it, so the divergence may have been
fixed, may be transient, or may have been a misreading, and I cannot distinguish
those three.

**The design consequence is real either way.** The `identity_baseline` machinery
in the spec, R-054 through R-057, exists to make a *systemic* divergence
distinguishable from a per-dispatch one. **On the only evidence available today,
there is no systemic divergence to be baselined.** Building that machinery now
would be building against an unobserved condition, which is the project's own
rule 2. Recommendation: keep R-030 (pin) and R-031 (record what ran), which are
cheap and correct regardless, and **defer the baseline until a divergence is
observed twice.**

## UNVERIFIED

- The 5-second `start_timeout` recommendation is extrapolation from n=7 on one
  machine, one prompt size, a warm cache and a good network.
- I did not measure a cold spawn after a reboot, a large prompt, or a degraded
  network. The cold/warm gap (0.685 vs 0.167) suggests the tail matters and I
  have one cold sample.
- `drain()`'s budget behaviour under a mid-turn hang is untested. I fixed the
  bug by inspection after fixing its twin; I did not reproduce the hang there.
- The sol/luna finding is one observation of one config file at one time.
- Claude Code's H2 path is entirely unexercised.
- 48 tests, still written by the same author as the code. nxb-009 remains the
  only independent check and I killed its first run.

## Where I think you may still be framing this wrongly

**1. The most valuable output of this task was produced by a mistake, and that
should change how these tasks are scoped.** F-15b exists because I broke
something. F-15's real defect surfaced because a test harness killed a hang I
had not predicted. Neither would have appeared in a specification, and neither
appeared in nxb-005's twenty-five refusals despite the spec being written by the
same person who then failed to implement two of them correctly. **Scope future
build tasks to include deliberately hostile conditions**, because the honest
conditions found more in one hour than the careful ones did.

**2. "Refusals that survived contact" is a weaker claim than it sounds, and I
should stop letting it stand unqualified.** Seven refusals survived. But every
one of them survived a test I wrote against an adapter I wrote, and the three
that died were found by a hung process, a harness timeout, and a mistake, not by
my tests. **My tests have never yet caught one of my own refusal defects.** That
is worth putting in the handoff as a measured property of this workflow rather
than a worry: the tests demonstrate the refusals, they do not test them.

**3. The project now has three unmeasured numbers and one of them is load
bearing.** `start_timeout` is measured. F-5's staleness budget, the canary
interval, and the H3 drain budget are not, and F-5's is the one that already
killed a refusal in nxb-006. A spawn hop cannot produce it. **If F-5 matters,
the canary has to be built next**, and if it does not matter enough to build the
canary, F-5 should be dropped rather than left as a rule the operator forges
proofs to get past. Leaving it in its current state is the worst of the three
options, and it is where the project currently is.
