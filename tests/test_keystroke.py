"""nxb-051: typing as the transport, and the marker that cannot be omitted.
nxb-052: the standing rig is discovered, never assumed (RIG-4)."""

import ast
import json
import os
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from nxb.enroll import MARKER, enrollment_rule, typed_enrolment_rule
from nxb.keystroke import marked_directive

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TheMarkerCannotBeOmitted(unittest.TestCase):
    """Structural, not conventional. A convention the code merely follows is
    the thing this project has watched erode."""

    def test_every_directive_carries_the_marker(self):
        text = marked_directive("nxbt-1", "W", "do a thing")
        self.assertTrue(text.startswith(MARKER),
                        "the marker must LEAD, so a worker can classify the "
                        "message before reading anything that might argue")

    def test_a_directive_without_a_task_id_is_impossible(self):
        for bad in ("", "   ", None):
            with self.subTest(task_id=bad):
                with self.assertRaises(ValueError):
                    marked_directive(bad, "W", "body")

    def test_a_directive_without_a_worker_is_impossible(self):
        with self.assertRaises(ValueError):
            marked_directive("nxbt-1", "", "body")

    def test_there_is_NO_BRANCH_that_returns_an_unmarked_directive(self):
        """Read the function, not the docs: every return must include MARKER."""
        tree = ast.parse((ROOT / "nxb" / "keystroke.py").read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "marked_directive")
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        self.assertTrue(returns)
        for node in returns:
            self.assertIn("MARKER", ast.dump(node.value),
                          "a return path that omits the marker")

    def test_only_ONE_function_can_type_a_directive(self):
        tree = ast.parse((ROOT / "nxb" / "keystroke.py").read_text())
        senders = [n.name for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and any(isinstance(c, ast.Call)
                           and getattr(c.func, "id", None) == "send_line"
                           for c in ast.walk(n))]
        self.assertEqual(senders, ["send_directive"])

    def test_send_directive_REQUIRES_a_task_id_positionally(self):
        """No default, so 'send without an id' is a TypeError at the call
        site rather than a quieter message on the wire."""
        import inspect

        from nxb.keystroke import send_directive
        params = inspect.signature(send_directive).parameters
        self.assertIs(params["task_id"].default, inspect.Parameter.empty)


class OneRuleTwoDeliveries(unittest.TestCase):
    def test_both_runtimes_get_the_SAME_rule_text(self):
        """The uniform transport is only uniform if the obligation is."""
        launch = enrollment_rule("W", ledger="/l", repo="/r")
        typed = typed_enrolment_rule("W", ledger="/l", repo="/r")
        self.assertIn(launch, typed,
                      "the typed rule must CONTAIN the launch rule verbatim, "
                      "or the two runtimes are enforcing different things")

    def test_the_rule_defines_marked_and_unmarked(self):
        rule = enrollment_rule("W", ledger="/l", repo="/r")
        self.assertIn(MARKER, rule)
        self.assertIn("AUTOMATED", rule)
        self.assertIn("NOT AUTOMATED", rule)

    def test_the_rule_makes_UNMARKED_the_operator(self):
        """Stated because it is the permissive half: anything on this machine
        that can type is the operator as far as this rule is concerned."""
        self.assertIn("operator", enrollment_rule("W", ledger="/l", repo="/r"))

    def test_the_typed_rule_carries_persistence_language(self):
        """A system prompt is structurally above later messages; a first
        conversational message is not, so it has to say so itself."""
        typed = typed_enrolment_rule("W", ledger="/l", repo="/r")
        self.assertIn("STANDING RULE", typed)
        self.assertIn("every message you receive from now on", typed)

    def test_the_typed_rule_asks_for_an_acknowledgement(self):
        from nxb.enroll import ACK
        self.assertIn(ACK, typed_enrolment_rule("W", ledger="/l", repo="/r"))


class TheStandingRigIsDiscoveredNeverAssumed(unittest.TestCase):
    """RIG-4. The default session name and the rig actually standing drifted
    apart ('nxb' vs 'nxb-s2'); mint refused a declared Codex worker as
    unknown, and send's remedy would have stood up a SECOND rig. The fix is
    removal of the assumption: state files next to the ledger already know
    every rig, and tmux answers which of them stands."""

    def _rig_state(self, tmp, sessions):
        for s in sessions:
            with open(os.path.join(tmp, f"rig-{s}.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"session": s, "panes": [
                    {"name": "CX Worker 1", "runtime": "codex", "pane": "%3",
                     "enrolment": "typed", "thread_id": "t-1"}]}, handle)
        return os.path.join(tmp, "ledger.db")

    def _tmux_answering(self, alive):
        def fake(*args, **kwargs):
            # `-t =name` is tmux's exact-match form; the rig uses it now so
            # that `nxb` cannot prefix-match `nxb-s2`. [RIG-8]
            target = args[2].lstrip("=") if len(args) > 2 else ""
            code = 0 if (args and args[0] == "has-session"
                         and target in alive) else 1
            return types.SimpleNamespace(returncode=code, stdout="",
                                         stderr="")
        return fake

    def test_rig_sessions_reads_the_state_files(self):
        from nxb.keystroke import rig_sessions
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._rig_state(tmp, ["nxb-s2", "other"])
            with open(os.path.join(tmp, "rig-broken.json"), "w",
                      encoding="utf-8") as handle:
                handle.write("{half a rec")     # half-written names no rig
            self.assertEqual(rig_sessions(ledger), ["nxb-s2", "other"])

    def test_one_standing_rig_is_resolved_and_typed_into(self):
        from nxb.keystroke import send_directive
        typed = []
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._rig_state(tmp, ["nxb-s2"])
            with mock.patch("nxb.rig._tmux",
                            self._tmux_answering({"nxb-s2"})), \
                 mock.patch("nxb.rig.send_line",
                            lambda pane, text: typed.append((pane, text))):
                out = send_directive("CX Worker 1", "nxbt-1", "body",
                                     ledger=ledger)
        self.assertEqual(out["state"], "TYPED")
        self.assertEqual(out["session"], "nxb-s2")
        self.assertEqual(typed[0][0], "%3")

    def test_a_recorded_but_fallen_rig_is_not_standing(self):
        from nxb.keystroke import send_directive
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._rig_state(tmp, ["nxb-s2"])
            with mock.patch("nxb.rig._tmux", self._tmux_answering(set())):
                out = send_directive("CX Worker 1", "nxbt-1", "body",
                                     ledger=ledger)
        self.assertEqual(out["reason"], "keystroke_no_rig")
        self.assertIn("nxb-s2", out["detail"],
                      "the refusal must say state EXISTS for the fallen rig, "
                      "or the operator cannot tell a dead rig from no rig")

    def test_two_standing_rigs_refuse_as_ambiguous(self):
        from nxb.keystroke import send_directive
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._rig_state(tmp, ["a", "b"])
            with mock.patch("nxb.rig._tmux",
                            self._tmux_answering({"a", "b"})):
                out = send_directive("CX Worker 1", "nxbt-1", "body",
                                     ledger=ledger)
        self.assertEqual(out["reason"], "keystroke_ambiguous_rig")
        self.assertEqual(out["remedy"], ["--session a", "--session b"],
                         "the remedy is the exact flag, per rig, not advice")

    def test_a_wrong_explicit_session_names_the_standing_one(self):
        """The measured trap: --session nxb while nxb-s2 stands. The old
        remedy was `rig up --session nxb`, which stands up a second rig."""
        from nxb.keystroke import send_directive
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._rig_state(tmp, ["nxb-s2"])
            with mock.patch("nxb.rig._tmux",
                            self._tmux_answering({"nxb-s2"})):
                out = send_directive("CX Worker 1", "nxbt-1", "body",
                                     ledger=ledger, session="nxb")
        self.assertEqual(out["reason"], "keystroke_no_rig")
        self.assertIn("nxb-s2", out["detail"])
        self.assertEqual(out["remedy"], ["--session nxb-s2"])

    def test_no_state_at_all_still_points_at_rig_up(self):
        from nxb.keystroke import send_directive
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "ledger.db")
            with mock.patch("nxb.rig._tmux", self._tmux_answering(set())):
                out = send_directive("CX Worker 1", "nxbt-1", "body",
                                     ledger=ledger)
        self.assertEqual(out["reason"], "keystroke_no_rig")
        self.assertTrue(any("rig up" in r for r in out["remedy"]))


class TheAnswerComesBack(unittest.TestCase):
    """RIG-5. `rig send` typed and returned, and nothing read the reply, so
    an orchestrator could dispatch and never see what came back. Review was a
    habit rather than a step, and nothing correlated a reply to its task."""

    TASK = "nxbt-abc123"

    def _pane(self, screen):
        """A rig of one worker whose pane shows `screen`."""
        from nxb import keystroke
        rig = {"session": "s", "panes": [
            {"name": "W", "runtime": "codex", "pane": "%9",
             "enrolment": "typed", "thread_id": "t"}]}
        return (mock.patch.object(keystroke, "_resolve",
                                  lambda w, l, s: (rig["panes"][0], "s", None)),
                mock.patch("nxb.rig.capture_history", lambda p, **k: screen))

    def _collect(self, screen):
        from nxb.keystroke import collect_reply
        resolve, capture = self._pane(screen)
        with resolve, capture:
            return collect_reply("W", self.TASK, ledger="/tmp/l.db")

    def test_the_directive_asks_for_a_correlated_done_marker(self):
        from nxb.keystroke import done_marker
        text = marked_directive(self.TASK, "W", "do a thing")
        self.assertIn(done_marker(self.TASK), text)
        self.assertNotIn(done_marker("nxbt-other"), text,
                         "the marker must name THIS task, or a reply cannot "
                         "be told from a reply to something else")

    def test_an_answer_between_the_boundary_and_the_marker_is_returned(self):
        from nxb.keystroke import done_marker
        out = self._collect(
            marked_directive(self.TASK, "W", "count them") + "\n"
            "42\n" + done_marker(self.TASK) + "\n")
        self.assertEqual(out["state"], "ANSWERED")
        self.assertEqual(out["answer"], "42")

    def test_THE_ECHOED_DIRECTIVE_ALONE_IS_NOT_AN_ANSWER(self):
        """THE REGRESSION THAT MATTERS. Measured on the first live collect:
        the directive must NAME the done marker in order to ask for it, so the
        marker is on the pane from the moment the directive lands. Searching
        the whole pane found that copy and returned the echoed directive as
        the answer -- a false green in the collector itself."""
        out = self._collect(marked_directive(self.TASK, "W", "count them"))
        self.assertEqual(out["state"], "WAITING",
                         "a directive that has only been ECHOED is not an "
                         "answer to itself")
        self.assertTrue(out["dispatch_seen"])

    def test_a_directive_that_never_landed_is_told_apart_from_one_in_flight(self):
        """Both are WAITING and they are NOT the same problem: one needs
        re-sending, the other needs patience."""
        self.assertFalse(self._collect("some unrelated pane")["dispatch_seen"])

    def test_a_marker_wrapped_across_lines_is_still_found(self):
        """Codex hard-wraps to the pane width and tmux -J does not rejoin it,
        which already cost this project a rename parser that worked in the
        wide pane and failed in every narrow one."""
        from nxb.keystroke import done_marker
        wrapped = "\n".join(["[NXB-D", "ONE nxbt-", "abc123]"])
        out = self._collect(
            marked_directive(self.TASK, "W", "x") + "\n7\n" + wrapped + "\n")
        self.assertEqual(out["state"], "ANSWERED")
        self.assertEqual(out["answer"], "7")
        self.assertIn(self.TASK, done_marker(self.TASK))

    def test_waiting_carries_the_tail_so_a_refusal_is_visible(self):
        """A worker that REFUSED an id and correctly did nothing else looks
        exactly like one still working. The collector must not guess."""
        out = self._collect(
            marked_directive(self.TASK, "W", "x") + "\nRefused: wrong worker.")
        self.assertEqual(out["state"], "WAITING")
        self.assertIn("Refused", out["tail"])

    def test_send_and_collect_resolve_the_pane_the_SAME_way(self):
        """One resolver, so a directive and its answer can never disagree
        about which pane the worker is."""
        import inspect

        from nxb.keystroke import collect_reply, send_directive
        for fn in (send_directive, collect_reply):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_resolve", inspect.getsource(fn))


class ThePublishedVocabulary(unittest.TestCase):
    def test_keystroke_refusals_are_published(self):
        import nxb.keystroke as ks
        contract = json.loads((ROOT / "contract" / "rig.json").read_text())
        emitted = {v for k, v in vars(ks).items()
                   if k.startswith("KEYSTROKE_") and isinstance(v, str)}
        self.assertEqual(emitted - set(contract["refusal_vocabulary"]), set())


if __name__ == "__main__":
    unittest.main()
