"""Executable `closes_when` predicates for FINDINGS.json.

Each returns True when the finding is closed. The ledger test asserts the
predicate agrees with the recorded state, in BOTH directions:

  OPEN  + check passes  -> the record is lying; the thing is already fixed.
  FIXED + check fails   -> the fix regressed.

This is the generalisation of the mechanism that already worked once: an
expectedFailure tracking `units` flipped to an unexpected success the moment
the fix landed and held the suite red until the record was updated. A debt that
cannot be paid quietly also cannot be forgotten.
"""

import inspect
import json
import os
import pathlib
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _contract():
    return json.loads((_ROOT / "contract" / "contract.json").read_text())


def c1_canonicalisation_published():
    """C-1: does the contract say HOW to canonicalise before digesting?"""
    raw = json.dumps(_contract()).lower()
    return all(t in raw for t in ("sort", "separator")) and "ensure_ascii" in raw


def f1_divergent_repeat_refused():
    from nxb.dispatch import Broker
    from nxb.ledger import Ledger
    from nxb.runtimes import register
    from tests.test_dispatch import envelope, live_declaration
    with tempfile.TemporaryDirectory() as tmp:
        reg = {}
        register(live_declaration(), reg)
        led = Ledger(f"{tmp}/l.db")
        try:
            b = Broker(led, registry=reg)
            b.dispatch(envelope())
            out = b.dispatch(envelope(units=[{"instruction": "different"}]))
            return out["state"] == "REFUSED"
        finally:
            led.close()


def f2_repeat_replays_refusal():
    from nxb.dispatch import Broker
    from nxb.ledger import Ledger
    from nxb.runtimes import register
    from tests.test_dispatch import envelope, live_declaration
    with tempfile.TemporaryDirectory() as tmp:
        reg = {}
        register(live_declaration(), reg)
        led = Ledger(f"{tmp}/l.db")
        try:
            b = Broker(led, registry=reg)
            bad = envelope(declared_digest="0" * 64)
            return (b.dispatch(bad)["state"] == "REFUSED"
                    and b.dispatch(bad)["state"] == "REFUSED")
        finally:
            led.close()


def f3_relative_ledger_refused():
    from nxb.ledger import Ledger
    try:
        Ledger("relative/ledger.db")
    except ValueError:
        return True
    return False


def f4_alarm_reachable():
    """The firing alarm must be reachable from the surface an operator has."""
    from nxb import __main__ as cli
    src = inspect.getsource(cli)
    return '"pending"' in src and '"collect"' in src


def f7_observer_matches_contract():
    from nxb.dispatch import Broker
    default = inspect.signature(Broker.__init__).parameters["observer"].default
    return default == _contract()["examples"]["receipt"]["observer"]


def w3_units_reaches_worker():
    from nxb import roundtrip
    src = inspect.getsource(roundtrip)
    return "render_directive(envelope[" in src


def w3_start_timeout_honoured():
    from nxb import roundtrip
    src = inspect.getsource(roundtrip)
    return 'declaration.get("start_timeout")' in src


def h2_1_events_write_is_capped():
    """H2-1: is the write path bounded, or can a child write without limit?

    BEHAVIOURAL, not textual. This check used to grep a named module and
    reported a regression in nxb-027 when the code merely MOVED to a shared
    base while the property still held. A check coupled to where code lives
    tests the file layout, not the property. See finding CHECK-1.
    """
    import io
    from nxb.adapters._process import _BoundedWriter
    w = _BoundedWriter(io.StringIO(), cap=100)
    w.write("x" * 500)
    return w.truncated and w._written <= 100 + 200


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and obj.__module__ == __name__}


def n1_canonical_form_is_valid_json():
    """N-1: a non-finite number must be refused, not encoded as NaN/Infinity."""
    from nxb.receipt import CanonicalisationError, canonical_bytes
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            canonical_bytes([{"n": bad}])
            return False
        except CanonicalisationError:
            pass
    return True


def n2_untransmittable_text_is_refused():
    """N-2: text that cannot go on a UTF-8 wire must not be digested."""
    from nxb.receipt import CanonicalisationError, canonical_bytes
    try:
        canonical_bytes([{"s": "\ud800"}])
        return False
    except CanonicalisationError:
        return True


def c1_test_vectors_reproduce():
    """C-1: the published vectors must match what the code actually emits."""
    from nxb.receipt import canonical_bytes
    canon = _contract().get("canonicalisation")
    if not canon:
        return False
    return all(canonical_bytes(v["value"]).decode() == v["canonical"]
               for v in canon["test_vectors"])


def h2_2_no_spin_on_eof():
    """H2-2: a child that closes stdout and lives must not burn a core."""
    from nxb.adapters import codex
    src = inspect.getsource(codex.CodexAdapter.spawn)
    return "registered = False" in src and "proc.wait(timeout=dl.slice" in src


def h2_3_kill_cannot_raise():
    """H2-3: nothing escapes the kill path into a caller promised a refusal."""
    from nxb.adapters import codex
    src = inspect.getsource(codex.CodexAdapter._kill)
    return "except Exception" in src


def blocking_class_has_an_interrupter():
    """The class fix: a deadline that can interrupt, not one that is checked.

    Searches every module under nxb/ rather than one named file, so moving the
    loops does not read as losing the property. Also proves the breaker
    actually fires while the caller is blocked, which is the whole claim.
    """
    import pathlib
    import time
    from nxb.deadline import Deadline

    paired = any(
        "Deadline(" in t and "breaker=" in t
        for t in (f.read_text() for f in (_ROOT / "nxb").rglob("*.py")))
    fired = []
    with Deadline(0.05, breaker=lambda: fired.append(1)):
        time.sleep(0.2)
    return paired and bool(fired)


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def cc1_reader_survives_a_break():
    """CC-1: frames buffered in spawn must survive the handover to drain."""
    import io
    import os as _os
    from nxb.adapters._process import _LineReader
    r, w = _os.pipe()
    _os.write(w, b"a\nb\nc\n")
    _os.close(w)
    reader = _LineReader(io.FileIO(r, "r"))
    for _ in reader.drain_ready():
        break
    return reader.has_pending and len(list(reader.drain_ready())) == 2


def cc2_claude_schema_is_inlined():
    """CC-2: --json-schema takes the schema itself, not a path."""
    import tempfile
    from nxb.adapters.claude_code import ClaudeCodeAdapter
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"type": "object"}, fh)
        path = fh.name
    cmd = ClaudeCodeAdapter().build_command(
        work_dir="/tmp", prompt="p", out_path="/tmp/o", schema_path=path)
    i = cmd.index("--json-schema")
    return cmd[i + 1] != path and json.loads(cmd[i + 1])["type"] == "object"


def cc3_spawned_child_declaration_registers():
    """CC-3: a spawned Claude Code child must have a registrable declaration."""
    from nxb.runtimes import register
    path = _ROOT / "contract" / "runtimes" / "claude_code.json"
    decl = json.loads(path.read_text()).get("spawned_child")
    if not decl:
        return False
    registry = {}
    register(decl, registry)
    return "claude_code" in registry


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def c14_blank_id_is_not_a_start():
    from nxb.adapters._process import find_evidence
    from nxb.adapters.codex import CodexAdapter
    from nxb.adapters.claude_code import ClaudeCodeAdapter
    blank_refs = [CodexAdapter()._match_start(
                      {"type": "thread.started", "thread_id": ""})[1],
                  ClaudeCodeAdapter()._match_start(
                      {"type": "system", "subtype": "init", "session_id": ""})[1]]
    return (not any(blank_refs)
            and find_evidence("~", "") is None
            and CodexAdapter.evidence_for("") is None
            and ClaudeCodeAdapter.evidence_for("") is None)


def rt1_replay_returns_the_answer_after_divergence_check():
    """A replay must not clobber, AND must not answer before H1 refuses."""
    import inspect
    from nxb import roundtrip
    src = inspect.getsource(roundtrip.RoundTrip.dispatch)
    h1 = src.index("self.broker.dispatch(")
    peek = src.index("self.outbox.peek(")
    return h1 < peek and "already_spawned" in src


def f3_relative_ledger_refused_from_the_cli():
    """F3's guard must be reachable from the surface an operator uses.

    BEHAVIOURAL. The first version of this check grepped for `abspath` in the
    resolver's source and failed on the DOCSTRING that explains what the code
    used to do. That is the third time in this project a source-grep check has
    tripped on prose describing the very thing it forbids, after the pkill
    comment in nxb-021 and the relocation false-red in CHECK-1. Assert the
    behaviour, not the text.
    """
    from nxb import __main__ as cli
    from nxb import run as runmod
    try:
        cli._resolve_ledger("rel/ledger.db")
        return False
    except SystemExit:
        pass
    try:
        runmod.run(directive="x", runtime_id="claude_code",
                   ledger_path="rel/ledger.db")
        return False
    except ValueError:
        return True
    except Exception:
        return False


def canary_verdict_matches_its_own_evidence():
    """A canary must not report ok when its proof failed verification."""
    import inspect
    from nxb import canary
    src = inspect.getsource(canary.run_canary)
    return "if not proof_store.clear_disproof(" in src


def nxb_has_a_surface_that_returns_an_answer():
    import inspect
    from nxb import __main__ as cli
    return '"run"' in inspect.getsource(cli)


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def workdir_is_honoured_by_the_base():
    """WD-1: an adapter must not be able to accept work_dir and drop it."""
    import inspect
    from nxb.adapters._process import ProcessAdapter
    src = inspect.getsource(ProcessAdapter.spawn)
    return "cwd=work_dir" in src


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def wd2_deleted_token_waiver_expires():
    """WD-2: does a waiver for a REMOVED token expire?

    Every other waiver in this project expires by becoming CONFORMANT. A token
    waived because it is being DELETED has no such condition: it was never
    published, so there is nothing for it to become conformant with. Fixed by
    expiring that category in the opposite direction, on removal.

    Behavioural, not textual: feeds the rule a token no code-side vocabulary
    carries and asserts it is flagged, and feeds it a live one and asserts it is
    not. A check that grepped for the rule's name would pass over a rule that
    had been gutted.
    """
    from tests.test_vocabulary_drift import (code_side_vocabularies,
                                             stale_code_side_waivers)
    live = set()
    for _where, terms in code_side_vocabularies().values():
        live.update(terms)
    if not live:
        return False
    a_live_token = sorted(live)[0]
    return (stale_code_side_waivers({"a_token_no_vocabulary_carries": "x"})
            == ["a_token_no_vocabulary_carries"]
            and stale_code_side_waivers({a_live_token: "x"}) == [])


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def proof1_refs_are_anchored_and_rooted():
    from nxb.proof import codex_evidence_verifier as v
    bad = [("/etc/hosts", "o"), ("/etc/passwd", "s"), ("/etc/shells", "e")]
    return not any(v({"evidence_path": p, "runtime_ref": r,
                      "runtime_id": "codex"}) for p, r in bad)


def proof2_regular_file_check_is_on_the_descriptor():
    import inspect
    from nxb import proof
    src = inspect.getsource(proof.codex_evidence_verifier)
    return "os.fstat(fd)" in src and "O_NONBLOCK" in src


def proof3_malformed_path_is_refused_not_raised():
    from nxb.proof import codex_evidence_verifier as v
    try:
        return v({"evidence_path": "/tmp/e\x00x", "runtime_ref": "a" * 12,
                  "runtime_id": "codex"}) is False
    except Exception:
        return False


def rt2_already_spawned_exposes_the_child():
    import inspect
    from nxb.h2 import SpawnHop
    src = inspect.getsource(SpawnHop.spawn)
    return "runtime_ref" in src and "evidence_for(ref)" in src


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def h2_8_children_are_process_group_isolated():
    """H2-8: a child must not share the broker's process group."""
    import inspect
    from nxb.adapters._process import ProcessAdapter
    spawn = inspect.getsource(ProcessAdapter.spawn)
    kill = inspect.getsource(ProcessAdapter._kill)
    return ("start_new_session=True" in spawn and "_nxb_pgid" in spawn
            and "_signal_group" in kill)


def decl1_both_runtimes_are_registrable():
    """Every runtime the CLI can name must have a registrable declaration."""
    import glob
    from nxb.run import ADAPTERS, load_registry
    return all(rid in load_registry(rid)[0] for rid in ADAPTERS)


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def wd3_collect_report_declaration_is_consumed_or_gone():
    """WD-3: is `declaration` still accepted by collect_report and read by nobody?

    Behavioural on the AST rather than a grep for the name: passes when the
    parameter is consumed OR removed from the signature, which are the two
    honest resolutions, and fails while it is merely carried.
    """
    from tests.test_dropped_parameter_guard import dropped_parameters
    return not any(fn == "collect_report" and param == "declaration"
                   for _f, fn, param, _l in dropped_parameters())


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def proof4_evidence_cap_clears_the_measured_ref_offset():
    """PROOF-4: is the 256KB evidence read cap actually big enough?

    The finding was raised UNVERIFIED: a transcript whose ref first appears past
    the cap would fail verification, and nobody had checked. Measured in nxb-040
    across every real artefact on this machine, 582 of them, restricted to files
    the verifier would actually accept (a ref anchored in the basename):

        codex        n=363   max first-occurrence offset 143 bytes
        claude_code  n=219   max first-occurrence offset 255 bytes

    Both runtimes put the ref in the FIRST record, so the worst observed case
    uses 0.1% of the cap. The invariant holds with a 1000x margin.

    So the check is not "re-measure the machine", which would make a regression
    test depend on whichever transcripts happen to be lying around. It is that
    the cap stays far above the measured worst case. Lowering it toward the
    observed offsets is the only way this becomes a real defect, and that is a
    code change, which is the thing a regression test can actually watch.
    """
    from nxb.proof import _MAX_EVIDENCE_BYTES
    MEASURED_WORST_OFFSET = 255          # nxb-040, n=582
    return _MAX_EVIDENCE_BYTES >= MEASURED_WORST_OFFSET * 100


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def grant2_fleet_tools_are_banned_and_read_back():
    """GRANT-2: banned under every grant, AND verified against the child's own
    init frame so the denylist fails loud rather than rotting open."""
    from nxb.adapters.claude_code import ClaudeCodeAdapter
    from nxb.grants import GRANTS, adapter_kwargs
    for name in GRANTS:
        banned = adapter_kwargs(name, "claude_code").get("banned_tools") or []
        if not {"SendMessage", "ListAgents", "Task"}.issubset(set(banned)):
            return False
    a = ClaudeCodeAdapter(**adapter_kwargs("default", "claude_code"))
    rejected = a._reject_start({"type": "system", "subtype": "init",
                                "tools": ["Read", "SendMessage"]})
    accepted = a._reject_start({"type": "system", "subtype": "init",
                                "tools": ["Read"]})
    return rejected is not None and accepted is None


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def enforce_1_no_security_claims():
    """ENFORCE-1. Enrolment removes drift; it must never be sold as a boundary.

    Checks the operator-facing prose, not the internals: the risk is what
    Rohan reads and believes, not what a variable is called.
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    banned = re.compile(r"\b(security boundary|prevents an orchestrator|"
                        r"authorises the worker|cannot be bypassed)\b", re.I)
    for doc in (root / "docs").glob("OPERATOR-NOTE*.md"):
        if banned.search(doc.read_text(encoding="utf-8")):
            return False
    note = (root / "contract" / "roster.json").read_text(encoding="utf-8")
    return "IT IS NOT A SECURITY BOUNDARY" in note


def enforce_2_mint_blocked_on_naming():
    """ENFORCE-2. Closes only when a real-roster mint returns an id.

    Deliberately checks the LIVE roster rather than a fixture. A fixture would
    pass today and the finding would close while the chain is still inert.

    Returns a plain bool. A (bool, reason) tuple is always truthy, so a check
    written that way reads as PASSING however it failed, and the ledger then
    reports an open finding as already fixed. [nxb-049, hit and fixed here.]
    """
    from nxb.roster import discover
    from nxb.tasks import TaskRegistry
    import os
    import tempfile
    roster = discover()
    if not roster.names:
        return False        # live workers, none nameable: mint still refuses
    with tempfile.TemporaryDirectory() as tmp:
        reg = TaskRegistry(os.path.join(tmp, "c.db"))
        try:
            task_id, refusal = reg.mint(sorted(roster.names)[0], roster)
        finally:
            reg.close()
    return task_id is not None


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def rig_1_codex_gap_is_stated():
    """RIG-1. The asymmetry must be visible where Codex workers are offered."""
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    contract = json.loads((root / "contract" / "rig.json").read_text())
    if "unprotected" not in json.dumps(contract).lower():
        return False
    note = (root / "docs" / "OPERATOR-NOTE-nxb.md").read_text(encoding="utf-8")
    return "neither" in note.lower() and "codex queue" in note.lower()


def rig_2_sendkeys_is_not_a_dispatch_path():
    """RIG-2. Closes only on Rohan's ruling; until then this asserts the
    default has not quietly changed underneath the question."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("dispatch.py", "roundtrip.py", "h2.py", "run.py", "mcp.py"):
        path = root / "nxb" / name
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and "rig" in (
                    node.module or "").split("."):
                return False
            if isinstance(node, ast.Import) and any(
                    "rig" in a.name.split(".") for a in node.names):
                return False
    import json
    contract = json.loads((root / "contract" / "rig.json").read_text())
    # A ruling relayed by an orchestrator is enough to BUILD on and not enough
    # to close with. This closes when Rohan has stated it readably himself.
    return bool(contract.get("_ruling", {}).get("ruling_confirmed_by_rohan"))


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def rig_3_typed_rule_decay_measured():
    """RIG-3. Closes only on a recorded soak, never on the six-case proof.

    Six cases across three turns show the barrier WORKS; they say nothing
    about whether it SURVIVES, and those are different claims.
    """
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    contract = json.loads((root / "contract" / "rig.json").read_text())
    soak = contract.get("_typed_rule_soak", {})
    return bool(soak.get("turns_tested")) and soak.get("verdict") is not None


def rig_5_the_answer_comes_back_correlated():
    """RIG-5. A reply must be readable, bounded by its OWN task id, and an
    echoed directive must never read as an answer to itself."""
    from nxb import keystroke
    from nxb.keystroke import collect_reply, done_marker, marked_directive
    task, other = "nxbt-check5", "nxbt-someoneelse"
    pane = {"name": "W", "runtime": "codex", "pane": "%9",
            "enrolment": "typed"}

    def collect(screen):
        real_resolve, real_capture = keystroke._resolve, None
        keystroke._resolve = lambda w, l, s: (pane, "s", None)
        import nxb.rig
        real_capture = nxb.rig.capture_history
        nxb.rig.capture_history = lambda p, **k: screen
        try:
            return collect_reply("W", task, ledger="/tmp/l.db")
        finally:
            keystroke._resolve, nxb.rig.capture_history = (real_resolve,
                                                           real_capture)

    directive = marked_directive(task, "W", "count them")
    if collect(directive)["state"] != "WAITING":
        return False                      # the echo is not an answer
    answered = collect(f"{directive}\n42\n{done_marker(task)}\n")
    if answered["state"] != "ANSWERED" or answered["answer"] != "42":
        return False
    # Another task's marker must not close this one.
    return collect(f"{directive}\n42\n{done_marker(other)}\n")["state"] \
        == "WAITING"


def rig_4_dispatch_defaults_find_the_standing_rig():
    """RIG-4. No dispatch-path command may ASSUME a session name.

    send resolves the standing rig (its session parameter has no name to
    default to), and mint counts every rig recorded next to the ledger.
    """
    import pathlib

    from nxb.keystroke import send_directive
    if inspect.signature(send_directive).parameters["session"].default \
            is not None:
        return False
    root = pathlib.Path(__file__).resolve().parent.parent
    # nxb-079 moved minting into nxb/minting.py so `rig dispatch` can mint
    # without a second process; the property is the same, the file moved.
    return "rig_sessions" in ((root / "nxb" / "__main__.py").read_text()
                              + (root / "nxb" / "minting.py").read_text())


def rig_24_collect_waits_inside_the_command():
    """RIG-24. `collect` takes a wait budget, dispatch is one command, and
    the brief tells the orchestrator to use both and never to poll."""
    from nxb.enroll import orchestrator_rule
    from nxb.keystroke import collect_reply, dispatch
    if "wait" not in inspect.signature(collect_reply).parameters:
        return False
    if not callable(dispatch):
        return False
    text = orchestrator_rule("O", ledger="/l", repo="/r", session="s")
    return all(t in text for t in ("--wait", "NEVER poll", "rig dispatch",
                                   "--message-file"))


def rig_25_every_launch_carries_a_context_ceiling():
    """RIG-25. Both launch lines carry a ceiling by default, and a
    fresh-context send is the default."""
    import os

    from nxb.keystroke import send_directive
    from nxb.rig import launch_command
    if inspect.signature(send_directive).parameters["fresh"].default is not True:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        cc, _, _ = launch_command(
            {"name": "W", "runtime": "claude_code", "role": "worker"},
            ledger=os.path.join(tmp, "l.db"), repo="/r")
        cx, _, _ = launch_command(
            {"name": "W", "runtime": "codex", "role": "worker"},
            ledger=os.path.join(tmp, "l.db"), repo="/r")
    return "--autocompact" in cc and "model_auto_compact_token_limit" in cx


def rig_26_a_downed_rig_is_resumable_on_its_ids():
    """RIG-26. The record holds the ids and `rig resume` reopens on them."""
    import os

    from nxb import rig
    from nxb.keystroke import PANE_RECORD_KEYS
    from nxb.rig import launch_command
    if not callable(getattr(rig, "resume", None)):
        return False
    if not {"session_id", "thread_id", "instructions"} <= set(PANE_RECORD_KEYS):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        cc, _, _ = launch_command(
            {"name": "W", "runtime": "claude_code", "role": "worker",
             "session_id": "sid"}, ledger=os.path.join(tmp, "l.db"), repo="/r")
        cx, _, _ = launch_command(
            {"name": "W", "runtime": "codex", "role": "worker",
             "resume_thread_id": "tid"}, ledger=os.path.join(tmp, "l.db"),
            repo="/r")
    return "--session-id sid" in cc and cx.endswith("resume tid")


def rig_27_mint_refuses_a_busy_worker():
    """RIG-27. A second id for a worker with an unfiled task is refused."""
    import os
    import types
    from unittest import mock

    from nxb.minting import TASK_WORKER_BUSY, mint_task
    from nxb.roster import RosterEntry
    roster = types.SimpleNamespace(entries=[
        RosterEntry("%1", name="W", alive=True, source="rig")])
    with tempfile.TemporaryDirectory() as tmp:
        ledger = os.path.join(tmp, "l.db")
        with mock.patch("nxb.roster.discover", lambda: roster), \
                mock.patch("nxb.rig.live_rig_sessions", lambda l: []):
            first, refusal = mint_task(ledger, "W")
            if refusal is not None or not first:
                return False
            second, refusal = mint_task(ledger, "W")
            return second is None and refusal["reason"] == TASK_WORKER_BUSY


def rig_28_a_nudge_has_guards():
    """RIG-28. The nudge path exists with its three refusals, and health
    is read-only."""
    from nxb import rig
    names = ("RIG_PANE_BUSY", "RIG_NUDGE_THROTTLED", "RIG_NOTHING_TO_NUDGE")
    if not all(isinstance(getattr(rig, n, None), str) for n in names):
        return False
    if not callable(getattr(rig, "nudge", None)):
        return False
    return "send_line" not in inspect.getsource(rig.health)


def rig_29_collect_delivers_summary_plus_path():
    """RIG-29. A long filed answer comes back as its SUMMARY and a path."""
    import os
    from unittest import mock

    from nxb import keystroke
    from nxb.keystroke import collect_reply, file_reply, marked_directive
    from nxb.roster import Roster, RosterEntry
    from nxb.tasks import TaskRegistry
    if "SUMMARY:" not in marked_directive("t", "W", "x", ledger="/l", repo="/r"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        ledger = os.path.join(tmp, "l.db")
        reg = TaskRegistry(ledger)
        try:
            task, refusal = reg.mint("demo W", Roster([RosterEntry(
                "%1", name="demo W", alive=True, source="rig")]))
        finally:
            reg.close()
        if refusal:
            return False
        file_reply("demo W", task, "SUMMARY: fine.\n\n" + "x\n" * 5000,
                   ledger=ledger)
        pane = {"name": "demo W", "runtime": "codex", "pane": "%1",
                "enrolment": "typed"}
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "demo", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: ""):
            out = collect_reply("demo W", task, ledger=ledger)
        return (out.get("answer") == "fine." and not out.get("answer_inline")
                and os.path.isfile(out.get("answer_path", "")))


def rig_30_fresh_workers_are_pointed_at_a_bounded_state_note():
    """RIG-30. A state note is capped, and a directive names it when it
    exists."""
    import os

    from nxb.context import (CONTEXT_NOTE_TOO_BIG, STATE_CAP_CHARS, Vault,
                             orientation_line, state_key)
    from nxb.keystroke import marked_directive
    with tempfile.TemporaryDirectory() as tmp:
        ledger = os.path.join(tmp, "l.db")
        vault = Vault(ledger)
        try:
            if orientation_line(ledger, "demo") is not None:
                return False
            too_big = vault.put(state_key("demo"), "x" * (STATE_CAP_CHARS + 1))
            if too_big.get("reason") != CONTEXT_NOTE_TOO_BIG:
                return False
            vault.put(state_key("demo"), "what exists")
        finally:
            vault.close()
        line = orientation_line(ledger, "demo")
        if not line or "ORIENT FIRST" not in line:
            return False
        text = marked_directive("t", "demo W", "x", ledger=ledger, repo="/r",
                                orientation=line)
        return "ORIENT FIRST" in text and text.endswith(
            "it is how your answer is collected.")


def rig_31_checkpoint_gates_the_reset():
    """RIG-31. checkpoint_pane exists, its refusal is published, and the
    default ceiling is 100K on both runtimes."""
    import json
    import pathlib

    from nxb import rig
    root = pathlib.Path(__file__).resolve().parent.parent
    vocab = json.loads((root / "contract" / "rig.json").read_text())
    if rig.RIG_CHECKPOINT_UNCONFIRMED not in vocab["refusal_vocabulary"]:
        return False
    if not callable(getattr(rig, "checkpoint_pane", None)):
        return False
    src = inspect.getsource(rig.checkpoint_pane)
    # nxb-082.3 moved the reset into _finish_checkpoint; the gate is the same.
    src += inspect.getsource(getattr(rig, "_finish_checkpoint", rig.checkpoint_pane))
    if "RIG_CHECKPOINT_UNCONFIRMED" not in src or "reset_pane" not in src:
        return False
    return rig.DEFAULT_CONTEXT_LIMIT == {"claude_code": 100_000,
                                         "codex": 100_000}


def rig_32_the_vault_has_a_dashboard():
    """RIG-32. A new vault carries an Obsidian Base with views."""
    import os

    from nxb.context import BASE_FILENAME, Vault
    with tempfile.TemporaryDirectory() as tmp:
        vault = Vault(os.path.join(tmp, "l.db"))
        try:
            path = os.path.join(vault.root, BASE_FILENAME)
            if not os.path.exists(path):
                return False
            text = open(path, encoding="utf-8").read()
        finally:
            vault.close()
    return "views:" in text and "card" in text


def rig_33_maps_are_offered_and_named():
    """RIG-33. A map note is bounded, the brief asks for one, and the
    orientation line names it when it exists."""
    import os

    from nxb.context import (CONTEXT_NOTE_TOO_BIG, MAP_CAP_CHARS, Vault,
                             orientation_line, state_key)
    from nxb.enroll import orchestrator_rule
    if "context map --session s" not in orchestrator_rule(
            "O", ledger="/l", repo="/r", session="s"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        ledger = os.path.join(tmp, "l.db")
        vault = Vault(ledger)
        try:
            if vault.put("maps/p", "x" * (MAP_CAP_CHARS + 1)).get(
                    "reason") != CONTEXT_NOTE_TOO_BIG:
                return False
            vault.put(state_key("s"), "state")
            vault.put("maps/p", "modules")
        finally:
            vault.close()
        line = orientation_line(ledger, "s", "/any/p") or ""
    return "maps/p.md" in line


def rig_34_rig_panes_get_the_core_tool_set():
    """RIG-34. A Claude rig pane launches with the core tools by default,
    and `tools: all` widens it."""
    import os

    from nxb.rig import launch_command
    with tempfile.TemporaryDirectory() as tmp:
        default, _, _ = launch_command(
            {"name": "W", "runtime": "claude_code", "role": "worker"},
            ledger=os.path.join(tmp, "l.db"), repo="/r")
        widened, _, _ = launch_command(
            {"name": "W", "runtime": "claude_code", "role": "worker",
             "tools": "all"}, ledger=os.path.join(tmp, "l.db"), repo="/r")
    return ("--tools Bash,Read,Edit,Write,Glob,Grep" in default
            and "--tools" not in widened)


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}


def rig_35_a_live_worker_is_not_superseded():
    """RIG-35. A supersede aimed at a worker whose transcript moved within
    five minutes is refused unless forced; WAITING carries last_activity_s."""
    import inspect

    from nxb import keystroke, minting
    if not hasattr(keystroke, "last_activity_s"):
        return False
    if minting.TASK_WORKER_ACTIVE != "task_worker_active":
        return False
    if minting.ACTIVE_WITHIN_S < 60:
        return False
    src = inspect.getsource(keystroke._collect_once)
    vocab = json.loads((_ROOT / "contract" / "roster.json").read_text())
    return ("last_activity_s" in src
            and "task_worker_active" in vocab["refusal_vocabulary"]
            and "force" in inspect.signature(minting.mint_task).parameters)


def rig_36_the_checkpoint_pass_holds():
    """RIG-36. Owed resets, one clock per pass, idle wait before reset, a
    cap above the request, a stamp that survives, a width-proof marker."""
    from nxb import context, rig
    from nxb.enroll import orchestrator_rule
    if not all(hasattr(rig, n) for n in
               ("_owed_reset", "_await_idle", "_plan_checkpoint",
                "_finish_checkpoint", "CHECKPOINT_NOTE_FRESH_S",
                "CHECKPOINT_IDLE_DEADLINE_S")):
        return False
    if context.CHECKPOINT_HARD_CAP_CHARS <= context.CHECKPOINT_CAP_CHARS:
        return False
    if "Ask Codex" not in rig.READY_MARKERS["codex"]:
        return False
    brief = orchestrator_rule("O", ledger="/l", repo="/r", session="s")
    return ("rig checkpoint --session s --worker" in brief
            and "rig usage --session s" in brief)



def rig_37_a_narrow_pane_reads_busy():
    """RIG-37. The spinner line and a truncated footer both read busy."""
    from nxb.keystroke import busy_screen
    return (busy_screen("✳ Seasoning… (17m 10s · ↓ 14.1k tokens)")
            and busy_screen("⏵⏵ bypass permissions on · 1 shell · esc to inte…")
            and not busy_screen("✻ Worked for 14s · done 11:27 PM"))



def rig_38_the_rig_reports_its_own_cost():
    """RIG-38. Window pinned, widths in health, stalls in the watch line,
    duration and checkpoints on a collected task."""
    import inspect

    from nxb import context, rig
    from nxb.keystroke import PANE_RECORD_KEYS
    src = inspect.getsource(rig._build_window)
    return ("window-size" in src and "resize-window" in src
            and hasattr(rig, "_stalls") and hasattr(rig, "_pane_widths")
            and callable(getattr(context, "task_cost", None))
            and "checkpoints" in PANE_RECORD_KEYS)



def rig_39_a_clear_is_proven_and_requests_never_stack():
    """RIG-39. Pending requests wait; queued messages read busy; a Claude
    reset needs a rotated session id."""
    from nxb import rig
    from nxb.keystroke import busy_screen
    vocab = json.loads((_ROOT / "contract" / "rig.json").read_text())
    return (rig.RIG_RESET_UNCONFIRMED in vocab["refusal_vocabulary"]
            and hasattr(rig, "CHECKPOINT_PENDING_S")
            and busy_screen("❯ Press up to edit queued messages"))



def rig_40_one_pane_relaunches_in_place():
    """RIG-40. rig relaunch exists, replaces the process with respawn-pane,
    and its refusal is published."""
    import inspect

    from nxb import rig
    if not callable(getattr(rig, "relaunch_pane", None)):
        return False
    src = inspect.getsource(rig.relaunch_pane)
    vocab = json.loads((_ROOT / "contract" / "rig.json").read_text())
    return ("respawn-pane" in src and "launch_command" in src
            and rig.RIG_RELAUNCH_UNCONFIRMED in vocab["refusal_vocabulary"])


def _zero_reads_zero():
    """fullness() must tell a reading of zero from a missing reading."""
    from nxb import gauge
    real = gauge.pane_context
    try:
        gauge.pane_context = lambda entry: {"tokens": 0, "fresh": True}
        return gauge.fullness({"context_limit": 140_000}) == (0, 140_000, 0.0)
    finally:
        gauge.pane_context = real


def rig_41_a_fresh_pane_gauges_zero_not_unknown():
    """RIG-41. The registry is read by PANE ID, newest record wins, a
    vouched session with no transcript reads 0, and an unvouched one is
    still unknown."""
    from nxb.gauge import pane_context
    from nxb.roster import session_registry_panes
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "77.json").write_text(json.dumps(
            {"pid": 77, "sessionId": "fresh-one", "name": "Builder 1",
             "tmux": "rig:@1.%9", "startedAt": 2}))
        (root / "12.json").write_text(json.dumps(
            {"pid": 12, "sessionId": "dead-one", "name": "Builder 1",
             "tmux": "rig:@1.%9", "startedAt": 1}))
        if session_registry_panes(str(root)) != {"%9": "fresh-one"}:
            return False
    unvouched = pane_context({"runtime": "claude_code", "pane": "%no-pane",
                              "session_id": "no-session-of-this-name",
                              "context_limit": 140_000})
    if unvouched.get("tokens") is not None:
        return False
    return _cleared_reads_zero() and _newest_transcript_wins() \
        and _zero_reads_zero()


def _cleared_reads_zero():
    """`/clear` writes a transcript holding only metadata; that is zero."""
    from nxb import gauge
    meta = ('{"type":"custom-title","customTitle":"Builder 1"}\n'
            '{"type":"agent-name","agentName":"Builder 1"}\n'
            '{"type":"mode","mode":"normal"}\n')
    real = gauge._claude_transcript
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "cleared.jsonl"
        path.write_text(meta)
        try:
            gauge._claude_transcript = lambda sid: str(path)
            reading = gauge.pane_context({"runtime": "claude_code",
                                          "session_id": "cleared"})
        finally:
            gauge._claude_transcript = real
    return reading.get("tokens") == 0 and reading.get("fresh") is True


def _newest_transcript_wins():
    """Record and registry both name a session; the newer file is live."""
    from nxb import gauge
    turn = ('{"type":"assistant","message":{"usage":'
            '{"input_tokens":%d,"cache_read_input_tokens":0}}}\n')
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "old.jsonl").write_text(turn % 90000)
        (root / "new.jsonl").write_text(turn % 1234)
        os.utime(root / "old.jsonl", (1, 1))
        real_t, real_p = gauge._claude_transcript, None
        from nxb import roster
        real_p = roster.session_registry_panes
        try:
            gauge._claude_transcript = lambda sid: (
                str(root / f"{sid}.jsonl")
                if (root / f"{sid}.jsonl").exists() else None)
            roster.session_registry_panes = lambda *a, **k: {"%1": "new"}
            entry = {"runtime": "claude_code", "pane": "%1",
                     "session_id": "old"}
            reading = gauge.pane_context(entry)
        finally:
            gauge._claude_transcript = real_t
            roster.session_registry_panes = real_p
    return reading.get("tokens") == 1234 and entry["session_id"] == "new"


def rig_42_the_watch_line_reports_the_machine():
    """RIG-42. health carries a machine block, the watch line prints one,
    narrow panes name their client, and `warn` alone is not an alarm."""
    from nxb import machine, rig
    calm = {"pressure": 2, "pressure_name": "warn", "swap_used_gb": 2.8,
            "load1": 3.5, "cores": 10, "free_gb": 3.0, "simulators": 1,
            "companions": 8}
    swamped = dict(calm, swap_used_gb=25.0, load1=14.2)
    if machine.strained(calm) or not machine.strained(swamped):
        return False
    if "orphan companion" not in machine.line(calm):
        return False
    if "MACHINE STRAINED" not in machine.line(dict(swamped, strained=True)):
        return False
    if not callable(getattr(machine, "clients", None)):
        return False
    return ("machine.snapshot" in inspect.getsource(rig.health)
            and "machine.line" in inspect.getsource(rig.watch)
            and "narrow panes" in inspect.getsource(rig.watch))


def rig_43_a_rising_pane_is_asked_before_the_line():
    """RIG-43. The measured 11:50 to 11:54 AM sequence: silent at 43
    percent, firing at 72, silent when steady, and the plan bypasses the
    level test but never the nothing-outstanding test."""
    import time as _time

    from nxb import rig
    ceiling, now = 140_000, _time.monotonic()
    line = ceiling * rig._effective_threshold(ceiling, rig.CHECKPOINT_THRESHOLD)
    history = {}
    if rig._rising_past_the_line("B1", 60_200, line, 0.43, history):
        return False                       # 43 percent: room for a pass
    history["B1"] = (60_200, now - 60)
    if not rig._rising_past_the_line("B1", 100_800, line, 0.72, history):
        return False                       # 72 percent, 40K a minute: ask
    history["B1"] = (100_800, now - 60)
    if rig._rising_past_the_line("B1", 101_000, line, 0.72, history):
        return False                       # steady at 72 percent: leave it
    if rig._rising_past_the_line("B1", 60_200, line, 0.43,
                                 {"B1": (20_000, now - 60)}):
        return False                       # fast but under the floor
    # RIG-46, the class of fire the correction removes. Constructed, not
    # measured: a pane at 59 percent, the fraction two of the six spurious
    # fires happened at, rising 15K a minute. The old rule projected that
    # to the CEILING over four minutes, 142,600, and asked. The corrected
    # rule projects one pass to the ASK-LINE, 97,600 against 105,000, and
    # leaves it alone, because the 35K it would have reserved twice is
    # already reserved once by _effective_threshold.
    if rig._rising_past_the_line("B2", 82_600, line, 0.59,
                                 {"B2": (67_600, now - 60)}):
        return False
    if 82_600 + 250 * 240 < ceiling:       # the old rule really did fire
        return False
    src = inspect.getsource(rig._plan_checkpoint)
    return (rig.CHECKPOINT_HORIZON_S >= 60.0
            and 0.0 < rig.CHECKPOINT_RATE_FLOOR < rig.CHECKPOINT_THRESHOLD
            and "not rising and (fraction is None" in src
            and 'if not held and entry.get("role") != "orchestrator" '
                'and not force:' in src)


def rig_44_the_threshold_allows_for_the_ask():
    """RIG-44. Every ceiling with room for it is asked early enough that
    the measured cost of the ask still lands under the ceiling."""
    from nxb.rig import (CHECKPOINT_RATE_FLOOR, CHECKPOINT_REQUEST_COST,
                         CHECKPOINT_THRESHOLD, _effective_threshold)
    if CHECKPOINT_REQUEST_COST < 30_000:
        return False                       # measured at 33K and 43K
    for limit in (100_000, 140_000, 150_000, 160_000, 258_400):
        ask = _effective_threshold(limit, CHECKPOINT_THRESHOLD)
        if ask > CHECKPOINT_THRESHOLD or ask < CHECKPOINT_RATE_FLOOR:
            return False
        if ask * limit + CHECKPOINT_REQUEST_COST > limit + 1:
            return False                   # still over when it resets
    # A ceiling too small for the ask is floored, not driven to nothing.
    if _effective_threshold(40_000, CHECKPOINT_THRESHOLD) \
            != CHECKPOINT_RATE_FLOOR:
        return False
    return _effective_threshold(None, CHECKPOINT_THRESHOLD) \
        == CHECKPOINT_THRESHOLD


def rig_45_a_late_clear_does_not_strand_a_worker():
    """RIG-45. The continuation is separable from the reset, an unproven
    clear drops the pending stamp, and a stranded pane is derived from
    state: fresh, unasked, holding a task, note newer than the reset."""
    from nxb import rig
    from nxb.keystroke import PANE_RECORD_KEYS
    if not callable(getattr(rig, "_continue_from_note", None)):
        return False
    if "reset_unproven_at" not in PANE_RECORD_KEYS:
        return False
    finish = inspect.getsource(rig._finish_checkpoint)
    if ("RIG_RESET_UNCONFIRMED" not in finish
            or "clear=True" not in finish
            or "_note_unproven_reset" not in finish):
        return False
    plan = inspect.getsource(rig._plan_checkpoint)
    owed = inspect.getsource(rig._continuation_owed)
    # Derived from state, and checked BEFORE the pending stamp can block it.
    if plan.index("_continuation_owed") > plan.index("CHECKPOINT_PENDING_S"):
        return False
    if not all(clause in owed for clause in
               ('reading.get("fresh")', 'reading.get("asked")',
                "CONTINUATION_OWED_AFTER_S", "_is_busy")):
        return False
    return (rig.CONTINUATION_OWED_AFTER_S >= 60.0
            and rig.CONTINUATION_OWED_AFTER_S < rig.CHECKPOINT_NOTE_FRESH_S
            and 'plan["action"] == "continue"'
            in inspect.getsource(rig.checkpoint_rig))


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}
