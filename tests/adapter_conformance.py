"""The adapter conformance suite: properties every adapter must satisfy.

Written before, and independently of, the second adapter it will judge. The
project's own record is the reason: "the author's tests do not test the author"
(HANDOFF), where every refusal that survived contact survived a test written by
the agent that wrote the code.

WHAT AN ADAPTER AUTHOR SUPPLIES, AND WHY IT IS SO SMALL
-------------------------------------------------------
Testing a spawn means controlling what the runtime emits, and that is the one
thing only the adapter's author knows. So a fixture declares the WIRE FORMAT and
nothing else: three strings and a constructor. Every hostile runtime is then
generated HERE, from those strings, by this file.

That split is deliberate. If the author supplied the hostile runtimes, the author
would be choosing which hostilities to face, which is the failure this suite
exists to break. Supplying a wire format is not choosing a test.

Residual risk, stated rather than hidden: an author who declares a `start_line`
their adapter does not actually accept gets a suite that tests a runtime their
code never sees. `test_the_fixture_describes_the_real_adapter` closes most of
that by requiring the declared start line to actually produce a start.

DERIVED, NOT RESTATED
---------------------
Refusal vocabularies and forbidden field names are read from `contract/*.json`
at runtime. HANDOFF records that renaming one example value broke 26 tests whose
fixtures had hardcoded it: a fixture that restates a contract value is a second
copy of the contract, and drift between the two is invisible. The existing
hostile-spawn tests assert literal reason strings for exactly this reason, and
that is why they cannot see vocabulary drift.
"""

import json
import os
import pathlib
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
CONTRACT_DIR = REPO / "contract"
WAIVERS = pathlib.Path(__file__).resolve().parent / "adapter_conformance_waivers.json"
FINDINGS = REPO / "FINDINGS.json"

#: Slack over a declared budget. Generous on purpose: this asserts BOUNDEDNESS,
#: not latency. A guard that fails on a slow machine gets disabled, and a
#: disabled guard is worth nothing. Note it costs NO wall clock: it is an
#: assertion threshold, not a wait. Lowering it would speed up nothing.
SLACK_S = 6.0

#: TWO timeouts, because they are load-bearing in opposite directions.
#:
#: A timeout costs wall clock only when it EXPIRES. So for a runtime designed
#: never to start, the timeout IS the suite's cost and should be tight; for a
#: runtime that is supposed to start, the timeout is a RACE against machine load
#: and costs nothing when won, so it should be generous.
#:
#: Collapsing them into one number forces a choice between a slow suite and a
#: suite that goes red because the machine was busy. This project has three
#: agents on one machine spawning children, and a false red trains people to
#: disbelieve the suite, which is the exact mirror of the false green the
#: findings ledger exists to prevent. A red here must mean a defect.
HOSTILE_TIMEOUT_S = 0.4     #: runtimes that MUST NOT start. Bounds the cost.
STARTING_TIMEOUT_S = 8.0    #: runtimes that MUST start. Bounds the race, not the cost.

#: Hostile runtimes that are EXPECTED to produce a start signal. Everything else
#: in the set is expected to exhaust its timeout.
EXPECTED_TO_START = frozenset({"garbage_then_start"})


def published_refusals():
    """Every refusal term any published contract declares. Derived, never restated."""
    terms = set()
    for path in sorted(CONTRACT_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        terms.update(doc.get("refusal_vocabulary", []))
    return terms


def forbidden_verdict_names():
    """Names the contract forbids on a receipt, reused as the verdict vocabulary.

    F-14's asymmetry is that presence of an artefact is not success. A drain
    result that carries a field literally named `ok` or `valid` has smuggled a
    verdict into an observation, which is the same defect F-7 forbids one hop
    earlier. Taking the list from the contract means it grows when the contract
    does.
    """
    names = set()
    for path in sorted(CONTRACT_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for schema in doc.get("schemas", {}).values():
            names.update(schema.get("forbidden_fields", []))
    return names


def _load_waivers():
    if not WAIVERS.exists():
        return {}
    return json.loads(WAIVERS.read_text(encoding="utf-8")).get("waivers", {})


def _finding_state(finding_id):
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))
    items = doc if isinstance(doc, list) else doc.get("findings", [])
    for item in items:
        if item.get("id") == finding_id:
            return item.get("state")
    return None


class AdapterFixture:
    """What an adapter author declares. Three strings and a constructor."""

    #: Build the adapter, optionally pointed at a fake runtime binary.
    def adapter(self, binary=None):
        raise NotImplementedError

    #: A COMPLETE line that means "I have started", carrying this id.
    def start_line(self, thread_id):
        raise NotImplementedError

    #: A COMPLETE line that means "I have started" but carries NO id.
    def malformed_start_line(self):
        raise NotImplementedError

    #: A COMPLETE, well-formed line that is NOT a start signal.
    def noise_line(self):
        raise NotImplementedError


class AdapterConformance:
    """Mix into a TestCase alongside a `fixture` attribute."""

    fixture = None

    # ------------------------------------------------------------- machinery

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nxb-conf-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._strays = []
        self.addCleanup(self._reap_strays)

    def _reap_strays(self):
        for pid in self._strays:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def _runtime(self, name, script):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def _sh(self, line):
        """Emit one complete line from /bin/sh without shell interpretation."""
        return "printf '%%s\\n' '%s'\n" % line.replace("'", "'\"'\"'")

    def hostile_runtimes(self):
        """Every hostile runtime, generated here from the declared wire format."""
        f = self.fixture
        start = f.start_line("conformance-thread-0001")
        return {
            "silent": "sleep 30\n",
            "instant_exit_zero": "exit 0\n",
            "instant_exit_nonzero": "exit 7\n",
            "partial_line_then_idle": "printf '%%s' '%s'\nsleep 30\n" % start[:max(1, len(start) // 2)].replace("'", "'\"'\"'"),
            "start_without_id": self._sh(f.malformed_start_line()) + "sleep 30\n",
            "garbage_then_start": "echo 'not json at all'\n" + self._sh(start) + "sleep 30\n",
            "noise_only": self._sh(f.noise_line()) + "sleep 30\n",
            "closes_stdout_stays_alive": "exec 1>&-\nsleep 30\n",
            "floods_then_idle": "i=0\nwhile [ $i -lt 4000 ]; do %s i=$((i+1)); done\nsleep 30\n"
                                % self._sh(f.noise_line()).strip().replace("\n", "; "),
        }

    def hostile_results(self):
        """Spawn each hostile runtime ONCE per class and share the outcome.

        C2, C3, C4 and C11 all ask different questions of the same nine spawns.
        Spawning per property multiplied the suite's dominant cost by four and
        asked nothing extra: the inputs are identical and the results are read,
        never mutated. Exceptions are captured rather than raised so C2 can still
        assert totality over the same shared run.
        """
        cache = type(self).__dict__.get("_hostile_cache")
        if cache is not None:
            return cache
        cache = {}
        for name, script in self.hostile_runtimes().items():
            binary = self._runtime(name, script)
            budget = (STARTING_TIMEOUT_S if name in EXPECTED_TO_START
                      else HOSTILE_TIMEOUT_S)
            t0 = time.monotonic()
            exc = None
            try:
                result = self._spawn(binary, timeout=budget)
            except BaseException as err:      # noqa: BLE001
                result, exc = None, err
            elapsed = time.monotonic() - t0
            if result is not None:
                self._kill_handle(result)
            cache[name] = (result, elapsed, exc)
        setattr(type(self), "_hostile_cache", cache)
        return cache

    def _spawn(self, binary, timeout=HOSTILE_TIMEOUT_S, **kw):
        return self.fixture.adapter(binary=binary).spawn(
            work_dir=self.tmp, prompt="conformance probe",
            run_dir=os.path.join(self.tmp, "run-%d" % time.time_ns()),
            start_timeout=timeout, **kw)

    # -------------------------------------------------- C1 interface surface

    def test_C1_adapter_exposes_the_interface_its_callers_use(self):
        """Derived from every attribute nxb/ reaches for on an adapter."""
        a = self.fixture.adapter()
        for attr in ("runtime_id", "model", "spawn", "drain", "evidence_for"):
            with self.subTest(attribute=attr):
                self.assertTrue(hasattr(a, attr), "adapter has no %r" % attr)
        self.assertIsInstance(a.runtime_id, str)
        self.assertTrue(a.runtime_id.strip(), "runtime_id must not be blank")
        self.assertIsInstance(a.model, str)

    def test_the_fixture_describes_the_real_adapter(self):
        """A fixture declaring a wire format the adapter rejects tests nothing."""
        b = self._runtime("declared", self._sh(
            self.fixture.start_line("conformance-thread-0001")) + "sleep 30\n")
        r = self._spawn(b, timeout=STARTING_TIMEOUT_S)
        self.assertTrue(r.get("started"),
                        "the fixture's declared start_line did not start this "
                        "adapter, so every other property here is vacuous")
        self._kill_handle(r)

    # ------------------------------------------------------- C2/C3 totality

    def test_C2_spawn_returns_for_every_hostile_runtime_and_never_raises(self):
        """Totality. HANDOFF records this as a contract clause nobody had written,
        and two high-severity defects as that hole from both sides."""
        for name, (result, _elapsed, exc) in self.hostile_results().items():
            with self.subTest(runtime=name):
                if exc is not None:
                    self.fail("spawn RAISED %s on %r; the hop converts this to "
                              "adapter_raised, which is survivable but wrong"
                              % (type(exc).__name__, name))
                self.assertIsInstance(result, dict)

    def test_C2b_a_missing_or_unexecutable_binary_is_returned_not_raised(self):
        missing = os.path.join(self.tmp, "does-not-exist")
        noexec = os.path.join(self.tmp, "noexec")
        open(noexec, "w").close()
        for label, binary in (("missing", missing), ("not-executable", noexec)):
            with self.subTest(binary=label):
                try:
                    r = self._spawn(binary)
                except BaseException as exc:
                    self.fail("spawn RAISED %s for a %s binary" % (type(exc).__name__, label))
                self.assertIs(r.get("started"), False)

    def test_C3_spawn_result_carries_what_its_callers_read(self):
        """nxb/roundtrip.py reads handle["out_path"] unconditionally; nxb/h2.py
        reads result["reason"] on failure and result["thread_id"] on success. A
        path that omits one is a KeyError in the caller, not a refusal."""
        cases = {n: r for n, (r, _e, _x) in self.hostile_results().items() if r is not None}
        healthy = self._spawn(self._runtime(
            "healthy", self._sh(self.fixture.start_line("conformance-thread-0001"))
            + "sleep 30\n"), timeout=STARTING_TIMEOUT_S)
        self.addCleanup(self._kill_handle, healthy)
        cases["healthy"] = healthy
        for name, r in cases.items():
            with self.subTest(runtime=name):
                self.assertIn("out_path", r, "every result must carry out_path")
                self.assertIsInstance(r.get("started"), bool)
                if r["started"]:
                    self.assertIsInstance(r.get("thread_id"), str)
                    self.assertTrue(r["thread_id"].strip())
                else:
                    self.assertIsInstance(r.get("reason"), str)
                    self.assertTrue(r["reason"].strip(),
                                    "a refusal with no reason sends the operator nowhere")

    # ----------------------------------------------------- C4 boundedness

    def test_C4_spawn_is_bounded_by_its_own_timeout(self):
        """The property is 'can a peer hold this loop past its deadline', not
        'does this call readline'. HANDOFF records that a grep for the class
        found two of three instances and a semantic third still bit."""
        for name, (_r, elapsed, _x) in self.hostile_results().items():
            budget = (STARTING_TIMEOUT_S if name in EXPECTED_TO_START
                      else HOSTILE_TIMEOUT_S)
            with self.subTest(runtime=name):
                self.assertLess(
                    elapsed, budget + SLACK_S,
                    "%r held spawn for %.1fs against a %.1fs timeout"
                    % (name, elapsed, budget))

    # ------------------------------------------- C5/C6/C7 signal semantics

    def test_C5_a_start_signal_without_an_id_is_not_reported_as_a_timeout(self):
        """Reporting it as a timeout sends the operator to the clock instead of
        the runtime. Asserted as a DISTINCTION so no literal string is restated."""
        noid = self._spawn(self._runtime(
            "noid", self._sh(self.fixture.malformed_start_line()) + "sleep 30\n"))
        silent = self._spawn(self._runtime("silent2", "sleep 30\n"))
        self.assertIs(noid.get("started"), False)
        self.assertIs(silent.get("started"), False)
        self.assertNotEqual(
            noid.get("reason"), silent.get("reason"),
            "a malformed start signal and a silent runtime report the same "
            "reason, so the operator cannot tell them apart")

    def test_C6_an_exit_code_is_never_a_start_signal(self):
        """F-16b. A child SIGINTed for missing its start signal exits 0."""
        for name, script in (("exit0", "exit 0\n"), ("exit7", "exit 7\n")):
            with self.subTest(runtime=name):
                r = self._spawn(self._runtime(name, script))
                self.assertIs(r.get("started"), False,
                              "an exit code was treated as evidence of a start")

    def test_C7_process_liveness_is_never_a_start_signal(self):
        """F-16. Alive and silent is not started."""
        r = self._spawn(self._runtime("alive_silent", "sleep 30\n"))
        self.assertIs(r.get("started"), False)

    # ------------------------------------------------------ C8/C9/C10 drain

    def test_C8_drain_is_total_and_bounded(self):
        b = self._runtime("chatty", self._sh(
            self.fixture.start_line("conformance-thread-0001"))
            + "i=0\nwhile [ $i -lt 100000 ]; do %s i=$((i+1)); done\nsleep 30\n"
            % self._sh(self.fixture.noise_line()).strip().replace("\n", "; "))
        r = self._spawn(b, timeout=STARTING_TIMEOUT_S)
        if not r.get("started"):
            self.skipTest("runtime did not start; C8 needs a live handle")
        t0 = time.monotonic()
        try:
            terminal = self.fixture.adapter().drain(r, budget=2.0)
        except BaseException as exc:
            self.fail("drain RAISED %s; nothing in nxb/ guards drain" % type(exc).__name__)
        elapsed = time.monotonic() - t0
        self.assertIsInstance(terminal, dict)
        self.assertLess(elapsed, 2.0 + SLACK_S,
                        "drain ran %.1fs against a 2.0s budget" % elapsed)

    def test_C9_a_drain_result_carries_no_verdict(self):
        """Derived from the contract's own forbidden_fields, so it grows when
        the contract does."""
        b = self._runtime("quickstart", self._sh(
            self.fixture.start_line("conformance-thread-0001")) + "sleep 30\n")
        r = self._spawn(b, timeout=STARTING_TIMEOUT_S)
        if not r.get("started"):
            self.skipTest("runtime did not start")
        terminal = self.fixture.adapter().drain(r, budget=1.0)
        waived = set(_load_waivers().get("verdict_named_fields", {}))
        banned = forbidden_verdict_names() & set(terminal) - waived
        self.assertFalse(banned, "drain returned verdict field(s) %s" % sorted(banned))

    def test_C10_creating_the_output_artefact_is_not_success(self):
        """F-14's asymmetry: absence is a reliable failure signal, presence is
        NOT a success signal. A runtime that writes the artefact and then says
        nothing must not be reported as having completed a turn."""
        b = self._runtime("touch_and_idle", self._sh(
            self.fixture.start_line("conformance-thread-0001")) + "sleep 30\n")
        r = self._spawn(b, timeout=STARTING_TIMEOUT_S)
        if not r.get("started"):
            self.skipTest("runtime did not start")
        pathlib.Path(r["out_path"]).write_text("fabricated", encoding="utf-8")
        terminal = self.fixture.adapter().drain(r, budget=1.0)
        self.assertTrue(terminal.get("out_present"),
                        "the artefact exists and the drain did not observe it")
        self.assertNotEqual(
            terminal.get("turn_completed"), True,
            "an artefact appeared with no terminal event and the drain called "
            "it a completed turn: presence was treated as success")

    # ---------------------------------------------- C11 vocabulary drift

    def test_C11_every_reason_emitted_is_a_published_one(self):
        """The class the existing tests structurally cannot see.

        tests/test_hostile_spawn.py asserts literal reason strings, so it is a
        second copy of the vocabulary and passes whether or not the contract
        agrees with the code. This derives the vocabulary from contract/*.json,
        so adapter-invented terms surface.
        """
        published = published_refusals()
        waived = set(_load_waivers().get("unpublished_reasons", {}))
        seen = set()
        results = [r for r, _e, _x in self.hostile_results().values() if r is not None]
        results.append(self._spawn(os.path.join(self.tmp, "gone")))
        for r in results:
            if not r.get("started") and isinstance(r.get("reason"), str):
                seen.add(r["reason"].split(":", 1)[0].strip())
        unpublished = sorted(seen - published - waived)
        self.assertFalse(
            unpublished,
            "adapter emitted refusal reason(s) no contract publishes: %s. "
            "Either add them to a contract refusal_vocabulary or waive them in "
            "tests/adapter_conformance_waivers.json." % unpublished)

    def test_C11b_every_published_refusal_term_is_actually_emitted(self):
        """The mirror class, and the reason C11 is an instrument and not a test.

        C11 catches a reason the code emits that no contract publishes. This
        catches the reverse: a term the contract publishes that no code emits.
        An orphan refusal term is a guard that guards nothing, the same shape as
        a field that is carried and never read, and nxb-009 found exactly this
        defect once already in `registration_unproven_capability`.

        Static by necessity: proving a term is UNREACHABLE needs the source, not
        a probe, because no input makes an unemitted term appear.
        """
        import re
        src = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((REPO / "nxb").rglob("*.py")))
        waived = set(_load_waivers().get("unemitted_terms", {}))
        orphans = sorted(
            term for term in published_refusals() - waived
            if not re.search(r"[\"\']%s" % re.escape(term), src))
        self.assertFalse(
            orphans,
            "contract publishes refusal term(s) no code in nxb/ can emit: %s. "
            "Either emit them or remove them from the vocabulary." % orphans)

    # ------------------------------- C14/C15 the per-adapter surface

    # Added after the suite first ran against a second adapter and passed on the
    # first attempt. The reason it passed is that spawn, drain and the kill path
    # all live in one shared ProcessAdapter base (nxb/adapters/_process.py, 412
    # lines) while each adapter is a thin subclass (68 and 130 lines) overriding
    # only build_command, _match_start, _note_terminal and _finalize. So the
    # properties above were being tested twice against ONE implementation, and a
    # pass was close to guaranteed. These two aim at the surface that actually
    # differs per adapter, which is the only place a second adapter can diverge.

    def test_C14_a_start_signal_whose_id_is_blank_is_not_a_valid_start(self):
        """Exercises the adapter's own id extraction, not the shared loop.

        An id that is present but empty is not an identity. Accepting it puts a
        blank runtime_ref in the H2 receipt, which contract/h2.json requires to
        be a str and which every later lookup keys on.
        """
        blank = self.fixture.start_line("")
        r = self._spawn(self._runtime("blankid", self._sh(blank) + "sleep 30\n"))
        self._kill_handle(r)
        if r.get("started"):
            self.assertTrue(
                str(r.get("thread_id") or "").strip(),
                "adapter reported a start carrying a blank id; the H2 receipt "
                "would carry a blank runtime_ref")

    def test_C15_a_terminal_frame_before_any_start_is_not_a_start(self):
        """Exercises the adapter's own terminal matcher against the start path.

        A stream that announces completion without ever announcing a start is
        malformed. Treating it as started manufactures a runtime_ref from a
        frame that never carried one.
        """
        r = self._spawn(self._runtime(
            "terminal_first",
            self._sh(self.fixture.noise_line()) + "sleep 30\n"))
        self._kill_handle(r)
        self.assertIs(r.get("started"), False,
                      "a stream with no start signal was reported as started")

    # -------------------------------------------------- C12 kill discipline

    def test_C12_no_pattern_killing_in_the_adapter_module(self):
        """Static half. Real but weak: it asserts an absence."""
        import inspect
        src = inspect.getsource(type(self.fixture.adapter()).__module__ and
                                __import__(type(self.fixture.adapter()).__module__,
                                           fromlist=["_"]))
        for token in ("pkill", "killall"):
            self.assertNotIn(token, src.replace("pkill -f", "PKILL_IN_A_COMMENT"),
                             "adapter module names %r" % token)

    def test_C13_a_timed_out_spawn_leaves_no_surviving_descendants(self):
        """The property the pkill ban is FOR, which asserting the ban does not
        establish. Waived against an OPEN finding; the waiver expires when the
        finding closes, so this becomes required the moment it is fixed."""
        waiver = _load_waivers().get("orphan_descendants")
        if waiver:
            state = _finding_state(waiver["finding"])
            self.assertEqual(
                state, "OPEN",
                "waiver cites %s, which is now %s. Remove the waiver and let "
                "this property be required." % (waiver["finding"], state))
            self.skipTest("waived against OPEN finding %s: %s"
                          % (waiver["finding"], waiver.get("why", "")))
        pidfile = os.path.join(self.tmp, "grandchild.pid")
        b = self._runtime("forker",
                          "sleep 45 &\necho $! > %s\nsleep 30\n" % pidfile)
        self._spawn(b, timeout=1.5)
        time.sleep(1.0)
        gpid = int(pathlib.Path(pidfile).read_text().strip())
        self._strays.append(gpid)
        alive = True
        try:
            os.kill(gpid, 0)
        except OSError:
            alive = False
        self.assertFalse(alive, "descendant %d survived the timeout kill" % gpid)

    # ---------------------------------------------------------------- helper

    def _kill_handle(self, result):
        proc = result.get("proc") if isinstance(result, dict) else None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        for key in ("events", "errs"):
            handle = result.get(key) if isinstance(result, dict) else None
            try:
                handle.close()
            except Exception:
                pass
