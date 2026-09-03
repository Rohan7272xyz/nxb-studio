"""Consume the runtime's own failure announcement.

Both runtimes ANNOUNCE that they are failing, in a machine-readable frame,
within about 0.6 seconds. [M: nxb-022] Nothing consumed it. The canary instead
waited for the ABSENCE of an output file, which is only knowable once the whole
budget has elapsed, so a dead API cost 25.6s to detect a fact the runtime had
volunteered at 0.6s.

Absence of a positive is a slow signal by construction: you cannot know a thing
is missing until you stop waiting. Presence of a negative is fast. This module
reads the negatives.

## What is matched, and how structural each one is

**Codex** emits, at top level, `{"type": "error", "message": "..."}`. We key on
`type == "error"` and read no prose at all. The message is
"Reconnecting... waiting for network (Connection failed: error sending
request)" in the measured outage [evidence/nxb-022/stdout-broken.jsonl], and we
carry it as opaque detail for the operator without matching on it.

The one distinction that matters, and it is structural rather than textual:
a top-level `error` is fatal, while a NON-fatal warning arrives as
`{"type": "item.completed", "item": {"type": "error", ...}}`. Both are visible
in evidence/nxb-002-codex/spawn-failed-badmodel.jsonl, where the "Model
metadata not found" warning is an `item.completed` and the 400 that actually
killed the turn is a top-level `error`. Keying on the top-level `type` therefore
distinguishes them without inspecting a single character of message text.

**Claude Code** emits `{"type": "system", "subtype": "api_retry", "attempt": N,
"max_retries": M, ...}` [evidence/nxb-022/cc-broken.jsonl]. Two documented
fields compared by equality; `attempt` and `max_retries` are carried as detail.

**No substring matching anywhere in this file.** A brittle prose match that
silently stops matching after a runtime update is a false green of exactly the
kind this project keeps finding, so there is nothing here to silently stop
matching except the field names themselves.

## What breaks it, stated so the next reader does not have to guess

- Codex renaming the top-level `error` type, or beginning to emit top-level
  `error` for conditions it recovers from.
- Claude Code renaming `system`/`api_retry`, or moving the retry notice into a
  different envelope.
- Either runtime failing in a way it does not announce at all, which is the
  slow-outage case: an API that accepts the connection and then answers late or
  never looks identical to a hard task, and neither runtime has anything to
  announce. Nothing here helps there. See FAILSIGNAL-SLOW in FINDINGS.json.

## How it fails

**Closed, toward the old behaviour.** If a frame changes shape, `detect`
returns None, no abort fires, and the caller falls back to its deadline. That
is slower, which is what we had before this file existed. It is never a false
pass: this module can only ever cause an earlier DISPROVEN, never a PROVEN.
A detector whose failure mode is "you go back to waiting" is safe to key a
liveness verdict on; one whose failure mode is "you conclude success" is not.
"""

#: Structural rules per runtime. Field equality only, never prose.
_RULES = {
    "codex": lambda e: (
        {"reason": "runtime_announced_error",
         "detail": {"message": e.get("message")}}
        if e.get("type") == "error" else None
    ),
    "claude_code": lambda e: (
        {"reason": "runtime_announced_api_retry",
         "detail": {"attempt": e.get("attempt"),
                    "max_retries": e.get("max_retries"),
                    "error_status": e.get("error_status")}}
        if e.get("type") == "system" and e.get("subtype") == "api_retry"
        else None
    ),
}


def detect(event, *, runtime_id):
    """Return {'reason', 'detail'} if this event announces failure, else None.

    `event` is one already-parsed JSONL frame. Unknown runtimes return None
    rather than raising: a runtime we have not measured has no announcement we
    are entitled to interpret.
    """
    if not isinstance(event, dict):
        return None
    rule = _RULES.get(runtime_id)
    if rule is None:
        return None
    hit = rule(event)
    if hit is None:
        return None
    return {"runtime_id": runtime_id, **hit}


def runtimes_with_a_known_signal():
    """The runtimes whose failure announcement we can actually read."""
    return sorted(_RULES)
