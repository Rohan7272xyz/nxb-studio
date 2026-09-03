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
    return "rig_sessions" in (root / "nxb" / "__main__.py").read_text()


CHECKS = {name: obj for name, obj in list(globals().items())
          if callable(obj) and not name.startswith("_") and name.islower()
          and getattr(obj, "__module__", None) == __name__}
