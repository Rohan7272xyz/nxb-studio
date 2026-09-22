# nxb-078: peer rigs, and a reply that survives its own pane

2026-09-07. Built for Rohan's multi-rig programme (one product, five rigs,
a hub orchestrator driving four domain orchestrators).

## The gap

A rig has at most one orchestrator (`compose_agents`, enforced). So anything
larger than one fleet is several rigs, and nothing let their orchestrators
talk. Reading the code showed the TRANSPORT never forbade it: names carry
their rig (RIG-20), so `mint`, `rig send` and `rig collect` already resolve
any pane in any standing rig by its full name, and the orchestrator pane is
in the roster and enrolled. What forbade it was the BRIEF: "YOU BELONG TO RIG
X AND ONLY THAT RIG", with `--session X` hard-coded into its three commands.
A compliant orchestrator refused to cross rigs. The rule was the wall.

## What changed

1. **`peers`** on a rig (draft field, `POST /api/rig/up` body, `rig up
   --peers`, `rig orchestrate --peers`). When present, the orchestrator brief
   gains a PEER RIGS paragraph: the named rigs' ORCHESTRATORS are addressable
   with the same three commands and `--session <peer>`; a peer's workers stay
   that peer's; a refusal means stop and ask, never substitute. Absent peers,
   the brief is byte-identical to before. A self-peer or a name a session
   cannot carry is refused as `rig_peer_invalid` before tmux is touched. The
   rig record remembers its peers so `rig clear` re-briefs the same way.

2. **`rig reply`**, a filed answer. `collect` scrapes a pane's screen, and
   MEASURED 2026-09-03 a Claude Code pane scrolls its transcript internally,
   so an unanchored answer is cut to a 60-line budget and a busy orchestrator
   pane can lose its marker entirely. `rig reply --worker <me> --task-id <id>
   --file <report>` files the answer next to the ledger under the task id,
   after the same `validate` the worker ran on the directive, so an answer
   cannot be filed into another worker's task. `collect` reads the outbox
   FIRST and whole (`source: outbox`), and falls back to the screen as before
   (`source: pane`). Every live directive now asks for filing; a worker that
   does not file still collects off the screen, so this degrades, never gates.

3. **Codex `max`** in the Studio effort picker. MEASURED 2026-09-07 on
   codex-cli 0.153.4: `codex exec -m gpt-6-astra -c
   model_reasoning_effort="max"` answered (6,137 tokens). The binary's effort
   enum reads minimal/low/medium/high/xhigh/max/ultra. `ultra` is nested
   delegation and stays out of a picker that composes a visible fleet.

## Shape of a programme

Hub-and-spoke. The hub rig lists the domain rigs as peers; the domain rigs
list none, so they can only answer. A peer mesh would let A wait on B while
B waits on A, and `collect` is a blocking poll with no deadline by design.
A peer's task is itself a whole wave of dispatches and can take hours, so the
hub collects it with `rig collect --wait 900` (or `rig await` across several
peers), which waits inside the command rather than in the hub's own turn.
`WAITING` is still not failure. (Corrected by nxb-079: "polls every few
minutes" was the single most expensive sentence in the system; see
docs/CONTEXT-BUDGET-nxb-079.md.)

## Not done

- The peer's directive is typed into a pane that may be mid-turn. The runtime
  queues it (measured for workers on 2026-09-03), but a peer that is polling
  its own workers in a tight loop will not read it until that turn ends.
- Nothing stops an operator listing a peer rig that is never brought to life;
  the first mint refuses and the hub asks. That is the intended failure.
