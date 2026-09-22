"""Typing as the transport. The ONLY way nxb delivers a directive.

Rohan's design call, and it is structural rather than a convenience.

WHY THIS REPLACES THE VENDOR CHANNELS
-------------------------------------
Each runtime has its own IPC -- a socket for Claude, `codex queue` for Codex --
and they behave differently: one holds a non-session sender for approval, the
other delivers with no approval at all. Building on both meant inheriting the
difference and then patching it, forever.

Typing is the same channel on both. So nxb stops using the vendor channels for
dispatch and types instead, and the asymmetry does not need patching because it
is no longer in the path.

REACHABILITY STOPS BEING AUTHORISATION
--------------------------------------
`codex queue` still exists and anyone may call it; so does a bare message to a
Claude pane. Neither is gated, and neither needs to be, because anything
arriving that way is UNMARKED -- which the worker's rule defines as the
operator talking. The question stops being "who could reach this pane" and
becomes "is this marked, and does its id validate".

THE MARKER CANNOT BE OMITTED
----------------------------
There is exactly one function here that types a directive, it takes a task id
as a required argument, and it builds the payload through `marked_directive`,
which has no branch that omits the marker. There is no flag to send raw text.
A test asserts all of that, because a convention the code merely follows is the
thing this project has watched erode.

WHAT THIS IS NOT
----------------
It is not authentication. The marker is not secret and not signed; anything on
this machine could type one, and anything that can type is the operator as far
as the rule is concerned. The security rests entirely on the task id
validation, which is itself a model following its own rule. Drift control, not
a wall. [ENFORCE-1, RIG-2]

THE CONTEXT BUDGET [RIG-24, RIG-25, nxb-079]
--------------------------------------------
MEASURED on the 25-pane Pact programme, 2026-09-07 to 09-10: 11,779 Codex
requests carried 1.48 BILLION input tokens, and every request re-sends the
pane's whole context. Sixty-eight orchestrator turns that polled `rig collect`
in a loop accounted for 5,047 of those requests and 633M tokens, 43 percent of
everything the fleet spent. So two things here are load-bearing for cost:

  * `collect` can WAIT inside itself (`wait=`), so one command replaces a
    polling loop of twenty to ninety model round-trips.
  * `send` starts a worker on a FRESH context by default (`fresh=True`): the
    filed reply and the repository carry the state, the pane's memory does
    not have to. A worker that keeps 200K of context re-sends it on every
    one of its next few hundred requests.

A WAITING payload is deliberately small for the same reason: every byte of it
lands in the orchestrator's context and stays there until compaction.
"""

import json
import os
import re
import time

from nxb.enroll import MARKER

#: Published refusals. See contract/rig.json.
KEYSTROKE_UNKNOWN_WORKER = "keystroke_unknown_worker"
KEYSTROKE_NO_RIG = "keystroke_no_rig"
KEYSTROKE_AMBIGUOUS_RIG = "keystroke_ambiguous_rig"
#: A fresh-context send to a worker that still holds an unfiled task. Clearing
#: that pane would destroy work in flight, so the send refuses instead. [RIG-27]
KEYSTROKE_WORKER_BUSY = "keystroke_worker_busy"


#: What a worker prints when it has finished an automated directive. It CARRIES
#: THE TASK ID, which is the whole point: a reply on a screen is otherwise
#: uncorrelated to the directive that asked for it, and an orchestrator reading
#: the wrong answer off a stale screen would never know. [RIG-5]
DONE_MARKER = "[NXB-DONE {task_id}]"

#: The reply protocol, appended to every automated directive.
#:
#: It travels with the DIRECTIVE rather than living in the enrolment rule, and
#: that is deliberate. A rule bound at launch cannot be added to a pane that is
#: already standing without restarting it, and Rohan's panes hold his work. It
#: also degrades correctly: a Codex pane whose typed rule has decayed (RIG-3)
#: still gets the protocol, because it arrives in the same message as the task.
_REPLY_PROTOCOL = (
    " When you have finished, state your answer, and then print as the very "
    "last line exactly: {done}. Print that line only when you are actually "
    "done; {tail}"
)

#: FILING. [RIG-21]
#:
#: The collector reads a pane's SCREEN, and a Claude Code pane scrolls its
#: transcript internally, so a long answer, or one followed by more output,
#: is cut to a line budget or lost outright. An answer FILED next to the
#: ledger is read first and whole. Present only when the dispatcher knows its
#: ledger and repo, which `send_directive` always does; an unfiled answer
#: still collects off the screen as before, so this degrades, never gates.
#:
#: The filed copy IS the answer, so the worker is told not to print the report
#: a second time: a 78 KB report echoed into a pane is 78 KB the orchestrator's
#: collect may scrape into its own context. [RIG-24]
_FILING_PROTOCOL = (
    " Before you finish, FILE your full answer so it can be collected even "
    "after this pane scrolls, by running exactly: PYTHONPATH={repo} python3 "
    "-m nxb rig reply --worker \"{worker}\" --task-id {task_id} --file <path "
    "to a file containing your answer> --ledger {ledger} (a short answer may "
    "use --message \"<answer>\" instead). BEGIN the filed answer with one "
    "paragraph headed SUMMARY: of at most 800 characters stating the "
    "outcome, the verdict and anything the orchestrator must act on; that "
    "paragraph is what your orchestrator reads, the rest is read only on "
    "demand. The filed copy IS your answer: after filing, print at most "
    "three lines of summary, never the whole report again."
)

#: Above this many characters, `collect` hands the orchestrator the worker's
#: SUMMARY and the report's path instead of the whole answer. [RIG-29]
#:
#: MEASURED on the Pact programme: 250 filed replies, 6.3M tokens, median 16K
#: characters, the largest 3 MB, and every one went whole into a long-lived
#: orchestrator context and stayed there until compaction. Six thousand
#: characters is about 1.5K tokens: a real summary, not a headline.
ANSWER_INLINE_CHARS = 6_000

#: The last words of the directive, and therefore THE BOUNDARY between what
#: nxb typed and what the worker said.
#:
#: MEASURED, first live collect, 2026-09-03: without this the collector
#: returned ANSWERED with the echoed directive as the "answer". The directive
#: has to NAME the done marker in order to ask for it, so the marker is on the
#: screen from the moment the directive lands, and a search of the whole pane
#: finds that copy. A FALSE GREEN in the collector, which is the exact defect
#: class this project exists to catch, produced by the reply protocol talking
#: about itself.
#:
#: The marker mention sits BEFORE this tail inside the protocol, so anything
#: after the tail's last occurrence is the worker speaking and nothing else.
_PROTOCOL_TAIL = "it is how your answer is collected."

#: The phrase that identifies the directive's OWN copy of the done marker.
#:
#: The boundary above is the strong anchor and it is not always there. MEASURED
#: 2026-09-03 on a live Claude Code pane: its TUI scrolls INTERNALLY, so once
#: the app redraws, an earlier message is gone from tmux's scrollback entirely
#: -- `capture-pane -S -3000` returned 38 lines containing the launch command
#: and the worker's reply, and no trace of the directive between them. Codex
#: keeps its transcript in the terminal's own scrollback and does not lose it.
#: Another runtime asymmetry, and one that would have made collect useless on
#: exactly half the fleet.
#:
#: So when the boundary is absent, the marker alone must be trusted -- minus
#: the one copy that is part of the request for it, which this phrase finds.
_INSTRUCTION_PHRASE = "print as the very last line exactly"

#: What a runtime shows while its model is mid-turn. Read by `collect` so a
#: WAITING result can say whether the worker is visibly working, and by
#: `nudge` so nothing is typed into a pane that is busy. Both runtimes use the
#: same phrase on 2026-09 builds; `audit.py` on the Pact programme matched it
#: for three days without a false reading.
BUSY_MARKERS = ("esc to interrupt", "Esc to interrupt")
#: A NARROW PANE TRUNCATES THE FOOTER. MEASURED 2026-09-13 (pact-dev): a
#: 53-column Builder pane showed "bypass permissions on · 1 shell · esc to
#: inte…" ten minutes into an xcodebuild run, the marker never matched, and
#: the pane read idle to collect, to the reset, and to the watcher. The
#: spinner line ("✳ Seasoning… (17m 10s · ↓ 14.1k tokens)") is on screen
#: whenever the turn is running and survives any width; the idle line reads
#: "Worked for 14s · done 11:27 PM" and has no timer in parentheses. [RIG-37]
_SPINNER = re.compile(r"…\s*\((?:\d+h )?(?:\d+m )?\d+s")


def busy_screen(screen):
    """True when a Claude or Codex pane is visibly mid-turn."""
    text = screen or ""
    if any(m in text for m in BUSY_MARKERS):
        return True
    if "esc to int" in text:          # the footer, cut by the pane width
        return True
    # A QUEUED OR PASTED MESSAGE MEANS A TURN IS ABOUT TO RUN. MEASURED
    # 2026-09-13 12:55 AM: a reset typed /clear into a pane whose composer
    # held a queued request; the clear and the continuation queued behind
    # it and the pane ran its old context on. [RIG-39]
    if "edit queued messages" in text or "[Pasted text #" in text:
        return True
    return bool(_SPINNER.search(text))

#: A WAITING payload's tail is a few lines and a few hundred bytes. The old
#: 40-line tail was 1 to 4 KB per poll, and the Pact Director polled 704
#: times: several hundred kilobytes of pane scrapings living in the one
#: context that most needed to stay small. [RIG-24]
WAITING_TAIL_LINES = 8
WAITING_TAIL_CHARS = 700

#: Backoff inside a waiting collect. Starts quick so a fast answer is seen
#: fast; caps low enough that a filed reply is never missed by more than the
#: cap. Every iteration is a file stat and one tmux capture: no model turn.
_WAIT_POLL_MIN_S = 2.0
_WAIT_POLL_MAX_S = 15.0


def done_marker(task_id):
    return DONE_MARKER.format(task_id=task_id)


def marked_directive(task_id, worker, body, *, ledger=None, repo=None,
                     orientation=None):
    """The exact text typed into a pane. Always marked; there is no other form.

    The marker leads so a worker can classify the message from its first
    characters, before it has read anything that might try to talk it out of
    classifying at all. It CLOSES with the reply protocol, so every automated
    directive is answerable by the same mechanism that dispatched it.

    `orientation` is the one sentence that points a fresh worker at its
    rig's state note [RIG-30]; it sits between the body and the protocols
    so the collector's boundary stays the last words.
    """
    if not task_id or not str(task_id).strip():
        raise ValueError("a directive cannot be typed without a task id")
    if not worker or not str(worker).strip():
        raise ValueError("a directive cannot be typed without a worker")
    filing = (_FILING_PROTOCOL.format(repo=repo, worker=worker,
                                      task_id=task_id, ledger=ledger)
              if ledger and repo else "")
    orient = (" " + " ".join(str(orientation).split())) if orientation else ""
    return (f"{MARKER} task_id={task_id} worker={worker!r} :: "
            f"{' '.join(str(body).split())}"
            + orient
            + filing
            + _REPLY_PROTOCOL.format(done=done_marker(task_id),
                                     tail=_PROTOCOL_TAIL))


def state_path(ledger, session):
    """Where the rig records which pane holds which worker."""
    return os.path.join(os.path.dirname(ledger), f"rig-{session}.json")


def load_rig(ledger, session):
    try:
        with open(state_path(ledger, session), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def rig_sessions(ledger):
    """Every rig session with state recorded next to this ledger.

    RIG-4 exists because a session NAME was assumed instead of read: the
    default said 'nxb', the standing rig was 'nxb-s2', and the refusal blamed
    the roster. The state files already know every rig this ledger has stood
    up, so nothing needs to assume. A state file is a record, not a live rig:
    tear_down does not delete it, so liveness stays tmux's to answer.
    """
    import glob

    sessions = []
    for path in sorted(glob.glob(
            os.path.join(os.path.dirname(ledger), "rig-*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            continue                    # a half-written record names no rig
        if isinstance(state, dict) and state.get("session"):
            sessions.append(state["session"])
    return sessions


#: Per-pane fields the rig record keeps. `role` persists so a cleared
#: ORCHESTRATOR is re-enrolled with the orchestrator brief rather than silently
#: demoted to a worker [RIG-7]; `instructions` so a reset re-types the role;
#: `session_id` and `thread_id` so a rig that went down with the machine can be
#: RESUMED on its original conversations instead of rebuilt from nothing
#: [RIG-26]; `dir` and `context_limit` so the resumed launch line is the
#: original one.
PANE_RECORD_KEYS = ("name", "runtime", "role", "pane", "enrolment",
                    "thread_id", "session_id", "model", "effort",
                    "context_limit", "tools", "dir", "instructions",
                    "role_binding",
                    "state", "reason", "trust_scope", "launched_at",
                    "resumed_at", "last_nudge_at", "last_checkpoint_at",
                    "checkpoint_task", "checkpoints",
                    "checkpoint_requested_at", "reset_unproven_at")

#: Rig-level fields, for the same reason: `resume` rebuilds the tmux session
#: the way `stand_up` built it.
RIG_RECORD_KEYS = ("work_dir", "layout", "width", "height", "repo",
                   "launched_at", "resumed_at")


def save_rig(ledger, session, report):
    path = state_path(ledger, session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {"session": report["session"],
              # Which rigs this one's orchestrator may dispatch to, so a
              # /clear re-brief carries the same federation. [RIG-21]
              "peers": list(report.get("peers") or [])}
    for key in RIG_RECORD_KEYS:
        if report.get(key) is not None:
            record[key] = report[key]
    record["panes"] = [{k: p.get(k) for k in PANE_RECORD_KEYS
                        if k in p or k in ("name", "runtime", "role", "pane",
                                           "enrolment", "thread_id", "model",
                                           "effort", "state", "reason",
                                           "trust_scope")}
                       for p in report["panes"]]
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    os.replace(tmp, path)
    return path


def reply_path(ledger, task_id):
    """Where a worker FILES its answer: next to the ledger, by task id. [RIG-21]"""
    safe = "".join(c if c.isalnum() or c in "-_." else "-"
                   for c in str(task_id))
    return os.path.join(os.path.dirname(ledger), "replies", f"{safe}.json")


def read_reply(ledger, task_id):
    """The filed answer for `task_id`, or None. Reading consumes nothing."""
    try:
        with open(reply_path(ledger, task_id), encoding="utf-8") as handle:
            filed = json.load(handle)
    except (OSError, ValueError):
        return None
    return filed if isinstance(filed, dict) else None


def _write_reply(ledger, record):
    path = reply_path(ledger, record["task_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    os.replace(tmp, path)
    return path


def file_reply(worker, task_id, answer, *, ledger):
    """File `worker`'s answer to `task_id` where `collect_reply` reads FIRST.

    The id is validated the way the worker validated the directive, with the
    registry's own verdict: an answer filed under an id minted for someone
    else is refused, so a reply cannot land in another worker's task through
    a typo any more than a directive can be accepted through one.
    """
    import datetime
    from nxb.tasks import TaskRegistry
    reg = TaskRegistry(ledger)
    try:
        verdict = reg.validate(task_id, worker)
    finally:
        reg.close()
    if not verdict.get("valid"):
        return {"state": "REFUSED", "worker": worker, "task_id": task_id,
                "verdict": verdict.get("verdict"),
                "detail": verdict.get("detail")}
    record = {"task_id": task_id, "worker": worker, "answer": str(answer),
              "source": "outbox",
              "filed_at": datetime.datetime.now(
                  datetime.timezone.utc).isoformat()}
    path = _write_reply(ledger, record)
    return {"state": "FILED", "worker": worker, "task_id": task_id,
            "path": path, "chars": len(record["answer"])}


def outstanding_tasks(ledger, worker=None):
    """Issued, unrevoked task ids with no reply on file, newest first.

    THE DEFINITION OF "BUSY". An id is outstanding from the moment it is
    minted until an answer is filed for it (by the worker, or by a collect
    that read one off the pane) or it is revoked. `mint` refuses a second id
    for a worker that has one outstanding, and a fresh-context `send`
    refuses to clear such a worker's pane. [RIG-27]

    Read-only, and tolerant of a ledger that does not exist yet or has never
    minted: both answer "nothing outstanding", which is true.
    """
    import sqlite3
    if not ledger or not os.path.isfile(ledger):
        return []
    try:
        conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        try:
            rows = conn.execute(
                "SELECT task_id, worker_name, issued_at FROM issued_tasks "
                "WHERE revoked_at IS NULL"
                + (" AND worker_name = ?" if worker else "")
                + " ORDER BY issued_at DESC",
                (worker,) if worker else ()).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    return [{"task_id": t, "worker": w, "issued_at": at}
            for t, w, at in rows if read_reply(ledger, t) is None]


def _wrapped_index(lines, needle, *, span=4):
    """Index of the LAST line where `needle` completes, or None.

    Matched against a whitespace-stripped join of a sliding window, because
    Codex hard-wraps its own output to the pane width and tmux's -J does not
    rejoin that: in a narrow worker pane a marker straddles a newline. The
    rename parser learned this the expensive way, presenting as flakiness
    because the id parsed in the wide top pane and failed in every pane below.
    """
    wanted = re.sub(r"\s+", "", needle)
    for i in range(len(lines) - 1, -1, -1):
        if wanted in re.sub(r"\s+", "", "".join(lines[i:i + span])):
            return i
    return None


def _wrapped_index_excluding(lines, needle, exclude, *, span=4):
    """Last index where `needle` completes in a window NOT containing `exclude`.

    The directive's own copy of the done marker sits inside the sentence that
    requests it, so that sentence is the discriminator. Without this, a pane
    showing only an echoed directive reports ANSWERED -- measured, and it was
    the collector's first live result.
    """
    skip = re.sub(r"\s+", "", exclude)
    wanted = re.sub(r"\s+", "", needle)
    for i in range(len(lines) - 1, -1, -1):
        window = re.sub(r"\s+", "", "".join(lines[i:i + span]))
        if wanted in window and skip not in window:
            return i
    return None


def last_activity_s(entry):
    """Seconds since the pane's transcript last recorded a model request,
    or None when there is no transcript. Read from disk; costs nothing."""
    import datetime
    from nxb.gauge import pane_context
    reading = pane_context(dict(entry))
    stamp = reading.get("at")
    if not stamp:
        return None
    try:
        then = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=datetime.timezone.utc)
    return int((datetime.datetime.now(datetime.timezone.utc) - then)
               .total_seconds())


def _slim_tail(lines, tail_lines, tail_chars):
    tail = "\n".join(lines[-tail_lines:]).strip()
    if len(tail) > tail_chars:
        tail = "…" + tail[-tail_chars:]
    return tail


def _deliver(out, *, ledger, full):
    """Shape an ANSWERED result for the orchestrator's context. [RIG-29]

    A short answer goes inline, whole. A long one is filed in the context
    store as a report (plus a task card and a log line) and the result
    carries the worker's SUMMARY and the report's path; `full=True` returns
    the whole text deliberately. Only when the ledger is real, so a mocked
    collect writes nothing.
    """
    answer = out.get("answer", "")
    out["answer_chars"] = len(answer)
    if full or len(answer) <= ANSWER_INLINE_CHARS or not (
            ledger and os.path.isfile(ledger)):
        out["answer_inline"] = True
        return out
    from nxb.context import record_report
    rec = record_report(ledger, task_id=out["task_id"], worker=out["worker"],
                        answer=answer, session=out.get("session"))
    out.update(answer=rec["summary"], answer_inline=False,
               answer_path=rec["path"], report_key=rec["key"],
               summary_source=rec["summary_source"],
               took_min=rec.get("took_min"),
               checkpoints=rec.get("checkpoints", 0),
               full_with=(f"python3 -m nxb rig collect --worker "
                          f"{out['worker']!r} --task-id {out['task_id']} "
                          f"--full"),
               detail=(f"the answer is {len(answer)} characters, so this "
                       f"carries the worker's summary and the report's "
                       f"path. Read the path only if the summary is not "
                       f"enough; everything you read stays in your "
                       f"context."))
    return out


def _collect_once(worker, task_id, rig, session, *, ledger, tail_lines,
                  answer_lines, full=False):
    """One read of the outbox and the pane. Never sleeps. [RIG-5, RIG-21]"""
    from nxb.rig import capture_history

    pane = rig["pane"]

    # A FILED answer is read first, and whole: it is the one form of reply
    # that neither a scrolling TUI nor a line budget can cut. [RIG-21]
    filed = read_reply(ledger, task_id)
    if filed is not None and filed.get("worker") == worker:
        out = {"state": "ANSWERED", "worker": worker, "task_id": task_id,
               "pane": pane, "session": session, "runtime": rig["runtime"],
               "anchored": bool(filed.get("anchored", True)),
               "source": filed.get("source") or "outbox",
               "answer": str(filed.get("answer", "")).strip()}
        if filed.get("filed_at"):
            out["filed_at"] = filed["filed_at"]
        if filed.get("collected_at"):
            out["collected_at"] = filed["collected_at"]
        return _deliver(out, ledger=ledger, full=full)

    lines = capture_history(pane).splitlines()

    # THE ORDER MATTERS. Find where the directive ENDS first, and only then
    # look for the done marker after it. Searching the whole pane finds the
    # marker inside the directive's own request for it and reports the echoed
    # directive as the answer, which is a false green [RIG-5, measured].
    marker = done_marker(task_id)
    start = _wrapped_index(lines, _PROTOCOL_TAIL)
    if start is not None:
        after, end = lines[start + 1:], None
        end = _wrapped_index(lines[start + 1:], marker)
        anchored = True
    else:
        # The boundary scrolled away inside the runtime's own viewport. Fall
        # back to the marker alone, skipping the copy that lives inside the
        # request for it -- which is what produced the collector's first false
        # green. The answer's START is then unknown, so it is bounded by a
        # line budget and reported as approximate rather than silently guessed.
        after, anchored = lines, False
        end = _wrapped_index_excluding(lines, marker, _INSTRUCTION_PHRASE)
    if end is None:
        screen = "\n".join(lines[-40:])
        busy = busy_screen(screen)
        # THE TRANSCRIPT IS THE LIVENESS SIGNAL, NOT THE SCREEN. MEASURED
        # 2026-09-12 on pact-dev: a WAITING with busy=false and the
        # directive scrolled away read as "session lost" to an orchestrator,
        # which superseded a task whose worker had the fix done and the
        # test suite running. The age of the worker's last request is on
        # disk; it goes in the payload so "lost" is checkable. [RIG-35]
        age = last_activity_s(rig)
        return {"state": "WAITING", "worker": worker, "task_id": task_id,
                "pane": pane, "session": session, "dispatch_seen": anchored,
                "busy": busy, "last_activity_s": age,
                "detail": ("no done marker for this task yet"
                           + (f"; the worker's last model request was "
                              f"{age} s ago" if age is not None else "")
                           + (", visibly working" if busy else "")
                           + ("" if anchored else
                              "; the directive is not on screen, which on a "
                              "Claude pane is normal scrolling, not evidence "
                              "it never landed")
                           + ". A worker whose transcript moved in the last "
                              "few minutes is WORKING: collect again, never "
                              "supersede."),
                "tail": _slim_tail(lines, tail_lines, WAITING_TAIL_CHARS)}

    # Everything the worker printed in between, INCLUDING its own `nxb
    # validate` call: that call is the evidence the id check actually ran, so
    # it belongs in the answer rather than being tidied out of it.
    body = after[:end] if anchored else after[max(0, end - answer_lines):end]
    out = {"state": "ANSWERED", "worker": worker, "task_id": task_id,
           "pane": pane, "session": session, "runtime": rig["runtime"],
           # Whether the START of the answer is known, or merely budgeted.
           # The END is always exact: it is this task's own marker.
           "anchored": anchored, "source": "pane",
           "answer": "\n".join(body).strip()}
    if not anchored:
        out["detail"] = (f"the directive scrolled out of the pane, so the "
                         f"answer's end is exact (this task's marker) and its "
                         f"start is the last {answer_lines} lines before it. "
                         f"Read it as approximate at the top.")
    # RECORD THE COLLECTION. An answer read off a screen is as final as one
    # filed, and until it is on disk the task counts as outstanding forever:
    # `mint` would refuse the worker's next task on the strength of a reply
    # that was already read. Only when the ledger is real, so a mocked collect
    # in a test cannot leave a record that changes the next run. [RIG-27]
    if ledger and os.path.isfile(ledger):
        import datetime
        _write_reply(ledger, {
            "task_id": task_id, "worker": worker, "answer": out["answer"],
            "source": "pane", "anchored": anchored,
            "collected_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat()})
    return _deliver(out, ledger=ledger, full=full)


def collect_reply(worker, task_id, *, ledger, session=None,
                  tail_lines=WAITING_TAIL_LINES, answer_lines=60, wait=0.0,
                  full=False):
    """Read a worker's answer to ONE directive back off its pane. [RIG-5]

    The counterpart to `send_directive`, and the thing whose absence meant an
    orchestrator could dispatch and never see what came back. Rohan found the
    hole by asking the right question: without this, review is a habit rather
    than a step, and nothing correlates a reply to the task that asked for it.

    THREE STATES, AND THE MIDDLE ONE IS THE HONEST DEFAULT:

      ANSWERED  the done marker for THIS task id is on the pane, or an answer
                is filed; the text is returned.
      WAITING   no marker. The worker may still be thinking, or may have
                REFUSED and correctly done nothing else. Both look the same
                from outside, so this never guesses: it returns a short pane
                tail and lets the reader see. A refusal is visible in that tail.
      REFUSED   there is no such rig or no such worker (as `send_directive`).

    `wait` is the seconds this call may spend WAITING INSIDE ITSELF before it
    returns. That is the whole cost fix [RIG-24]: a model that runs
    `collect --wait 600` spends one round-trip per ten minutes of waiting,
    where a model that runs `collect` every few seconds spends one round-trip
    per few seconds, and each round-trip re-sends its entire context. The
    loop below is a file stat and a tmux capture; no model is consulted.
    WAITING at the end of the budget still costs nothing and is not a
    failure: collect again.
    """
    rig, session, refusal = _resolve(worker, ledger, session)
    if refusal is not None:
        return refusal
    started = time.monotonic()
    deadline = started + max(0.0, float(wait or 0))
    delay = _WAIT_POLL_MIN_S
    while True:
        out = _collect_once(worker, task_id, rig, session, ledger=ledger,
                            tail_lines=tail_lines, answer_lines=answer_lines,
                            full=full)
        remaining = deadline - time.monotonic()
        if out["state"] != "WAITING" or remaining <= 0:
            if wait:
                out["waited_s"] = round(time.monotonic() - started, 1)
            return out
        time.sleep(min(delay, remaining))
        delay = min(delay * 1.5, _WAIT_POLL_MAX_S)


def task_workers(ledger, task_ids):
    """{task_id: worker_name} from the ledger, for ids it issued."""
    import sqlite3
    out = {}
    if not ledger or not os.path.isfile(ledger) or not task_ids:
        return out
    try:
        conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        for tid in task_ids:
            try:
                row = conn.execute(
                    "SELECT worker_name FROM issued_tasks WHERE task_id = ?",
                    (tid,)).fetchone()
            except sqlite3.Error:
                row = None
            if row:
                out[tid] = row[0]
    finally:
        conn.close()
    return out


def await_any(task_ids, *, ledger, wait=0.0, session=None,
              tail_lines=4):
    """Wait on SEVERAL outstanding tasks in one call; return when any answers.

    A hub orchestrator with four peer tasks in flight otherwise runs four
    collects per poll. Here it runs one command, and the command does the
    waiting. Every id's worker is read from the ledger, which issued it, so
    the caller names only ids. [RIG-24]
    """
    ids = [t for t in task_ids if t]
    workers = task_workers(ledger, ids)
    unknown = [t for t in ids if t not in workers]
    started = time.monotonic()
    deadline = started + max(0.0, float(wait or 0))
    delay = _WAIT_POLL_MIN_S
    while True:
        answered, waiting, refused = [], [], []
        for tid in ids:
            if tid in unknown:
                continue
            out = collect_reply(workers[tid], tid, ledger=ledger,
                                session=session, tail_lines=tail_lines)
            {"ANSWERED": answered, "WAITING": waiting}.get(
                out["state"], refused).append(out)
        remaining = deadline - time.monotonic()
        if answered or not waiting or remaining <= 0:
            state = ("ANSWERED" if answered else
                     "WAITING" if waiting else "REFUSED")
            return {"state": state, "answered": answered, "waiting": waiting,
                    "refused": refused,
                    "unknown_task_ids": unknown,
                    "waited_s": round(time.monotonic() - started, 1)}
        time.sleep(min(delay, remaining))
        delay = min(delay * 1.5, _WAIT_POLL_MAX_S)


def _resolve(worker, ledger, session):
    """(pane record, session, refusal). The lookup `send` and `collect` share.

    One resolver, so a directive and its answer can never disagree about which
    pane the worker is: two copies of this would be two things that must agree
    with nothing making them, which is this project's own founding defect.
    """
    from nxb.rig import live_rig_sessions

    if session is None:
        live = live_rig_sessions(ledger)
        # A NAME NOW CARRIES ITS RIG (RIG-20), so with several rigs standing
        # there is nothing to disambiguate: find the one that holds this
        # worker. Refusing to act while two rigs stand was correct only while
        # names could collide.
        if len(live) > 1:
            holders = [s for s in live
                       if any(pane.get("name") == worker
                              for pane in (load_rig(ledger, s) or {})
                              .get("panes", []))]
            if len(holders) == 1:
                session = holders[0]
            elif not holders:
                return None, None, {
                    "state": "REFUSED", "reason": KEYSTROKE_UNKNOWN_WORKER,
                    "detail": (f"no worker named {worker!r} in any standing "
                               f"rig ({', '.join(sorted(live))})."),
                    "roster": sorted(
                        pane["name"] for s in live
                        for pane in (load_rig(ledger, s) or {}).get("panes", [])
                        if pane.get("name"))}
            else:
                return None, None, {
                    "state": "REFUSED", "reason": KEYSTROKE_AMBIGUOUS_RIG,
                    "detail": (f"{worker!r} is in more than one standing rig "
                               f"({', '.join(sorted(holders))}), which means "
                               f"rig-scoped naming has regressed."),
                    "remedy": [f"--session {s}" for s in sorted(holders)]}
        if not live:
            recorded = rig_sessions(ledger)
            return None, None, {
                "state": "REFUSED", "reason": KEYSTROKE_NO_RIG,
                "detail": ("no rig is standing. " +
                           (f"State is recorded for "
                            f"{', '.join(sorted(recorded))}, but no tmux "
                            f"session by that name is running."
                            if recorded else
                            "No rig state is recorded next to this ledger.")),
                "remedy": ["python3 -m nxb rig up --dir <work dir>"]}
        session = live[0]

    rig = load_rig(ledger, session)
    if rig is None:
        live = live_rig_sessions(ledger)
        return None, None, {
            "state": "REFUSED", "reason": KEYSTROKE_NO_RIG,
            "detail": (f"no rig state for session {session!r}." +
                       (f" Rigs that ARE standing: "
                        f"{', '.join(sorted(live))}." if live else "")),
            "remedy": ([f"--session {s}" for s in sorted(live)] or
                       [f"python3 -m nxb rig up --session {session}"])}
    for pane in rig["panes"]:
        if pane["name"] == worker:
            return pane, session, None
    return None, session, {
        "state": "REFUSED", "reason": KEYSTROKE_UNKNOWN_WORKER,
        "detail": f"no worker named {worker!r} in session {session!r}.",
        "roster": [p["name"] for p in rig["panes"]]}


def send_directive(worker, task_id, body, *, ledger, session=None,
                   fresh=True):
    """Type a MARKED directive to `worker`. The only dispatch path.

    Takes a task id because there is no such thing as an unmarked directive
    here: omitting it is a TypeError, not a quieter message.

    `session=None` resolves to the ONE rig standing, read from the state files
    next to the ledger and filtered by tmux liveness. One standing rig is
    unambiguous; two refuse as ambiguous rather than guessing. RIG-4: the old
    default assumed a session literally named 'nxb', and when the standing rig
    was 'nxb-s2' the refusal blamed the roster and its remedy would have stood
    up a second rig.

    `fresh=True` (the default) RESETS THE PANE'S CONTEXT before typing: the
    worker starts this task with its rule, its role and nothing else. Its
    previous task is on disk, in its filed reply and in the repository; the
    pane's memory of it would otherwise ride along on every request of the
    new task at the full per-request price. A worker that still holds an
    unfiled task is REFUSED rather than cleared, because a reset would erase
    work in flight [RIG-25, RIG-27]. `fresh=False` keeps the context, which is
    right for a revision of the task the worker just finished and for little
    else.
    """
    from nxb.rig import reset_pane, send_line

    pane, session, refusal = _resolve(worker, ledger, session)
    if refusal is not None:
        return refusal
    if not pane.get("enrolment"):
        # Not a refusal to send -- it is the operator's pane and he may type
        # into it -- but nxb will not pretend a rule is enforcing.
        return {"state": "REFUSED", "reason": KEYSTROKE_UNKNOWN_WORKER,
                "detail": f"{worker!r} is not enrolled, so a marked "
                          f"directive would not be validated by it."}
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    busy = [t for t in outstanding_tasks(ledger, worker)
            if t["task_id"] != task_id]
    reset = None
    if fresh:
        if busy:
            return {"state": "REFUSED", "reason": KEYSTROKE_WORKER_BUSY,
                    "worker": worker, "task_id": task_id,
                    "outstanding": busy,
                    "detail": (f"{worker!r} still holds "
                               f"{len(busy)} unfiled task(s); a fresh-context "
                               f"send would clear work in flight."),
                    "remedy": [
                        "collect the outstanding task with --wait first",
                        "or send with --keep-context to queue behind it",
                        "or revoke it: python3 -m nxb revoke <task id>"]}
        reset = reset_pane(pane, session=session, ledger=ledger, repo=repo)
        if reset.get("state") == "REFUSED":
            reset["detail"] = ("the pane could not be reset, so the "
                               "directive was NOT typed: " +
                               str(reset.get("detail", "")))
            return reset
    from nxb.context import orientation_line
    record = load_rig(ledger, session) or {}
    orientation = orientation_line(
        ledger, session, pane.get("dir") or record.get("work_dir"))
    send_line(pane["pane"], marked_directive(task_id, worker, body,
                                             ledger=ledger, repo=repo,
                                             orientation=orientation))
    out = {"state": "TYPED", "worker": worker, "pane": pane["pane"],
           "session": session, "task_id": task_id,
           "runtime": pane["runtime"], "marker": MARKER,
           "context": "fresh" if fresh else "kept",
           "collect_with": (f"python3 -m nxb rig collect --worker "
                            f"{worker!r} --task-id {task_id} --wait 600")}
    out["oriented"] = bool(orientation)
    if reset is not None:
        out["reset"] = {k: reset.get(k) for k in
                        ("state", "re_enrolled", "session_id", "detail")
                        if reset.get(k) is not None}
    if busy:
        out["queued_behind"] = [t["task_id"] for t in busy]
    return out


def dispatch(worker, body, *, ledger, session=None, fresh=True,
             supersede=None, force=False):
    """Mint and send in ONE call. [RIG-24]

    Every command an orchestrator runs is a model round-trip that re-sends
    its whole context, so two commands where one would do is a cost with no
    return. `mint` and `rig send` remain for anyone who wants the seam.
    """
    from nxb.minting import mint_task

    task_id, refusal = mint_task(ledger, worker, session=session,
                                 supersede=supersede, force=force)
    if refusal is not None:
        return refusal
    out = send_directive(worker, task_id, body, ledger=ledger,
                         session=session, fresh=fresh)
    if out.get("state") != "TYPED":
        # The id was issued and the directive never landed. Revoke it, so the
        # worker is not left "busy" on a task it never received.
        from nxb.tasks import TaskRegistry
        reg = TaskRegistry(ledger)
        try:
            reg.revoke(task_id)
        finally:
            reg.close()
        out["revoked_task_id"] = task_id
        return out
    out["minted"] = True
    return out
