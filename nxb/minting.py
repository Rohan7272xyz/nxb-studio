"""Minting as a FUNCTION, so `mint` and `rig dispatch` share one path.

Until nxb-079 the whole of minting lived inline in the CLI, which meant the
only way to mint from Python was to shell out to the CLI: one more process,
and for an orchestrator one more model round-trip. `rig dispatch` needs to
mint and type in a single command, so the logic moved here unchanged and the
CLI calls it.

ONE OUTSTANDING TASK PER WORKER. [RIG-27]
MEASURED on the Pact programme: after each of two host restarts, the rebuilt
orchestrators re-dispatched work whose original ids were still open, and on a
normal afternoon a lead sent a second directive to a builder mid-task. Both
cost a full task's worth of tokens and both were forbidden by a sentence in the
brief. A sentence in a brief decays; a refusal in `mint` does not. A worker with
an unfiled, unrevoked id is refused a second one unless the caller SUPERSEDES
the old id, which revokes it in the same step so the record says why.
"""

from nxb.keystroke import outstanding_tasks

#: Published refusals. See contract/roster.json.
TASK_WORKER_BUSY = "task_worker_busy"
#: A supersede aimed at a worker whose transcript moved recently. MEASURED
#: 2026-09-12 on pact-dev: an orchestrator superseded a task whose worker had
#: the fix done and the test suite running, because a WAITING looked idle.
#: Killing live work is the most expensive thing a fleet can do. [RIG-35]
TASK_WORKER_ACTIVE = "task_worker_active"
ACTIVE_WITHIN_S = 300


def _worker_activity(ledger, worker, session):
    """(age_s or None, busy or None): the worker's transcript age and screen."""
    from nxb.keystroke import _resolve, last_activity_s
    try:
        pane, _, refusal = _resolve(worker, ledger, session)
    except Exception:                                          # noqa: BLE001
        return None, None
    if refusal is not None or not pane:
        return None, None
    busy = None
    try:
        from nxb.keystroke import busy_screen
        from nxb.rig import capture
        busy = busy_screen(capture(pane["pane"]))
    except Exception:                                          # noqa: BLE001
        pass
    return last_activity_s(pane), busy


def mint_task(ledger, worker, *, session=None, supersede=None, force=False):
    """Issue a task id for `worker`, or return the refusal. (task_id, refusal)."""
    from nxb.keystroke import rig_sessions  # noqa: F401  (kept importable)
    from nxb.rig import RigTmuxError, live_rig_sessions, rig_roster
    from nxb.roster import Roster, discover
    from nxb.tasks import TaskRegistry

    busy = outstanding_tasks(ledger, worker)
    if supersede and busy and not force:
        age, on_screen = _worker_activity(ledger, worker, session)
        if on_screen or (age is not None and age < ACTIVE_WITHIN_S):
            return None, {
                "state": "REFUSED", "reason": TASK_WORKER_ACTIVE,
                "worker": worker, "last_activity_s": age, "busy": on_screen,
                "detail": (f"{worker!r} is ACTIVE on its outstanding task "
                           f"(last model request {age} s ago"
                           f"{', visibly working' if on_screen else ''}); "
                           f"superseding it would throw away live work."),
                "outstanding": busy,
                "remedy": ["collect it with --wait 600 and read the answer",
                           "supersede only a worker whose transcript has "
                           "been still for more than five minutes, or pass "
                           "--force if you have read its pane and know it "
                           "is dead"]}
    if supersede:
        wanted = ([t["task_id"] for t in busy] if supersede == "all"
                  else [supersede])
        held = {t["task_id"] for t in busy}
        missing = [t for t in wanted if t not in held]
        if missing:
            return None, {
                "state": "REFUSED", "reason": TASK_WORKER_BUSY,
                "detail": (f"{', '.join(missing)} is not an outstanding task "
                           f"of {worker!r}, so there is nothing to supersede."),
                "outstanding": busy}
        reg = TaskRegistry(ledger)
        try:
            for tid in wanted:
                reg.revoke(tid)
        finally:
            reg.close()
        busy = outstanding_tasks(ledger, worker)
    if busy:
        return None, {
            "state": "REFUSED", "reason": TASK_WORKER_BUSY,
            "worker": worker,
            "detail": (f"{worker!r} already holds {len(busy)} outstanding "
                       f"task(s) with no reply filed: "
                       f"{', '.join(t['task_id'] for t in busy)}. One "
                       f"directive at a time per worker."),
            "outstanding": busy,
            "remedy": [
                "collect it: python3 -m nxb rig collect --worker "
                f"\"{worker}\" --task-id {busy[0]['task_id']} --wait 600",
                "or, if that task is truly dead, supersede it: add "
                f"--supersede {busy[0]['task_id']} (revokes it first)"]}

    # Both populations: sessions the runtime registry can name, and workers
    # a rig declared. A Codex pane appears only in the second, and is no less
    # declared for it. EVERY LIVE rig recorded next to the ledger counts
    # unless --session narrows it -- RIG-4 was a default session name
    # drifting from the rig actually standing, refused as if the worker were
    # undeclared. rig_sessions() lists every rig ever recorded, including
    # ones torn down hours ago, and a dead rig has no workers to contribute.
    sessions = [session] if session else live_rig_sessions(ledger)
    entries, seen = list(discover().entries), {}
    for s in sessions:
        try:
            found = rig_roster(ledger, s).entries
        except RigTmuxError as exc:
            # Refuse rather than mint against a roster we know is
            # incomplete: a silently short roster is how RIG-4 blamed the
            # operator for a worker that existed.
            return None, {"state": "REFUSED", "reason": "rig_tmux_unavailable",
                          "detail": exc.detail}
        for e in found:
            if e.name == worker:
                seen.setdefault(e.name, []).append(s)
        entries.extend(found)
    # Scenario-built fleets share worker names by design, so with two rigs
    # standing "CC Worker 1" names two different panes. Minting for whichever
    # came first would hand out a ticket that types into someone else's
    # fleet. [RIG-18] UNREACHABLE while RIG-20 holds, and kept on purpose: it
    # fires on a naming REGRESSION rather than on operator behaviour.
    rigs = seen.get(worker, [])
    if len(rigs) > 1:
        return None, {
            "state": "REFUSED", "reason": "roster_ambiguous_worker",
            "detail": (f"{worker!r} exists in {len(rigs)} standing rigs: "
                       f"{', '.join(sorted(rigs))}. Names are supposed to "
                       f"carry their rig (RIG-20), so this means scoped "
                       f"naming has regressed."),
            "remedy": [f"--session {r}" for r in sorted(rigs)]}
    reg = TaskRegistry(ledger)
    try:
        return reg.mint(worker, Roster(entries))
    finally:
        reg.close()
