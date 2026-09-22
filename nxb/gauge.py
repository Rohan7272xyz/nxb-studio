"""How full is a pane's context? Read from the runtime's own transcript. [nxb-082]

WHY A GAUGE. nxb-079 gave every pane a ceiling, and the runtime compacts
when it is reached: an opaque summary, written by the vendor's prompt, that
the operator never sees and the worker cannot be asked about. nxb-082
checkpoints INSTEAD: a pane near its ceiling writes a bounded note to the
vault and is reset onto it. For that, something has to know how full a
pane is, and both runtimes already write it to disk after every request.

  claude_code   ~/.claude/projects/<cwd slug>/<session id>.jsonl
                each assistant message carries `usage`; the context is
                input + cache_read + cache_creation of the LAST one.
  codex         ~/.codex/sessions/<y>/<m>/<d>/rollout-*-<thread id>.jsonl
                each `token_count` event carries `last_token_usage`; the
                context is its `input_tokens`, and `model_context_window`
                names the window (258,400 on gpt-6-astra, measured).

READ FROM THE TAIL. A Codex rollout on the Pact programme reached 141 MB. The
last record is at the end, so this seeks to the last 256 KB and parses
backwards; a gauge that read whole files would be its own kind of outage.
Costs no tokens.
"""

import glob
import json
import os

TAIL_BYTES = 256 * 1024


def _tail(path, size=TAIL_BYTES):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            handle.seek(max(0, end - size))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _claude_transcript(session_id):
    hits = glob.glob(os.path.expanduser(
        f"~/.claude/projects/*/{session_id}.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def _codex_rollout(thread_id):
    hits = glob.glob(os.path.expanduser(
        f"~/.codex/sessions/*/*/*/rollout-*{thread_id}.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def _live_claude_session(entry):
    """(session id, transcript path) for a Claude pane, by NEWEST transcript.

    TWO RECORDS CAN NAME A PANE'S SESSION and either can be the stale one.
    The rig's own record is written the moment a reset types `/clear`; the
    session registry is written by the runtime a moment later. MEASURED
    2026-09-12 (RIG-33) the registry was the fresher of the two, and
    measured 2026-09-13 11:42 AM the rig record was, one minute after two
    builders were cleared. Preferring either by rule is wrong half the
    time, so this prefers the one whose transcript was written last, which
    is the live session by definition. The registry is read by PANE ID
    first: that key cannot collide across two rigs and is right during the
    seconds before a rename lands. [RIG-41]
    """
    from nxb.roster import session_registry_ids, session_registry_panes
    sid = entry.get("session_id")
    live = None
    if entry.get("pane") or entry.get("name"):
        live = session_registry_panes().get(entry.get("pane"))
        if not live and entry.get("name"):
            live = session_registry_ids().get(entry["name"])
    best, best_path, best_at = None, None, -1.0
    for candidate in (sid, live):
        if not candidate:
            continue
        path = _claude_transcript(candidate)
        if not path:
            continue
        at = os.path.getmtime(path)
        if at > best_at:
            best, best_path, best_at = candidate, path, at
    if best and best != sid:
        entry["session_id"] = best
    if best:
        return best, best_path
    # No transcript under either id. The registry's claim still tells us a
    # runtime is up on this pane; the rig's own record alone does not.
    if live:
        entry["session_id"] = live
    return live, None


def pane_context(entry):
    """{tokens, window, at, path} for a rig pane entry, or a reason it is
    unknown. `tokens` is the context the pane's LAST request carried."""
    runtime = entry.get("runtime")
    if runtime == "claude_code":
        sid, path = _live_claude_session(entry)
        if not path:
            # Nothing on disk under either id: the pane's runtime has not
            # written a byte. Only the registry can say whether that is a
            # session that has just started or a pane we have lost.
            if sid:
                return {"tokens": 0, "at": None, "path": None,
                        "session_id": sid, "fresh": True, "asked": False,
                        "reason": "launched, no request yet"}
            return {"tokens": None, "reason": "no transcript for this "
                                              "session id yet"}
        last, turns = None, False
        for line in _tail(path).splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("type") in ("user", "assistant"):
                turns = True
            if record.get("type") != "assistant":
                continue
            usage = (record.get("message") or {}).get("usage")
            if isinstance(usage, dict):
                tokens = ((usage.get("input_tokens") or 0)
                          + (usage.get("cache_read_input_tokens") or 0)
                          + (usage.get("cache_creation_input_tokens") or 0))
                if tokens:
                    last = {"tokens": tokens,
                            "at": record.get("timestamp"), "path": path}
        if last:
            last["session_id"] = sid
            return last
        # A CLEARED PANE HAS A TRANSCRIPT AND NO CONVERSATION. MEASURED
        # 2026-09-13 11:44 AM on pact-dev: `/clear` writes the file
        # immediately with `custom-title`, `agent-name`, `mode` and
        # `bridge-session` records and nothing else, so "the file does not
        # exist" is the wrong test for a fresh session and both builders
        # read "?" the minute after they were cleared. A transcript small
        # enough that the tail IS the whole file, holding no user or
        # assistant turn, is a session that has never been asked anything:
        # zero, not unknown. [RIG-41]
        try:
            whole = os.path.getsize(path) <= TAIL_BYTES
        except OSError:
            whole = False
        if whole:
            # No ANSWERED request in a file the tail read whole. Either the
            # pane was just cleared, or its first turn is still in flight;
            # both hold at most one prompt, which is nearer to zero than to
            # unknown, and neither is the lost pane "?" is reserved for.
            return {"tokens": 0, "at": None, "path": path,
                    "session_id": sid, "fresh": True, "asked": turns,
                    "reason": ("first request in flight" if turns
                               else "cleared, no request yet")}
        return {"tokens": None, "reason": "no usage record in the "
                                          "transcript tail"}
    if runtime == "codex":
        tid = entry.get("thread_id")
        path = _codex_rollout(tid) if tid else None
        if not path:
            return {"tokens": None, "reason": "no rollout for this thread "
                                              "id yet"}
        last = None
        for line in _tail(path).splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") or {}
            if record.get("type") != "event_msg" or \
                    payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            usage = info.get("last_token_usage") or {}
            tokens = usage.get("input_tokens") or 0
            if tokens:
                last = {"tokens": tokens,
                        "window": info.get("model_context_window"),
                        "at": record.get("timestamp"), "path": path}
        return last or {"tokens": None, "reason": "no token_count in the "
                                                  "rollout tail"}
    return {"tokens": None, "reason": f"no gauge for runtime {runtime!r}"}


def fullness(entry, *, default_limit=None):
    """(tokens, limit, fraction). The limit is the pane's own ceiling."""
    reading = pane_context(entry)
    tokens = reading.get("tokens")
    limit = entry.get("context_limit") or default_limit or reading.get("window")
    # `tokens is None` is UNKNOWN; zero is a reading. A fresh pane reports 0
    # and must gauge as 0 percent, not as a hole. [RIG-41]
    if tokens is None or not limit:
        return tokens, limit, None
    return tokens, limit, tokens / float(limit)
