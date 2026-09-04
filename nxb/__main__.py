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
                             "workers", "orchestrate", "forget"])
    rg.add_argument("--worker", help="rig send/collect: which worker")
    rg.add_argument("--task-id", help="rig send/collect: a minted nxb task id")
    rg.add_argument("--message", help="rig send: the directive body")
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
        if args.action == "show":
            print(json.dumps(SCENARIOS, indent=2))
            return 0
        if args.action == "send":
            from nxb.keystroke import send_directive
            missing = [f for f in ("worker", "task_id", "message")
                       if not getattr(args, f)]
            if missing:
                raise SystemExit("rig send needs --" +
                                 ", --".join(m.replace("_", "-")
                                             for m in missing))
            out = send_directive(args.worker, args.task_id, args.message,
                                 ledger=_ledger_from(args),
                                 session=args.session)
            print(json.dumps(out, indent=2))
            return 0 if out["state"] == "TYPED" else 3
        if args.action == "collect":
            from nxb.keystroke import collect_reply
            missing = [f for f in ("worker", "task_id")
                       if not getattr(args, f)]
            if missing:
                raise SystemExit("rig collect needs --" +
                                 ", --".join(m.replace("_", "-")
                                             for m in missing))
            out = collect_reply(args.worker, args.task_id,
                                ledger=_ledger_from(args),
                                session=args.session)
            print(json.dumps(out, indent=2))
            # 4 for WAITING, never 0: an answer that has not arrived must not
            # look to a script like an answer that has. Collect again.
            return {"ANSWERED": 0, "WAITING": 4}.get(out["state"], 3)
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
            send_line(pane["pane"], typed_orchestrator_rule(
                args.worker, ledger=ledger, repo=repo, session=session))
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
                       work_dir=args.dir, ledger=_ledger_from(args))
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

    if args.cmd in ("mint", "validate"):
        from nxb.roster import discover
        from nxb.tasks import TaskRegistry
        reg = TaskRegistry(_ledger_from(args))
        try:
            if args.cmd == "mint":
                # Both populations: sessions the runtime registry can name,
                # and workers a rig declared. A Codex pane appears only in the
                # second, and is no less declared for it. EVERY rig recorded
                # next to the ledger counts unless --session narrows it --
                # RIG-4 was a default session name drifting from the rig
                # actually standing, refused as if the worker were undeclared.
                from nxb.keystroke import rig_sessions
                from nxb.rig import rig_roster
                from nxb.roster import Roster
                ledger = _ledger_from(args)
                # LIVE rigs only. rig_sessions() lists every rig ever
                # recorded next to this ledger, including ones torn down
                # hours ago, and a dead rig has no workers to contribute.
                from nxb.rig import live_rig_sessions
                sessions = ([args.session] if args.session
                            else live_rig_sessions(ledger))
                from nxb.rig import RigTmuxError
                entries, seen = list(discover().entries), {}
                for s in sessions:
                    try:
                        found = rig_roster(ledger, s).entries
                        for e in found:
                            if e.name == args.worker:
                                seen.setdefault(e.name, []).append(s)
                        entries.extend(found)
                    except RigTmuxError as exc:
                        # Refuse rather than mint against a roster we know is
                        # incomplete: a silently short roster is how RIG-4
                        # blamed the operator for a worker that existed.
                        print(json.dumps({"state": "REFUSED",
                                          "reason": "rig_tmux_unavailable",
                                          "detail": exc.detail}, indent=2))
                        return 3
                # Scenario-built fleets share worker names by design, so with
                # two rigs standing "CC Worker 1" names two different panes.
                # Minting for whichever came first would hand out a ticket
                # that types into someone else's fleet. [RIG-18]
                rigs = seen.get(args.worker, [])
                if len(rigs) > 1:
                    print(json.dumps({
                        "state": "REFUSED", "reason": "roster_ambiguous_worker",
                        # UNREACHABLE while RIG-20 holds, and kept on
                        # purpose: it fires on a naming REGRESSION rather
                        # than on operator behaviour, which is the one thing
                        # that could bring the collision back.
                        "detail": (f"{args.worker!r} exists in {len(rigs)} "
                                   f"standing rigs: {', '.join(sorted(rigs))}. "
                                   f"Names are supposed to carry their rig "
                                   f"(RIG-20), so this means scoped naming "
                                   f"has regressed."),
                        "remedy": [f"--session {r}" for r in sorted(rigs)]},
                        indent=2))
                    return 3
                task_id, refusal = reg.mint(args.worker, Roster(entries))
                if refusal is not None:
                    print(json.dumps(refusal, indent=2))
                    return 3
                # JSON on both paths. Success used to print a bare id while
                # a refusal printed JSON, so nothing could parse the output
                # without knowing the answer first.
                print(json.dumps({"state": "ISSUED", "task_id": task_id,
                                  "worker": args.worker}, indent=2))
                return 0
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
