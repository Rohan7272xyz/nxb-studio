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
"""

import json
import os
import re

from nxb.enroll import MARKER

#: Published refusals. See contract/rig.json.
KEYSTROKE_UNKNOWN_WORKER = "keystroke_unknown_worker"
KEYSTROKE_NO_RIG = "keystroke_no_rig"
KEYSTROKE_AMBIGUOUS_RIG = "keystroke_ambiguous_rig"


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


def done_marker(task_id):
    return DONE_MARKER.format(task_id=task_id)


def marked_directive(task_id, worker, body):
    """The exact text typed into a pane. Always marked; there is no other form.

    The marker leads so a worker can classify the message from its first
    characters, before it has read anything that might try to talk it out of
    classifying at all. It CLOSES with the reply protocol, so every automated
    directive is answerable by the same mechanism that dispatched it.
    """
    if not task_id or not str(task_id).strip():
        raise ValueError("a directive cannot be typed without a task id")
    if not worker or not str(worker).strip():
        raise ValueError("a directive cannot be typed without a worker")
    return (f"{MARKER} task_id={task_id} worker={worker!r} :: "
            f"{' '.join(str(body).split())}"
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


def save_rig(ledger, session, report):
    path = state_path(ledger, session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"session": report["session"],
                   "panes": [{k: p.get(k) for k in
                              # `role` persists so a cleared ORCHESTRATOR is
                              # re-enrolled with the orchestrator brief rather
                              # than silently demoted to a worker. [RIG-7]
                              ("name", "runtime", "role", "pane", "enrolment",
                               "thread_id", "model", "effort")}
                             for p in report["panes"]]}, handle, indent=2)
    return path


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


def collect_reply(worker, task_id, *, ledger, session=None, tail_lines=40,
                  answer_lines=60):
    """Read a worker's answer to ONE directive back off its pane. [RIG-5]

    The counterpart to `send_directive`, and the thing whose absence meant an
    orchestrator could dispatch and never see what came back. Rohan found the
    hole by asking the right question: without this, review is a habit rather
    than a step, and nothing correlates a reply to the task that asked for it.

    THREE STATES, AND THE MIDDLE ONE IS THE HONEST DEFAULT:

      ANSWERED  the done marker for THIS task id is on the pane; the text
                between the dispatch and the marker is returned.
      WAITING   no marker. The worker may still be thinking, or may have
                REFUSED and correctly done nothing else. Both look the same
                from outside, so this never guesses: it returns the pane tail
                and lets the reader see. A refusal is visible in that tail.
      REFUSED   there is no such rig or no such worker (as `send_directive`).

    WAITING costs nothing and is not a failure: collect again. That is what
    keeps any deadline from being load-bearing, which matters because nobody
    has measured how long real work takes here and a number nobody measured is
    exactly what this project keeps deleting.
    """
    from nxb.rig import capture_history

    rig, session, refusal = _resolve(worker, ledger, session)
    if refusal is not None:
        return refusal
    pane = rig["pane"]

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
        return {"state": "WAITING", "worker": worker, "task_id": task_id,
                "pane": pane, "session": session, "dispatch_seen": anchored,
                "detail": ("no done marker for this task id on the pane. The "
                           "worker may still be working, or may have REFUSED "
                           "and correctly done nothing else -- both look "
                           "identical from outside, so read the tail rather "
                           "than assuming. " +
                           ("" if anchored else
                            "The directive itself is not visible either, "
                            "which is NOT evidence it never landed: a Claude "
                            "Code pane scrolls its transcript internally and "
                            "tmux cannot see past it.")),
                "tail": "\n".join(lines[-tail_lines:]).strip()}

    # Everything the worker printed in between, INCLUDING its own `nxb
    # validate` call: that call is the evidence the id check actually ran, so
    # it belongs in the answer rather than being tidied out of it.
    body = after[:end] if anchored else after[max(0, end - answer_lines):end]
    out = {"state": "ANSWERED", "worker": worker, "task_id": task_id,
           "pane": pane, "session": session, "runtime": rig["runtime"],
           # Whether the START of the answer is known, or merely budgeted.
           # The END is always exact: it is this task's own marker.
           "anchored": anchored, "answer": "\n".join(body).strip()}
    if not anchored:
        out["detail"] = (f"the directive scrolled out of the pane, so the "
                         f"answer's end is exact (this task's marker) and its "
                         f"start is the last {answer_lines} lines before it. "
                         f"Read it as approximate at the top.")
    return out


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


def send_directive(worker, task_id, body, *, ledger, session=None):
    """Type a MARKED directive to `worker`. The only dispatch path.

    Takes a task id because there is no such thing as an unmarked directive
    here: omitting it is a TypeError, not a quieter message.

    `session=None` resolves to the ONE rig standing, read from the state files
    next to the ledger and filtered by tmux liveness. One standing rig is
    unambiguous; two refuse as ambiguous rather than guessing. RIG-4: the old
    default assumed a session literally named 'nxb', and when the standing rig
    was 'nxb-s2' the refusal blamed the roster and its remedy would have stood
    up a second rig.
    """
    from nxb.rig import send_line

    pane, session, refusal = _resolve(worker, ledger, session)
    if refusal is not None:
        return refusal
    if not pane.get("enrolment"):
        # Not a refusal to send -- it is the operator's pane and he may type
        # into it -- but nxb will not pretend a rule is enforcing.
        return {"state": "REFUSED", "reason": KEYSTROKE_UNKNOWN_WORKER,
                "detail": f"{worker!r} is not enrolled, so a marked "
                          f"directive would not be validated by it."}
    send_line(pane["pane"], marked_directive(task_id, worker, body))
    return {"state": "TYPED", "worker": worker, "pane": pane["pane"],
            "session": session, "task_id": task_id,
            "runtime": pane["runtime"], "marker": MARKER,
            "collect_with": (f"python3 -m nxb rig collect --worker "
                             f"{worker!r} --task-id {task_id}")}
