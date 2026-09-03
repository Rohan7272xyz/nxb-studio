# nxb-047: what the pane transport will and will not carry

Worker 2. Measured 2026-08-28 on this Mac. Three throwaway panes, all killed by
handle; one plain-Python broker; one probe run against my own live session.

**The transport is asymmetric, and the direction that works is the opposite of
the one the design assumed.**

| direction | result |
|---|---|
| plain process to live pane | **BLOCKED.** Held for approval; never reaches the model |
| live pane to plain process | **WORKS.** Full content, plus the sender's identity |

## 1. Broker to pane: held, in every configuration tried

A plain Python broker connects to a live pane's socket and writes the same
frame `evidence/nxb-001/broker.py` used. Within 0.17 seconds, every time:

```json
{"type":"control","action":"peer_message_status","status":"held",
 "reason":"Your message is held for the recipient user's approval before it
           reaches their Claude session (permission-mode parity).",
 "from":"uds:/tmp/cc-socks/68953.sock","orig_msg_id":"...","msgV":1}
```

The directive never reaches the model. Four configurations, one outcome:

| # | sender | recipient | result |
|---|---|---|---|
| 1 | plain process, no `from_mode` | `--dangerously-skip-permissions` | held |
| 2 | plain process, `from_mode: "bypassPermissions"` | `--dangerously-skip-permissions` | held |
| 3 | plain process, no `from_mode` | **default mode** | held |
| 4 | plain process (Orchestrator 2's independent run) | a real live session, which confirmed **nothing arrived in its context** | held |

**THE CLAIMED `from_mode` IS IGNORED.** Row 2 is the security-relevant one and
it is the easiest thing here to lose in a summary. A local process asserting
`bypassPermissions` gets exactly the same treatment as one asserting nothing.

**The recipient's own mode is irrelevant.** Row 3 rules out the reading that
this is about matching a bypass recipient. So "permission-mode parity" does not
describe parity: a sender that is not itself a recognised Claude session is held
whatever either side claims. That is a real boundary and it is good news for
GRANT-1, which worried about exactly this.

Row 4 matters because rows 1 to 3 only prove the SENDER is refused. Orchestrator
2 probed its own session and confirmed the recipient half: nothing arrived.

## 2. Pane to broker: works, and carries more than the answer

The reply half could not be tested through a pane, because no directive ever
reached one. So it was tested with a real Claude session as the sender, into a
plain socket listener. The full frame received:

```json
{"msgV":1,"msg_id":"3fa77421-9b07-4eb8-a589-e3458c642232","type":"user",
 "priority":"next","from":"uds:/tmp/cc-socks/4050.sock",
 "message":{"role":"user","content":
   "<cross-session-message from=\"uds:/tmp/cc-socks/4050.sock\"
      hop-chain=\"93709ad2841252430aa3dd56\"
      from-name=\"Worker 2\" from-mode=\"bypass\">
    {\"marker\":\"NXB047-REPLYHALF\",\"task_id\":\"nxb-047\",\"status\":\"COMPLETE\",\"answer\":42}
    </cross-session-message>"}}
```

The payload survived byte-intact. And the envelope carries, asserted by the
transport rather than by the sender:

- **`from-name`** — the pane's display name
- **`from-mode`** — its real permission mode
- **`from`** — a usable return address
- **`msg_id`** and **`hop-chain`** — correlation and provenance

## 3. This dissolves the naming problem, rather than solving it

Roughly an hour went into pid-to-name across two workers: sockets are
`<pid>.sock` and carry no name; `/tmp/cc-socks/` holds corpses (9 of 15 sampled
were dead pids, some a day old); transcripts carry `custom-title` but nothing
links a session id to a pid.

**None of that is needed.** A broker learns a pane's name from the first message
that pane sends it. Discovery is not a directory read and not a broadcast probe;
it is a side effect of any pane speaking once.

Recorded because the effort was real and a successor will otherwise repeat it:
`claude -n NAME` DOES place the name in argv, verified on a spawned pane reading
`claude --dangerously-skip-permissions -n nxb-probe-target`, so pid-to-name is
available read-only for panes launched named. It is simply worse than
`from-name` in every way. Codex has no `--name` equivalent; searched
`codex --help` and `codex exec --help` case-insensitively for name, label and
title, finding only saved-session naming and `-p <profile>`.

## 4. A liveness probe is invisible to the probed pane

Worker 3's roster does a bare connect-and-close against other people's live
sessions and flagged as UNVERIFIED whether the probed pane sees anything.

**It sees nothing.** Tested by probing my own live session three times while
being the probed party, so this is a first-person report rather than an
inference:

```
probe 1: connect+close OK in 0.0001s
probe 2: connect+close OK in 0.0001s
probe 3: connect+close OK in 0.0001s
```

No message, no notification, no interruption arrived in my context.

**And `connect()` cleanly separates the living from the dead**, which is what
makes the roster viable at all:

```
live pane   /tmp/cc-socks/4050.sock   -> accepts in 0.0001s
dead pid    /tmp/cc-socks/10067.sock  -> ConnectionRefusedError: [Errno 61]
```

So a roster built on `connect()` is both accurate and unobtrusive. A roster
built on socket EXISTENCE is neither.

## 5. What this means for the product

The broker cannot be the thing that dispatches. Only a Claude session is a
deliverable sender, so dispatch must be initiated by the orchestrator pane,
while the broker receives, records and refuses.

Rohan ruled on the consequence: **worker-side enforcement.** The broker mints
ids after a roster check, the orchestrator dispatches carrying one, and the
worker validates by asking the broker, which is the direction proven to work,
refusing anything unvalidated. Baked in at launch via `--append-system-prompt`
so it cannot drift mid-session. Worker 3 has it as nxb-049.

## UNVERIFIED

- **Whether a HELD message is releasable by the recipient approving it, and
  whether that approval persists.** Not driveable from a script; needs a human
  at a pane. If it releases and persists, section 1 softens considerably. If it
  does not, the block is absolute. Nobody should assume either.
- **Whether a live pane mid-conversation honours `directive_for()`.** The
  directive shape survives the transport byte-intact, which is measured. Whether
  a standing worker with its own context obeys it is untested, because no
  directive reached a pane. Testable after nxb-049, when directives arrive from
  an orchestrator instead of from the broker.
