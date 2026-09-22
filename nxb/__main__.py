"""CLI. The dispatch is a CALL that returns the receipt on stdout.

    python -m nxb run --ledger <abs> --runtime <id> --directive <text|@file|->
    python -m nxb pending  --ledger <abs>
    python -m nxb collect  <dispatch_key> --ledger <abs>
    python -m nxb dispatch <envelope.json> --ledger <abs>   # H1 only
    python -m nxb digest   <units.json>
    python -m nxb contract

`run` is the one that returns an answer. Everything else was a reliability
layer with nothing in front of it [nxb-030, nxb-031].
"""

import argparse
import json
import os
import sys

from nxb.contract import CONTRACT
from nxb.dispatch import Broker
from nxb.h4 import Outbox
from nxb.ledger import Ledger
from nxb.receipt import digest_units
from nxb.run import read_directive
from nxb.runtimes import register, RegistrationRefused


def _resolve_ledger(value):
    """Expand `~`, then REFUSE anything still relative.

    nxb-031: this used to be `os.path.abspath(...)`, which resolved a relative
    path against the current directory and handed an absolute one to the
    Ledger, so THE LEDGER'S OWN REFUSAL COULD NEVER FIRE FROM THE CLI. F3 was
    written because idempotency silently scoped to your current directory made
    two shells disagree about whether work had happened; the guard existed and
    the only surface an operator uses walked straight past it.
    """
    path = os.path.expanduser(value)
    if not os.path.isabs(path):
        raise SystemExit(
            f"--ledger must be absolute, got {value!r}. A path relative to the "
            f"current directory means two shells disagree about whether work "
            f"already happened.")
    return path


def _ledger_from(args):
    """Resolve --ledger, falling back to NXB_LEDGER.

    The no-default rule stands: nothing here is guessed and nothing resolves
    against the current directory, which is the property F3 actually needs. An
    env var is still the operator SAYING where state lives, once, and it is
    already how the MCP server is told [nxb-045]. What stays refused is the
    thing that bit us: a relative path, from either source.

    Only enroll/mint/validate use this. The older commands keep --ledger
    required, because those are dispatch surfaces and a wrong ledger there
    silently re-scopes idempotency; these three only read or mint an id.
    """
    value = args.ledger or os.environ.get("NXB_LEDGER")
    if not value:
        raise SystemExit(
            "no ledger: pass --ledger <absolute path>, or set NXB_LEDGER. "
            "There is deliberately no default, so that 'where is my state' "
            "never needs archaeology.")
    return _resolve_ledger(value)


def _one_standing(ledger):
    """The single standing rig, or a SystemExit naming the choice."""
    from nxb.rig import live_rig_sessions
    live = live_rig_sessions(ledger)
    if len(live) == 1:
        return live[0]
    if not live:
        raise SystemExit("no rig is standing. python3 -m nxb rig up --dir <dir>")
    raise SystemExit(f"{len(live)} rigs standing: {', '.join(sorted(live))}. "
                     f"Say which with --session.")


def _rig_state(ledger, session):
    from nxb.keystroke import load_rig
    return load_rig(ledger, session)


def _load_registry(path):
    registry = {}
    if not path:
        return registry
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    for name, decl in doc.items():
        if name.startswith("_"):
            continue
        try:
            register(decl, registry)
        except RegistrationRefused as exc:
            print(json.dumps({"registration_refused": name,
                              "reason": exc.reason,
                              "detail": exc.detail}), file=sys.stderr)
    return registry


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nxb")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser(
        "run", help="dispatch a directive to a runtime and RETURN THE ANSWER")
    r.add_argument("--directive", required=True,
                   help="the instruction, or @path, or - for stdin")
    r.add_argument("--runtime", required=True,
                   help="runtime_id, e.g. claude_code or codex")
    r.add_argument("--ledger", required=True,
                   help="absolute path to the state database (no default)")
    r.add_argument("--dispatch-key",
                   help="reuse a key to RETRY safely after an UNKNOWN. "
                        "Reusing one with a changed directive is refused.")
    r.add_argument("--registry", help="declarations file; defaults to the "
                                      "ones the repo ships")
    r.add_argument("--model", help="pin the model explicitly")
    r.add_argument("--drain-budget", type=float, default=300.0)
    from nxb.grants import DEFAULT_GRANT, GRANTS
    r.add_argument("--grant", default=DEFAULT_GRANT, choices=sorted(GRANTS),
                   help="what the worker may hold; default is the narrow one")

    d = sub.add_parser("dispatch", help="H1 only: observe an envelope, no work is run")
    d.add_argument("envelope")
    # F3, nxb-021. There is NO DEFAULT. The old default was ./.nxb/ledger.db:
    # hidden, gitignored, and relative to wherever you were standing, so the
    # same key was a cached receipt in one directory and a fresh dispatch in
    # another with nothing saying so. An operator must be able to answer "where
    # is my state" without archaeology, and the cheapest way is to make them
    # say it.
    d.add_argument("--ledger", required=True,
                   help="absolute path to the state database (required; there "
                        "is deliberately no default)")
    d.add_argument("--registry")

    pen = sub.add_parser("pending",
                         help="outcomes nobody has collected. THE ALARM.")
    pen.add_argument("--ledger", required=True)

    col = sub.add_parser("collect", help="H4: take delivery of an outcome")
    col.add_argument("dispatch_key")
    col.add_argument("--ledger", required=True)

    g = sub.add_parser("digest", help="canonical digest of a units payload")
    g.add_argument("units")

    sub.add_parser("contract", help="print the published contract")

    en = sub.add_parser("enroll",
                        help="print the ONE command that launches an enrolled worker")
    en.add_argument("name", help="the worker's display name, e.g. 'Worker 3'")
    en.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")
    en.add_argument("--runtime", default="claude_code")
    en.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

    rg = sub.add_parser("rig", help="stand up a named, enrolled tmux scenario")
    rg.add_argument("action",
                    choices=["up", "down", "show", "clear", "send", "collect",
                             "reply", "workers", "orchestrate", "forget",
                             "dispatch", "await", "resume", "reset", "nudge",
                             "relaunch",
                             "health", "checkpoint", "watch", "usage"])
    rg.add_argument("--worker", help="rig send/collect: which worker")
    rg.add_argument("--task-id", action="append", dest="task_ids",
                    help="rig send/collect: a minted nxb task id "
                         "(rig await: repeatable)")
    rg.add_argument("--message", help="rig send/dispatch: the directive body; "
                                      "rig reply: a short answer; "
                                      "rig nudge: the note")
    rg.add_argument("--message-file", default=None,
                    help="rig send/dispatch: a file holding the directive, "
                         "so a long one never rides on a command line")
    rg.add_argument("--file", default=None,
                    help="rig reply: a file holding the full answer")
    # nxb-079: the context budget.
    rg.add_argument("--wait", type=float, default=0.0,
                    help="rig collect/await: seconds to wait INSIDE the "
                         "command for an answer (one round-trip instead of "
                         "a polling loop)")
    rg.add_argument("--tail", type=int, default=None,
                    help="rig collect: lines of pane tail in a WAITING reply "
                         "(default 8)")
    rg.add_argument("--keep-context", action="store_true",
                    help="rig send/dispatch: do NOT reset the worker's "
                         "context first (for a revision of its last task)")
    rg.add_argument("--supersede", default=None,
                    help="rig dispatch: revoke this outstanding task id "
                         "(or 'all') for the worker before minting")
    rg.add_argument("--continue", dest="continue_notes", action="store_true",
                    help="rig resume: tell every resumed pane that holds an "
                         "outstanding task to continue it")
    rg.add_argument("--reaffirm", action="store_true",
                    help="rig resume: re-type the rule into resumed Codex "
                         "panes (one turn each)")
    rg.add_argument("--min-interval", type=int, default=3600,
                    help="rig nudge: seconds between nudges to one pane")
    rg.add_argument("--context-limit", default=None,
                    help="rig relaunch: the pane's new context ceiling in "
                         "tokens, written to the record before the launch")
    rg.add_argument("--effort", default=None,
                    help="rig relaunch: the pane's new effort")
    rg.add_argument("--force", action="store_true",
                    help="rig nudge: ignore the interval and the no-task check")
    rg.add_argument("--full", action="store_true",
                    help="rig collect: return a long answer whole instead of "
                         "its summary and path")
    rg.add_argument("--threshold", type=float, default=None,
                    help="rig checkpoint/watch: context fraction that "
                         "triggers a checkpoint (default 0.8)")
    rg.add_argument("--interval", type=int, default=60,
                    help="rig watch: seconds between passes")
    rg.add_argument("--once", action="store_true",
                    help="rig watch: one pass, then exit")
    rg.add_argument("--peers", default=None,
                    help="rig up/orchestrate: comma-separated peer rigs whose "
                         "ORCHESTRATORS this rig's orchestrator may dispatch to")
    rg.add_argument("--scenario", default=None,
                    help="a named scenario; omit and use --workers to compose")
    rg.add_argument("--orchestrator", default=None,
                    help="runtime for the orchestrator pane: cc|codex|none")
    rg.add_argument("--workers", default=None,
                    help="composition, e.g. 'cx:5' or 'cc:2,cx:2'")
    # No default NAME. RIG-4: `send` assumed a session called 'nxb' while the
    # standing rig was 'nxb-s2', and the refusal blamed the roster. `send`
    # resolves the one standing rig; up/down/clear fall back to 'nxb' because
    # they act on the name itself and guessing a kill target is worse.
    rg.add_argument("--session", default=None,
                    help="tmux session (up/down/clear default to 'nxb'; "
                         "send finds the one standing rig)")
    rg.add_argument("--dir", default=None, help="working directory for panes")
    rg.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    mi = sub.add_parser("mint", help="issue a task id, if the roster allows it")
    mi.add_argument("--worker", required=True)
    mi.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")
    mi.add_argument("--session", default=None,
                    help="count only this rig session's workers (default: "
                         "every rig recorded next to the ledger)")
    mi.add_argument("--supersede", default=None,
                    help="revoke this outstanding id (or 'all') for the "
                         "worker first; without it a busy worker is refused")
    mi.add_argument("--force", action="store_true",
                    help="supersede even a worker whose transcript moved in "
                         "the last five minutes")

    dr = sub.add_parser(
        "doctor", help="check every assumption nxb makes about the runtimes")
    dr.add_argument("--deep", action="store_true",
                    help="also check the /usage wording; costs one Claude turn")
    dr.add_argument("--record", action="store_true",
                    help="write the current runtime versions as verified")

    st = sub.add_parser(
        "studio", help="compose a fleet visually and stand it up (local page)")
    st.add_argument("action", nargs="?", default="serve",
                    choices=["serve", "install", "status", "restart",
                             "uninstall"],
                    help="serve in this terminal, or manage the always-on "
                         "macOS user service")
    st.add_argument("--port", type=int, default=8787)
    st.add_argument("--no-open", action="store_true",
                    help="do not open a browser")
    st.add_argument("--app", action="store_true",
                    help="open a chromeless app window if a Chromium-family "
                         "browser is installed")
    st.add_argument("--fresh-token", action="store_true",
                    help="rotate the stored studio token")
    st.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    cx = sub.add_parser(
        "context", help="the context store: state notes, reports, search "
                        "[nxb-081]")
    cx.add_argument("action", choices=["state", "get", "put", "patch",
                                       "search", "list", "index", "log",
                                       "path", "map", "checkpoint",
                                       "relocate"])
    cx.add_argument("--section", default=None,
                    help="patch: the heading whose section to replace")
    cx.add_argument("--append", action="store_true",
                    help="patch: append to the section instead of replacing")
    cx.add_argument("--dir", default=None, help="map: the project directory")
    cx.add_argument("--worker", default=None, help="checkpoint: which pane")
    cx.add_argument("--to", default=None, help="relocate: the new vault folder")
    cx.add_argument("--session", help="state/log: which rig")
    cx.add_argument("--key", help="get/put: the note key, e.g. notes/decisions")
    cx.add_argument("--file", default=None, help="put: the note body file")
    cx.add_argument("--body", default=None, help="put: the note body inline")
    cx.add_argument("--summary", default=None, help="put: a one-line summary")
    cx.add_argument("--tags", default=None, help="put: comma-separated tags")
    cx.add_argument("--author", default=None, help="put: who wrote it")
    cx.add_argument("--query", help="search: the terms")
    cx.add_argument("--prefix", default="", help="search/list: key prefix")
    cx.add_argument("--limit", type=int, default=None)
    cx.add_argument("--max-chars", type=int, default=None,
                    help="get: how much of the body to return (bounded)")
    cx.add_argument("--offset", type=int, default=0, help="get: read on from")
    cx.add_argument("--line", default=None, help="log: the line to append")
    cx.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    br = sub.add_parser(
        "bridge", help="two agents talk through nxb with no rig [nxb-080]")
    br.add_argument("action", choices=["join", "peers", "send", "inbox",
                                       "history", "leave"])
    br.add_argument("--name", help="join/inbox/leave: your bridge name")
    br.add_argument("--from", dest="sender", help="send: your bridge name")
    br.add_argument("--to", help="send: the recipient's bridge name")
    br.add_argument("--message", help="send: the text")
    br.add_argument("--message-file", default=None,
                    help="send: a file holding the text")
    br.add_argument("--reply-to", type=int, default=None,
                    help="send: the id of the message this answers")
    br.add_argument("--wait", type=float, default=0.0,
                    help="inbox: seconds to wait inside the command")
    br.add_argument("--no-mark-read", action="store_true",
                    help="inbox: leave the messages unread")
    br.add_argument("--limit", type=int, default=50)
    br.add_argument("--a", help="history: one name")
    br.add_argument("--b", help="history: the other name")
    br.add_argument("--runtime", default=None, help="join: what you are")
    br.add_argument("--note", default=None, help="join: a one-line note")
    br.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    rv = sub.add_parser(
        "revoke", help="invalidate a task id, or every one for a worker")
    rv.add_argument("task_id", nargs="?", help="the id to revoke")
    rv.add_argument("--worker", help="revoke every unrevoked id for this worker")
    rv.add_argument("--all", action="store_true",
                    help="revoke every unrevoked id in the ledger")
    rv.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    va = sub.add_parser("validate",
                        help="a worker asks whether a task id is real and is for IT")
    va.add_argument("task_id")
    va.add_argument("--worker", required=True)
    va.add_argument("--ledger", default=None,
                    help="absolute path; or set NXB_LEDGER")

    args = parser.parse_args(argv)

    if args.cmd == "contract":
        print(json.dumps(CONTRACT, indent=2))
        return 0

    if args.cmd == "digest":
        with open(args.units, encoding="utf-8") as handle:
            print(digest_units(json.load(handle)))
        return 0

    if args.cmd == "enroll":
        from nxb.enroll import enroll_command
        cmd, refusal = enroll_command(
            args.name, ledger=_ledger_from(args), repo=args.repo,
            runtime=args.runtime)
        if refusal is not None:
            print(json.dumps(refusal, indent=2))
            return 3
        print(cmd)
        return 0

    if args.cmd == "rig":
        from nxb.rig import SCENARIOS, clear, stand_up, tear_down
        task_ids = getattr(args, "task_ids", None) or []
        args.task_id = task_ids[0] if task_ids else None

        def _body():
            """The directive text: --message, or --message-file, never both."""
            if bool(args.message) == bool(args.message_file):
                raise SystemExit(f"rig {args.action} needs exactly one of "
                                 f"--message or --message-file")
            if args.message_file:
                with open(args.message_file, encoding="utf-8") as handle:
                    return handle.read()
            return args.message

        if args.action == "show":
            print(json.dumps(SCENARIOS, indent=2))
            return 0
        if args.action == "send":
            from nxb.keystroke import send_directive
            missing = [f for f in ("worker", "task_id")
                       if not getattr(args, f)]
            if missing:
                raise SystemExit("rig send needs --" +
                                 ", --".join(m.replace("_", "-")
                                             for m in missing))
            out = send_directive(args.worker, args.task_id, _body(),
                                 ledger=_ledger_from(args),
                                 session=args.session,
                                 fresh=not args.keep_context)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "TYPED" else 3
        if args.action == "dispatch":
            # mint + send in ONE command: one model round-trip, not two.
            from nxb.keystroke import dispatch
            if not args.worker:
                raise SystemExit("rig dispatch needs --worker")
            out = dispatch(args.worker, _body(), ledger=_ledger_from(args),
                           session=args.session, fresh=not args.keep_context,
                           supersede=args.supersede, force=args.force)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "TYPED" else 3
        if args.action == "collect":
            from nxb.keystroke import WAITING_TAIL_LINES, collect_reply
            missing = [f for f in ("worker", "task_id")
                       if not getattr(args, f)]
            if missing:
                raise SystemExit("rig collect needs --" +
                                 ", --".join(m.replace("_", "-")
                                             for m in missing))
            out = collect_reply(args.worker, args.task_id,
                                ledger=_ledger_from(args),
                                session=args.session, wait=args.wait,
                                tail_lines=args.tail or WAITING_TAIL_LINES,
                                full=args.full)
            print(json.dumps(out, indent=2))
            # 4 for WAITING, never 0: an answer that has not arrived must not
            # look to a script like an answer that has. Collect again.
            return {"ANSWERED": 0, "WAITING": 4}.get(out["state"], 3)
        if args.action == "await":
            from nxb.keystroke import await_any
            if not task_ids:
                raise SystemExit("rig await needs one or more --task-id")
            out = await_any(task_ids, ledger=_ledger_from(args),
                            wait=args.wait, session=args.session)
            print(json.dumps(out, indent=2))
            return {"ANSWERED": 0, "WAITING": 4}.get(out["state"], 3)
        if args.action == "resume":
            from nxb.rig import resume
            if not args.session:
                raise SystemExit("rig resume needs --session <rig>")
            out = resume(args.session, ledger=_ledger_from(args),
                         work_dir=args.dir, reaffirm=args.reaffirm,
                         continue_notes=args.continue_notes)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "RESUMED" else 3
        if args.action == "reset":
            from nxb.keystroke import _resolve
            from nxb.rig import reset_pane
            if not args.worker:
                raise SystemExit("rig reset needs --worker")
            ledger = _ledger_from(args)
            pane, session, refusal = _resolve(args.worker, ledger,
                                              args.session)
            if refusal is not None:
                print(json.dumps(refusal, indent=2))
                return 3
            out = reset_pane(pane, session=session, ledger=ledger)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "RESET" else 3
        if args.action == "nudge":
            from nxb.rig import nudge
            if not args.worker or not args.message:
                raise SystemExit("rig nudge needs --worker and --message")
            out = nudge(args.worker, args.message, ledger=_ledger_from(args),
                        session=args.session,
                        min_interval_s=args.min_interval, force=args.force)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "TYPED" else 3
        if args.action == "relaunch":
            from nxb.rig import relaunch_pane
            if not args.worker or not args.session:
                raise SystemExit("rig relaunch needs --session and --worker")
            out = relaunch_pane(args.worker, session=args.session,
                                ledger=_ledger_from(args),
                                context_limit=args.context_limit,
                                effort=args.effort)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "RELAUNCHED" else 3
        if args.action == "health":
            from nxb.rig import health
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            out = health(session, ledger=ledger)
            print(json.dumps(out, indent=2))
            return 0 if "panes" in out else 3
        if args.action == "usage":
            from nxb.rig import usage
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            out = usage(session, ledger=ledger)
            print(json.dumps(out, indent=2))
            return 0 if out.get("state") == "USAGE" else 3
        if args.action == "checkpoint":
            from nxb.rig import CHECKPOINT_THRESHOLD, checkpoint_rig
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            out = checkpoint_rig(session, ledger=ledger, worker=args.worker,
                                 threshold=args.threshold or
                                 CHECKPOINT_THRESHOLD, force=args.force)
            print(json.dumps(out, indent=2))
            return 0 if out.get("state") == "PASS" else 3
        if args.action == "watch":
            from nxb.rig import CHECKPOINT_THRESHOLD, watch
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            out = watch(session, ledger=ledger, interval=args.interval,
                        threshold=args.threshold or CHECKPOINT_THRESHOLD,
                        once=args.once)
            return 0 if (out or {}).get("state") == "PASS" else 3
        if args.action == "reply":
            # A worker FILES its answer where collect reads first, so a
            # report survives its own pane scrolling. [RIG-21]
            from nxb.keystroke import file_reply
            missing = [f for f in ("worker", "task_id")
                       if not getattr(args, f)]
            if missing:
                raise SystemExit("rig reply needs --" +
                                 ", --".join(m.replace("_", "-")
                                             for m in missing))
            if bool(args.message) == bool(args.file):
                raise SystemExit("rig reply needs exactly one of --message "
                                 "or --file")
            answer = args.message
            if args.file:
                with open(args.file, encoding="utf-8") as handle:
                    answer = handle.read()
            out = file_reply(args.worker, args.task_id, answer,
                             ledger=_ledger_from(args))
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "FILED" else 3
        if args.action == "workers":
            # The live roster, for an ORCHESTRATOR to read. Nothing else
            # printed the fleet: `rig show` prints SCENARIOS (what CAN be
            # built), and the only way to see what IS standing was to trigger
            # a mint refusal and read the roster out of the error. [RIG-7]
            from nxb.rig import RigTmuxError, rig_roster
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            try:
                roster = rig_roster(ledger, session)
            except RigTmuxError as exc:
                print(json.dumps({"state": "REFUSED",
                                  "reason": "rig_tmux_unavailable",
                                  "detail": exc.detail,
                                  "remedy": [
                                      "run this from a shell that can reach "
                                      "tmux, or check `tmux ls` by hand"]},
                                 indent=2))
                return 3
            state = _rig_state(ledger, session)
            by_name = {p["name"]: p for p in (state or {}).get("panes", [])}
            print(json.dumps({
                "session": session,
                "workers": [{"name": e.name,
                             "runtime": by_name.get(e.name, {}).get("runtime"),
                             "role": by_name.get(e.name, {}).get("role",
                                                                 "worker"),
                             "pane": e.address,
                             "enrolled": bool(by_name.get(e.name, {})
                                              .get("enrolment"))}
                            for e in roster.named]}, indent=2))
            return 0
        if args.action == "orchestrate":
            # Type the orchestrator brief into a pane that is ALREADY standing,
            # so an existing rig does not have to be rebuilt to gain one.
            from nxb.enroll import typed_orchestrator_rule
            from nxb.rig import await_ack, send_line
            from nxb.keystroke import _resolve
            if not args.worker:
                raise SystemExit("rig orchestrate needs --worker <pane name>")
            ledger = _ledger_from(args)
            pane, session, refusal = _resolve(args.worker, ledger, args.session)
            if refusal is not None:
                print(json.dumps(refusal, indent=2))
                return 3
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            from nxb.rig import _clean_peers
            try:
                peers = _clean_peers(args.peers)
            except ValueError as exc:
                raise SystemExit(str(exc))
            send_line(pane["pane"], typed_orchestrator_rule(
                args.worker, ledger=ledger, repo=repo, session=session,
                peers=peers))
            ok = await_ack(pane["pane"], args.worker, deadline=120.0)
            print(json.dumps({"state": "BRIEFED" if ok else "UNCONFIRMED",
                              "worker": args.worker, "pane": pane["pane"],
                              "session": session,
                              "detail": ("the brief was typed and acknowledged"
                                         if ok else
                                         "the brief was typed and NOT "
                                         "acknowledged; treat this pane as "
                                         "un-briefed and read its screen")},
                             indent=2))
            return 0 if ok else 3
        if args.action == "forget":
            from nxb.keystroke import state_path
            from nxb.rig import live_rig_sessions
            ledger = _ledger_from(args)
            session = args.session or _one_standing(ledger)
            if session in live_rig_sessions(ledger):
                raise SystemExit(f"{session} is standing; tear it down first.")
            try:
                os.remove(state_path(ledger, session))
            except OSError:
                raise SystemExit(f"no record for {session}")
            print(json.dumps({"state": "FORGOTTEN", "session": session},
                             indent=2))
            return 0
        if args.action == "clear":
            out = clear(args.session or "nxb", ledger=_ledger_from(args))
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "CLEARED" else 3
        if args.action == "down":
            out = tear_down(args.session or "nxb")
            print(json.dumps(out, indent=2))
            return 0
        if args.workers or args.orchestrator:
            from nxb.rig import compose, parse_workers
            if args.scenario:
                raise SystemExit("--scenario and --workers are two ways to say "
                                 "the same thing; pass one.")
            try:
                plan = compose(parse_workers(args.workers or "cc:2,cx:2"),
                               orchestrator=(None if args.orchestrator in
                                             (None, "none") else
                                             args.orchestrator))
            except ValueError as exc:
                raise SystemExit(str(exc))
        else:
            plan = args.scenario or "scenario2"
        out = stand_up(plan, session=args.session or "nxb",
                       work_dir=args.dir, ledger=_ledger_from(args),
                       peers=args.peers)
        print(json.dumps(out, indent=2))
        return 0 if out["state"] == "READY" else 3

    if args.cmd == "doctor":
        from nxb.doctor import record, report
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if args.record:
            print(json.dumps(record(root), indent=2))
            return 0
        return report(deep=args.deep, root=root)

    if args.cmd == "studio":
        if args.action != "serve":
            from nxb.studio_service import (StudioServiceError, install,
                                            restart, status, uninstall)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            try:
                if args.action == "install":
                    out = install(_ledger_from(args), root, port=args.port)
                elif args.action == "restart":
                    out = restart(port=args.port)
                elif args.action == "uninstall":
                    out = uninstall(port=args.port)
                else:
                    out = status(port=args.port)
            except StudioServiceError as exc:
                print(f"studio service: {exc}", file=sys.stderr)
                return 3
            print(json.dumps(out, indent=2))
            return 0 if out.get("state") not in ("NOT_INSTALLED",) else 3
        from nxb.studio import serve
        return serve(_ledger_from(args), port=args.port,
                     open_browser=not args.no_open, app=args.app,
                     fresh_token=args.fresh_token)

    if args.cmd == "context":
        from nxb.context import (GET_CAP_CHARS, SEARCH_LIMIT, Vault,
                                 log_key, state_key)
        vault = Vault(_ledger_from(args))
        try:
            if args.action == "state":
                if not args.session:
                    raise SystemExit("context state needs --session")
                out = vault.state(args.session)
            elif args.action == "get":
                if not args.key:
                    raise SystemExit("context get needs --key")
                out = vault.get(args.key, max_chars=args.max_chars or
                                GET_CAP_CHARS, offset=args.offset)
            elif args.action == "put":
                if not args.key:
                    raise SystemExit("context put needs --key")
                if bool(args.body) == bool(args.file):
                    raise SystemExit("context put needs exactly one of "
                                     "--body or --file")
                body = args.body
                if args.file:
                    with open(args.file, encoding="utf-8") as handle:
                        body = handle.read()
                tags = [t.strip() for t in (args.tags or "").split(",")
                        if t.strip()]
                out = vault.put(args.key, body, summary=args.summary,
                                tags=tags, author=args.author)
            elif args.action == "patch":
                if not args.key or not args.section:
                    raise SystemExit("context patch needs --key and --section")
                if bool(args.body) == bool(args.file):
                    raise SystemExit("context patch needs exactly one of "
                                     "--body or --file")
                body = args.body
                if args.file:
                    with open(args.file, encoding="utf-8") as handle:
                        body = handle.read()
                out = vault.patch(args.key, args.section, body,
                                  append=args.append, author=args.author)
            elif args.action == "map":
                from nxb.keystroke import load_rig
                work_dir = args.dir
                if not work_dir and args.session:
                    work_dir = (load_rig(vault.ledger, args.session) or {}
                                ).get("work_dir")
                if not work_dir:
                    raise SystemExit("context map needs --dir or --session "
                                     "(with a recorded work_dir)")
                out = vault.map(work_dir)
            elif args.action == "checkpoint":
                if not args.session or not args.worker:
                    raise SystemExit("context checkpoint needs --session and "
                                     "--worker")
                out = vault.checkpoint(args.session, args.worker)
            elif args.action == "relocate":
                if not args.to:
                    raise SystemExit("context relocate needs --to <folder>")
                out = vault.relocate(args.to)
            elif args.action == "search":
                if not args.query:
                    raise SystemExit("context search needs --query")
                out = vault.search(args.query, limit=args.limit or
                                   SEARCH_LIMIT, prefix=args.prefix or None)
            elif args.action == "list":
                out = vault.list(args.prefix)
            elif args.action == "index":
                out = vault.reindex()
            elif args.action == "log":
                if not args.session or not args.line:
                    raise SystemExit("context log needs --session and --line")
                out = vault.append(log_key(args.session), args.line)
            else:
                out = {"state": "PATH", "root": vault.root,
                       "state_note": vault.path_for(state_key(
                           args.session)) if args.session else None,
                       "index": __import__("nxb.context", fromlist=["x"])
                       .index_path(vault.ledger),
                       "obsidian": ("open this folder as a vault in Obsidian, "
                                    "or set NXB_VAULT to a folder inside "
                                    "one of your vaults")}
        finally:
            vault.close()
        print(json.dumps(out, indent=2))
        return {"REFUSED": 3, "MISSING": 4, "EMPTY": 4}.get(
            out.get("state"), 0)

    if args.cmd == "bridge":
        from nxb.bridge import Bridge
        bridge = Bridge(_ledger_from(args))
        try:
            if args.action == "join":
                if not args.name:
                    raise SystemExit("bridge join needs --name")
                out = bridge.join(args.name, runtime=args.runtime,
                                  note=args.note)
            elif args.action == "peers":
                out = bridge.peers()
            elif args.action == "send":
                if not args.sender or not args.to:
                    raise SystemExit("bridge send needs --from and --to")
                if bool(args.message) == bool(args.message_file):
                    raise SystemExit("bridge send needs exactly one of "
                                     "--message or --message-file")
                text = args.message
                if args.message_file:
                    with open(args.message_file, encoding="utf-8") as handle:
                        text = handle.read()
                out = bridge.send(args.sender, args.to, text,
                                  reply_to=args.reply_to)
            elif args.action == "inbox":
                if not args.name:
                    raise SystemExit("bridge inbox needs --name")
                out = bridge.inbox(args.name, wait=args.wait,
                                   mark_read=not args.no_mark_read,
                                   limit=args.limit)
            elif args.action == "history":
                if not args.a or not args.b:
                    raise SystemExit("bridge history needs --a and --b")
                out = bridge.history(args.a, args.b, limit=args.limit)
            else:
                if not args.name:
                    raise SystemExit("bridge leave needs --name")
                out = bridge.leave(args.name)
        finally:
            bridge.close()
        print(json.dumps(out, indent=2))
        # EMPTY is 4, like WAITING: not an answer, not a failure.
        return {"REFUSED": 3, "EMPTY": 4}.get(out.get("state"), 0)

    if args.cmd == "revoke":
        from nxb.tasks import TaskRegistry
        reg = TaskRegistry(_ledger_from(args))
        try:
            revoked = reg.revoke_many(task_id=args.task_id,
                                      worker=args.worker, every=args.all)
        except ValueError as exc:
            raise SystemExit(str(exc))
        finally:
            reg.close()
        print(json.dumps({"state": "REVOKED", "count": len(revoked),
                          "task_ids": revoked}, indent=2))
        return 0

    if args.cmd == "mint":
        # The whole of minting lives in nxb/minting.py so `rig dispatch` can
        # mint without a second process. [nxb-079]
        from nxb.minting import mint_task
        task_id, refusal = mint_task(_ledger_from(args), args.worker,
                                     session=args.session,
                                     supersede=args.supersede,
                                     force=args.force)
        if refusal is not None:
            print(json.dumps(refusal, indent=2))
            return 3
        # JSON on both paths. Success used to print a bare id while a refusal
        # printed JSON, so nothing could parse the output without knowing the
        # answer first.
        print(json.dumps({"state": "ISSUED", "task_id": task_id,
                          "worker": args.worker}, indent=2))
        return 0

    if args.cmd == "validate":
        from nxb.tasks import TaskRegistry
        reg = TaskRegistry(_ledger_from(args))
        try:
            verdict = reg.validate(args.task_id, args.worker)
            print(json.dumps(verdict, indent=2))
            # 0 means PROCEED. Anything else means REFUSE THE DIRECTIVE.
            return 0 if verdict["valid"] else 3
        finally:
            reg.close()

    if args.cmd == "run":
        from nxb.run import run
        code, _ = run(directive=read_directive(args.directive),
                      runtime_id=args.runtime, ledger_path=args.ledger,
                      dispatch_key=args.dispatch_key,
                      registry_path=args.registry, model=args.model,
                      drain_budget=args.drain_budget, grant=args.grant)
        return code

    ledger_path = _resolve_ledger(args.ledger)
    # Every command that touches state says where that state is, every time.
    print(f"ledger: {ledger_path}", file=sys.stderr)

    if args.cmd in ("pending", "collect"):
        led = Ledger(ledger_path)
        box = Outbox(led._conn)
        if args.cmd == "pending":
            rows = box.pending()
            print(json.dumps(rows, indent=2))
            # An empty alarm and a firing alarm must not look alike.
            print(f"{len(rows)} uncollected outcome(s)", file=sys.stderr)
            return 0
        result = box.collect(args.dispatch_key)
        print(json.dumps(result, indent=2))
        return {"DELIVERED": 0, "PENDING": 4, "UNKNOWN_KEY": 3}[result["state"]]

    with open(args.envelope, encoding="utf-8") as handle:
        envelope = json.load(handle)
    broker = Broker(Ledger(ledger_path), registry=_load_registry(args.registry))
    result = broker.dispatch(envelope)
    print(json.dumps(result, indent=2))
    # The exit code carries the state so a shell caller cannot mistake
    # UNKNOWN for failure. 0 observed, 3 refused, 4 unknown. Deliberately NOT
    # 1, so a naive `|| echo failed` does not conflate REFUSED with UNKNOWN.
    return {"OBSERVED": 0, "REFUSED": 3, "UNKNOWN": 4}[result["state"]]


if __name__ == "__main__":
    sys.exit(main())
