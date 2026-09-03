"""nxb-050: the pane rig. Mostly offline; the live path is proven by hand."""

import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import types
import unittest

from nxb import rig

ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONTRACT = json.loads((ROOT / "contract" / "rig.json").read_text())


class TheScenarioIsRohansSpec(unittest.TestCase):
    def test_scenario2_is_one_orchestrator_and_four_workers(self):
        panes = rig.SCENARIOS["scenario2"]["panes"]
        self.assertEqual(len(panes), 5)
        roles = [p["role"] for p in panes]
        self.assertEqual(roles.count("orchestrator"), 1)
        self.assertEqual(roles.count("worker"), 4)
        self.assertEqual(panes[0]["role"], "orchestrator",
                         "the orchestrator must be pane 0: main-horizontal "
                         "puts pane 0 on top and the rest in a row below")

    def test_the_orchestrator_is_codex_and_workers_are_two_of_each(self):
        panes = rig.SCENARIOS["scenario2"]["panes"]
        self.assertEqual(panes[0]["runtime"], "codex")
        workers = [p for p in panes if p["role"] == "worker"]
        self.assertEqual(
            sorted(p["runtime"] for p in workers),
            ["claude_code", "claude_code", "codex", "codex"])

    def test_every_pane_is_named(self):
        for pane in rig.SCENARIOS["scenario2"]["panes"]:
            self.assertTrue(pane["name"].strip())


class LaunchCommands(unittest.TestCase):
    def _cmd(self, runtime, role="worker"):
        # A REAL directory: the launch command now reads its rule from a
        # brief file, because a rule long enough to matter cannot survive a
        # pty's ~1024-byte line limit. [RIG-19]
        tmp = tempfile.mkdtemp()
        return rig.launch_command(
            {"name": "CC Worker 1", "runtime": runtime, "role": role},
            ledger=os.path.join(tmp, "x.db"), repo="/r")

    def test_a_claude_ORCHESTRATOR_gets_the_orchestrator_brief(self):
        """RIG-16. Role was honoured on the typed path and ignored here, so a
        Claude orchestrator would have launched carrying the WORKER rule --
        RIG-7 surviving on the branch nobody had exercised, because every rig
        so far happened to seat Codex in the orchestrator chair."""
        cmd, _, refusal = self._cmd("claude_code", role="orchestrator")
        self.assertIsNone(refusal)
        brief = cmd.split("$(cat '")[1].split("')")[0]
        with open(brief, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("ORCHESTRATOR of a live fleet", text)
        self.assertIn("python3 -m nxb mint", text,
                      "an orchestrator that cannot mint cannot orchestrate")

    def test_a_claude_WORKER_does_not_get_the_orchestrator_brief(self):
        cmd, _, _ = self._cmd("claude_code")
        brief = cmd.split("$(cat '")[1].split("')")[0]
        with open(brief, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("You are the worker named", text)
        self.assertNotIn("ORCHESTRATOR of a live fleet", text)

    def test_a_claude_pane_is_named_AND_enrolled_at_launch(self):
        cmd, enrolment, refusal = self._cmd("claude_code")
        self.assertIsNone(refusal)
        self.assertEqual(enrolment, "launch")
        self.assertIn("-n 'CC Worker 1'", cmd)
        self.assertIn("--append-system-prompt", cmd)

    def test_a_codex_pane_is_enrolled_by_TYPING_not_at_launch(self):
        """nxb-051. Codex still has no --append-system-prompt, so its LAUNCH
        line carries no rule; the rule is typed once the pane has a name.

        The kind is carried as a string rather than a boolean on purpose: a
        typed rule is a weaker KIND of barrier than a launch-bound one (RIG-3),
        and a boolean would erase exactly that difference.
        """
        cmd, enrolment, refusal = self._cmd("codex")
        self.assertIsNone(refusal)
        self.assertEqual(enrolment, "typed")
        self.assertNotIn("--append-system-prompt", cmd)
        self.assertNotIn("BEFORE ACTING", cmd)

    def test_the_two_enrolment_kinds_are_never_conflated(self):
        self.assertNotEqual(self._cmd("claude_code")[1], self._cmd("codex")[1])

    def test_an_unknown_runtime_refuses(self):
        cmd, _kind, refusal = self._cmd("nonesuch")
        self.assertIsNone(cmd)
        self.assertIsNotNone(refusal)


class ReadinessIsAMarkerNeverASleep(unittest.TestCase):
    def _state(self, screen, runtime):
        real = rig.capture
        rig.capture = lambda pane: screen
        try:
            return rig.pane_state("%0", runtime)
        finally:
            rig.capture = real

    def test_the_measured_ready_markers_match_real_screens(self):
        self.assertEqual(
            self._state("  gpt-5.6-sol max\n> Ask Codex to do anything\n",
                        "codex"), "READY")
        self.assertEqual(
            self._state("  bypass permissions on (shift+tab to cycle)",
                        "claude_code"), "READY")

    def test_an_empty_screen_is_NOT_ready(self):
        self.assertIsNone(self._state("", "codex"))

    def test_BOTH_runtimes_trust_prompts_are_recognised(self):
        """Measured: codex says 'Do you trust the contents of this directory',
        Claude says 'Quick safety check'. My first guess matched neither, and
        every Claude pane timed out sitting at a dialog nobody was reading."""
        self.assertEqual(
            self._state("Do you trust the contents of this directory?", "codex"),
            rig.RIG_TRUST_PROMPT)
        self.assertEqual(
            self._state("Quick safety check: Is this a project you created",
                        "claude_code"),
            rig.RIG_TRUST_PROMPT)

    def test_a_blocking_prompt_WINS_over_a_ready_marker(self):
        """Otherwise a screen showing both reads as ready and the rig types
        into a security dialog."""
        both = ("Do you trust the contents of this directory\n"
                "Ask Codex to do anything")
        self.assertEqual(self._state(both, "codex"), rig.RIG_TRUST_PROMPT)


class TheThreadIdIsTheAddress(unittest.TestCase):
    CONFIRM = ("• Session renamed to CX Worker 1. To resume this session run "
               "codex resume, then select CX Worker 1 "
               "(01a04b75-424c-7fe2-9e97-4f332768a9f3)")

    def _await(self, screen, name):
        real = rig.capture
        rig.capture = lambda pane: screen
        try:
            return rig.await_rename("%0", name, deadline=0.3, poll=0.05)
        finally:
            rig.capture = real

    def test_the_id_is_read_from_the_runtimes_own_confirmation(self):
        self.assertEqual(self._await(self.CONFIRM, "CX Worker 1"),
                         "01a04b75-424c-7fe2-9e97-4f332768a9f3")

    def test_a_UUID_SPLIT_ACROSS_A_WRAP_still_parses(self):
        """THE REGRESSION. Codex hard-wraps to the pane width, so in the narrow
        worker panes the UUID straddles a newline. tmux -J does not rejoin it.
        The id parsed in the wide top pane and failed in all four below, which
        looked like flakiness rather than a layout-dependent bug."""
        wrapped = ("• Session renamed to CX Worker 1. To resume this session\n"
                   "run codex resume, then select CX Worker 1 (01a04b75-424c-\n"
                   "7fe2-9e97-4f332768a9f3)")
        self.assertEqual(self._await(wrapped, "CX Worker 1"),
                         "01a04b75-424c-7fe2-9e97-4f332768a9f3")

    def test_a_confirmation_for_a_DIFFERENT_pane_is_not_accepted(self):
        self.assertIsNone(self._await(self.CONFIRM, "CX Worker 2"))

    def test_no_confirmation_yields_no_address(self):
        self.assertIsNone(self._await("Ask Codex to do anything", "CX Worker 1"))


class TheNameIndexIsAnAppendLog(unittest.TestCase):
    def test_the_LAST_binding_wins(self):
        """A thread gets a row per rename. Taking the first match resolves a
        name to a thread that has since been renamed away from it."""
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                         delete=False) as handle:
            for row in ({"id": "old", "thread_name": "Shared"},
                        {"id": "new", "thread_name": "Shared"}):
                handle.write(json.dumps(row) + "\n")
            path = handle.name
        try:
            self.assertEqual(
                rig.codex_thread_named("Shared", index_path=path), "new")
        finally:
            os.unlink(path)

    def test_a_missing_index_resolves_nothing_and_does_not_raise(self):
        self.assertIsNone(
            rig.codex_thread_named("X", index_path="/nope/none.jsonl"))


class TheRigIsNotASpawnFallback(unittest.TestCase):
    """roster.py forbids the BROKER spawning. The rig is the operator's own
    act. That stays true only while no dispatch path can reach it."""

    DISPATCH_MODULES = ("dispatch.py", "roundtrip.py", "h2.py", "h3.py",
                        "h4.py", "run.py", "mcp.py", "roster.py", "tasks.py")

    def test_no_dispatch_path_imports_the_rig(self):
        for name in self.DISPATCH_MODULES:
            path = ROOT / "nxb" / name
            if not path.exists():
                continue
            with self.subTest(module=name):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn("rig", alias.name.split("."))
                    elif isinstance(node, ast.ImportFrom):
                        self.assertNotIn("rig", (node.module or "").split("."))

    def test_the_rig_can_only_ever_execute_TMUX(self):
        """F-15b, checked as a PROPERTY rather than by grep.

        A pattern kill here would reach the operator's unrelated work; that is
        not hypothetical, it cost another worker's run in nxb-009. The first
        version of this test grepped the source for 'pkill' and failed on its
        own docstring saying not to use one -- a check that greps source tests
        file layout, not behaviour. So instead: every process this module can
        start is proven to be tmux, at every call site.
        """
        tree = ast.parse((ROOT / "nxb" / "rig.py").read_text())
        sites = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "run"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "subprocess"]
        self.assertEqual(len(sites), 1,
                         "more than one place can start a process")
        argv = sites[0].args[0]
        self.assertIsInstance(argv, ast.List)
        self.assertEqual(argv.elts[0].value, "tmux")
        self.assertTrue(any(isinstance(e, ast.Starred) for e in argv.elts))

    def test_teardown_targets_a_named_session(self):
        self.assertIn("kill-session", (ROOT / "nxb" / "rig.py").read_text())


class ThePublishedVocabulary(unittest.TestCase):
    def test_every_refusal_the_rig_emits_is_published(self):
        emitted = {v for k, v in vars(rig).items()
                   if k.startswith("RIG_") and isinstance(v, str)}
        published = set(_CONTRACT["refusal_vocabulary"])
        self.assertEqual(emitted - published, set())

    def test_the_contract_records_that_codex_cannot_be_enrolled(self):
        self.assertIn("runtime_cannot_enroll", json.dumps(_CONTRACT))


if __name__ == "__main__":
    unittest.main()


class BothRuntimesRunTheSamePosture(unittest.TestCase):
    """RIG-12. The Claude half was launched --yolo from the first day and the
    Codex half was launched --sandbox workspace-write. Two runtimes in one
    fleet had different powers and nobody had decided that; the operator found
    it. A guard, because this is exactly the drift a review catches once and a
    test catches every time."""

    def _cmd(self, runtime):
        import tempfile
        from nxb.rig import launch_command
        # A real ledger dir: enroll_command WRITES the brief the command
        # reads, because a rule long enough to matter cannot be typed. [RIG-19]
        tmp = tempfile.mkdtemp()
        cmd, _, refusal = launch_command(
            {"name": "W", "runtime": runtime},
            ledger=os.path.join(tmp, "l.db"), repo="/R")
        self.assertIsNone(refusal, f"{runtime} refused to produce a command")
        return cmd

    def test_neither_runtime_is_quietly_sandboxed(self):
        for runtime in ("claude_code", "codex"):
            with self.subTest(runtime=runtime):
                self.assertIn("--yolo", self._cmd(runtime),
                              "this fleet's declared posture is bypass on "
                              "BOTH runtimes; a pane launched with less than "
                              "that is an undeclared asymmetry")

    def test_a_sandbox_is_an_explicit_opt_in_and_is_visible(self):
        """Asking for less is allowed. Getting less by default is not."""
        from nxb.rig import launch_command
        cmd, _, _ = launch_command({"name": "W", "runtime": "codex"},
                                   ledger=os.path.join(tempfile.mkdtemp(),
                                                       "l.db"),
                                   repo="/R", sandbox="read-only")
        self.assertIn("--sandbox read-only", cmd)
        self.assertNotIn("--yolo", cmd)

    def test_the_sandbox_default_is_none_not_a_policy_name(self):
        """A policy name as the default is how the asymmetry hid: it read as
        a deliberate choice in the signature and nobody had chosen it."""
        import inspect

        from nxb.rig import launch_command
        self.assertIsNone(
            inspect.signature(launch_command).parameters["sandbox"].default)


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class TmuxTargetFormsAreREAL(unittest.TestCase):
    """RIG-13. Every other test in this file mocks tmux, so the mocks agree
    with whatever the code believes about tmux's own syntax. That is a
    measurement of the author, not of tmux.

    A session target takes `=name` and a PANE or WINDOW target takes `=name:`
    and rejects the bare form. Sweeping the session form across every call
    site broke `rig up` outright with "can't find pane: =nxb", and no mocked
    test could have seen it. This drives the real binary and launches no
    runtime, so it costs a few milliseconds and no tokens.
    """

    SESSION = "nxb-selftest"

    def setUp(self):
        subprocess.run(["tmux", "kill-session", "-t", f"={self.SESSION}"],
                       capture_output=True)
        made = subprocess.run(
            ["tmux", "new-session", "-d", "-s", self.SESSION, "-x", "80",
             "-y", "20"], capture_output=True, text=True)
        if made.returncode != 0:
            self.skipTest(f"could not create a tmux session: {made.stderr}")
        self.addCleanup(subprocess.run,
                        ["tmux", "kill-session", "-t", f"={self.SESSION}"],
                        capture_output=True)

    def _run(self, *args):
        return subprocess.run(["tmux", *args], capture_output=True, text=True)

    def test_a_session_target_accepts_the_session_form(self):
        from nxb.rig import _exact
        self.assertEqual(
            self._run("has-session", "-t", _exact(self.SESSION)).returncode, 0)

    def test_a_pane_target_accepts_the_WINDOW_form_and_rejects_the_other(self):
        from nxb.rig import _exact, _exact_window
        ok = self._run("split-window", "-t", _exact_window(self.SESSION),
                       "-P", "-F", "#{pane_id}")
        self.assertEqual(ok.returncode, 0,
                         f"the window form must work: {ok.stderr.strip()}")
        bad = self._run("split-window", "-t", _exact(self.SESSION))
        self.assertNotEqual(bad.returncode, 0,
                            "if tmux ever accepts the bare session form for a "
                            "pane target, this guard is measuring nothing and "
                            "should be re-derived rather than deleted")

    def test_the_exact_forms_defeat_prefix_matching(self):
        """RIG-8's actual property, against the real binary."""
        from nxb.rig import _exact
        prefix = self.SESSION[:6]
        self.assertNotEqual(prefix, self.SESSION)
        self.assertEqual(self._run("has-session", "-t", prefix).returncode, 0,
                         "tmux should still prefix-match a BARE target")
        self.assertNotEqual(
            self._run("has-session", "-t", _exact(prefix)).returncode, 0,
            "the exact form must NOT match a session it merely prefixes")

    def test_layout_and_listing_work_on_a_real_session(self):
        from nxb.rig import _exact, _exact_window
        self._run("split-window", "-t", _exact_window(self.SESSION))
        self.assertEqual(
            self._run("select-layout", "-t", _exact_window(self.SESSION),
                      "main-horizontal").returncode, 0)
        listed = self._run("list-panes", "-t", _exact(self.SESSION),
                           "-F", "#{pane_id}")
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(len(listed.stdout.split()), 2)

    def test_a_TORN_DOWN_rig_has_no_workers_and_is_not_an_error(self):
        """RIG-14. nxb-055 made an unaskable tmux loud, and swept a legitimate
        answer in with it: a rig torn down hours earlier has no panes, which
        is a FACT, not a failure. Conflating them meant one stale state file
        refused every mint in the fleet."""
        from nxb.rig import _live_panes
        self.assertEqual(_live_panes("nxb-definitely-not-a-session"), set(),
                         "a session that does not exist has no panes; that "
                         "is an answer and must not raise")

    def test_a_STANDING_session_that_cannot_be_queried_still_raises(self):
        """The other half, or the fix above would re-open the false green."""
        from unittest import mock

        import nxb.rig as rig
        real = rig._tmux

        def flaky(*args, **kwargs):
            if args and args[0] == "has-session":
                return real(*args, **kwargs)          # the session IS there
            return types.SimpleNamespace(returncode=1, stdout="",
                                         stderr="tmux server exploded")

        with mock.patch.object(rig, "_tmux", flaky):
            with self.assertRaises(rig.RigTmuxError):
                rig._live_panes(self.SESSION)


class ANameCarriesItsRig(unittest.TestCase):
    """RIG-20. RIG-18 REFUSED an ambiguous worker name, which is a guard
    standing where an invariant belongs. Rohan's call: make the collision
    impossible instead of detecting it. Fleets are built from a shape, so two
    rigs held the same 'CX Worker 1' AND the same 'Orchestrator', and a ticket
    names a worker rather than a rig -- so a ticket minted for one fleet would
    have typed into the other and validated there."""

    def test_a_name_is_prefixed_with_its_session(self):
        self.assertEqual(rig.scoped_name("lab", "CX Worker 1"),
                         "lab CX Worker 1")

    def test_scoping_is_idempotent(self):
        """Applied at stand-up, and a scenario may be re-used or re-read."""
        once = rig.scoped_name("lab", "CX Worker 1")
        self.assertEqual(rig.scoped_name("lab", once), once)

    def test_two_fleets_of_the_SAME_SHAPE_share_no_name(self):
        """The actual property, stated as the collision that used to exist."""
        shape = rig.compose(rig.parse_workers("cc:2,cx:2"),
                            orchestrator="codex")
        a = {rig.scoped_name("nxb", p["name"]) for p in shape["panes"]}
        b = {rig.scoped_name("lab", p["name"]) for p in shape["panes"]}
        self.assertEqual(a & b, set(),
                         "two rigs built from one shape must share no worker "
                         "name, or a ticket minted for one types into the "
                         "other and is validated there")
        self.assertEqual(len(a), len(shape["panes"]), "names must be unique")

    def test_the_ORCHESTRATOR_is_scoped_too(self):
        """It collided as loudly as the workers did and was easy to miss,
        because there is only ever one per rig."""
        shape = rig.compose(rig.parse_workers("cx:1"), orchestrator="cc")
        names = [rig.scoped_name("lab", p["name"]) for p in shape["panes"]]
        self.assertIn("lab Orchestrator", names)

    def test_stand_up_scopes_the_names_it_records(self):
        """Naming is applied at STAND-UP, so a scenario stays a SHAPE. If it
        were baked into SCENARIOS, the rule would live in two places."""
        import inspect
        src = inspect.getsource(rig.stand_up)
        self.assertIn("scoped_name(session", src)

