"""Peer rigs and filed replies. [RIG-21]

A rig has at most one orchestrator, so a programme larger than one fleet is
several rigs. These tests pin the three things that make them ONE programme:
the peer paragraph in the orchestrator brief (present only when federated),
the reply outbox that survives a scrolling pane, and the draft/launch plumbing
that carries `peers` from a Studio draft into the brief.
"""

import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from nxb import rig
from nxb.enroll import orchestrator_rule, typed_orchestrator_rule
from nxb.keystroke import (collect_reply, file_reply, load_rig,
                           marked_directive, read_reply, reply_path, save_rig)
from nxb.roster import Roster, RosterEntry
from nxb.tasks import TaskRegistry


class ThePeerParagraph(unittest.TestCase):
    def _brief(self, peers=None):
        return orchestrator_rule("hub Director", ledger="/l/ledger.db",
                                 repo="/r", session="hub", peers=peers)

    def test_an_unfederated_brief_reads_as_it_always_did(self):
        text = self._brief()
        self.assertNotIn("PEER RIGS", text)
        self.assertIn("ONLY THAT RIG", text)
        self.assertEqual(text, self._brief(peers=[]))

    def test_a_federated_brief_names_every_peer_and_only_its_orchestrator(self):
        text = self._brief(peers=["product", "backend"])
        self.assertIn("PEER RIGS", text)
        self.assertIn("'product'", text)
        self.assertIn("'backend'", text)
        self.assertIn("ONLY pane in it you may dispatch to", text)
        self.assertIn("a peer's workers serve that peer, never you", text)

    def test_the_peer_commands_swap_the_session_not_the_protocol(self):
        text = self._brief(peers=["product"])
        self.assertIn("--session <peer rig> in place of --session hub", text)
        self.assertIn("rig workers --session <peer rig>", text)

    def test_a_peer_directive_is_answered_by_filing(self):
        text = self._brief(peers=["product"])
        self.assertIn('rig reply --worker "hub Director" --task-id <id> --file',
                      text)
        self.assertIn("--ledger /l/ledger.db", text)

    def test_the_typed_brief_carries_the_same_paragraph(self):
        typed = typed_orchestrator_rule("hub Director", ledger="/l/ledger.db",
                                        repo="/r", session="hub", peers=["x"])
        self.assertIn("PEER RIGS", typed)
        self.assertTrue(typed.rstrip().endswith("and nothing else."))

    def test_the_launch_command_threads_peers_into_the_brief_file(self):
        tmp = tempfile.mkdtemp()
        try:
            cmd, _, refusal = rig.launch_command(
                {"name": "hub Director", "runtime": "claude_code",
                 "role": "orchestrator"},
                ledger=os.path.join(tmp, "l.db"), repo="/r", session="hub",
                peers=["product"])
            self.assertIsNone(refusal)
            brief = cmd.split("$(cat '")[1].split("')")[0]
            with open(brief, encoding="utf-8") as handle:
                self.assertIn("PEER RIGS", handle.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_WORKER_never_gets_a_peer_paragraph(self):
        tmp = tempfile.mkdtemp()
        try:
            cmd, _, _ = rig.launch_command(
                {"name": "hub W", "runtime": "claude_code", "role": "worker"},
                ledger=os.path.join(tmp, "l.db"), repo="/r", session="hub",
                peers=["product"])
            brief = cmd.split("$(cat '")[1].split("')")[0]
            with open(brief, encoding="utf-8") as handle:
                self.assertNotIn("PEER RIGS", handle.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PeersAreValidatedLikeSessionNames(unittest.TestCase):
    def test_a_list_or_a_comma_string_both_clean_to_one_list(self):
        self.assertEqual(rig._clean_peers(["a", " b ", "a", ""]), ["a", "b"])
        self.assertEqual(rig._clean_peers("a, b,,a"), ["a", "b"])
        self.assertEqual(rig._clean_peers(None), [])

    def test_a_name_a_session_cannot_carry_is_refused(self):
        for bad in ("two words", "a:b", "a.b", "$a", "a'b", 'a"b', "a\\b"):
            with self.assertRaises(ValueError, msg=bad):
                rig._clean_peers([bad])

    def test_compose_agents_carries_peers_into_the_plan(self):
        plan = rig.compose_agents(
            [{"name": "D", "runtime": "cc", "role": "orchestrator"}],
            peers="product, backend")
        self.assertEqual(plan["peers"], ["product", "backend"])
        self.assertNotIn("peers", rig.compose_agents(
            [{"name": "D", "runtime": "cc"}]))

    def test_stand_up_refuses_a_self_peer_before_touching_tmux(self):
        calls = []

        def fake_tmux(*args, **kwargs):
            calls.append(args)
            raise AssertionError("tmux must not be touched")

        plan = rig.compose_agents(
            [{"name": "D", "runtime": "cc", "role": "orchestrator"}],
            peers=["hub"])
        with mock.patch.object(rig.shutil, "which",
                               lambda _: "/usr/bin/tmux"), \
                mock.patch.object(rig, "_tmux", fake_tmux):
            out = rig.stand_up(plan, session="hub", ledger="/l/l.db")
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], rig.RIG_PEER_INVALID)
        self.assertEqual(calls, [])

    def test_the_refusal_is_published(self):
        contract = json.loads(
            (pathlib.Path(rig.__file__).resolve().parents[1]
             / "contract" / "rig.json").read_text(encoding="utf-8"))
        self.assertIn(rig.RIG_PEER_INVALID, contract["refusal_vocabulary"])

    def test_the_rig_record_remembers_its_peers(self):
        tmp = tempfile.mkdtemp()
        try:
            ledger = os.path.join(tmp, "l.db")
            save_rig(ledger, "hub", {"session": "hub", "peers": ["product"],
                                     "panes": []})
            self.assertEqual(load_rig(ledger, "hub")["peers"], ["product"])
            save_rig(ledger, "solo", {"session": "solo", "panes": []})
            self.assertEqual(load_rig(ledger, "solo")["peers"], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FiledRepliesSurviveScrolling(unittest.TestCase):
    """The collector scrapes a SCREEN; a Claude Code pane scrolls its
    transcript internally; an orchestrator's pane is busy. A reply FILED next
    to the ledger is read first and whole."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "ledger.db")
        reg = TaskRegistry(self.ledger)
        try:
            roster = Roster([RosterEntry("%1", name="hub Director", alive=True),
                             RosterEntry("%2", name="hub W", alive=True)])
            self.task, refusal = reg.mint("hub Director", roster)
            self.assertIsNone(refusal)
        finally:
            reg.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _collect(self, worker, screen=""):
        from nxb import keystroke
        pane = {"name": worker, "runtime": "claude_code", "pane": "%1",
                "enrolment": "launch"}
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "hub", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: screen):
            return collect_reply(worker, self.task, ledger=self.ledger)

    def test_a_filed_answer_is_collected_from_an_EMPTY_screen(self):
        out = file_reply("hub Director", self.task, "full report\nline 2",
                         ledger=self.ledger)
        self.assertEqual(out["state"], "FILED")
        got = self._collect("hub Director", screen="nothing here")
        self.assertEqual(got["state"], "ANSWERED")
        self.assertEqual(got["source"], "outbox")
        self.assertEqual(got["answer"], "full report\nline 2")
        self.assertTrue(got["anchored"])

    def test_without_a_filed_answer_the_screen_path_is_unchanged(self):
        from nxb.keystroke import done_marker
        self.assertEqual(self._collect("hub Director", "nothing")["state"],
                         "WAITING")
        screen = (marked_directive(self.task, "hub Director", "count") + "\n"
                  "42\n" + done_marker(self.task) + "\n")
        got = self._collect("hub Director", screen=screen)
        self.assertEqual(got["state"], "ANSWERED")
        self.assertEqual(got["source"], "pane")
        self.assertEqual(got["answer"], "42")

    def test_an_answer_filed_under_ANOTHER_workers_id_is_refused(self):
        out = file_reply("hub W", self.task, "not mine", ledger=self.ledger)
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["verdict"], "task_wrong_worker")
        self.assertIsNone(read_reply(self.ledger, self.task))
        self.assertEqual(self._collect("hub Director")["state"], "WAITING")

    def test_a_forged_id_cannot_be_filed_against(self):
        out = file_reply("hub Director", "nxbt-forged", "x",
                         ledger=self.ledger)
        self.assertEqual(out["state"], "REFUSED")
        self.assertFalse(os.path.exists(reply_path(self.ledger,
                                                   "nxbt-forged")))

    def test_the_reply_lives_next_to_the_ledger(self):
        self.assertEqual(os.path.dirname(reply_path(self.ledger, "nxbt-1")),
                         os.path.join(self.tmp, "replies"))
        self.assertNotIn("/", os.path.basename(
            reply_path(self.ledger, "a/../b")))

    def test_the_directive_asks_for_filing_when_it_can_name_the_ledger(self):
        from nxb.keystroke import _PROTOCOL_TAIL
        text = marked_directive("nxbt-1", "hub W", "do it",
                                ledger="/l/ledger.db", repo="/r")
        self.assertIn('rig reply --worker "hub W" --task-id nxbt-1 --file',
                      text)
        self.assertIn("--ledger /l/ledger.db", text)
        self.assertTrue(text.endswith(_PROTOCOL_TAIL),
                        "the tail must stay the boundary collect anchors on")

    def test_a_directive_without_a_ledger_does_not_ask_for_filing(self):
        self.assertNotIn("rig reply",
                         marked_directive("nxbt-1", "hub W", "do it"))

    def test_send_directive_asks_for_filing(self):
        """`send_directive` knows its ledger, so every LIVE directive asks."""
        from nxb import keystroke
        typed = []
        pane = {"name": "hub W", "runtime": "codex", "pane": "%2",
                "enrolment": "typed"}
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "hub", None)), \
                mock.patch("nxb.rig.send_line",
                           lambda p, t, **k: typed.append(t)):
            out = keystroke.send_directive("hub W", "nxbt-1", "do it",
                                           ledger=self.ledger)
        self.assertEqual(out["state"], "TYPED")
        self.assertIn('rig reply --worker "hub W"', typed[0])
        self.assertIn(f"--ledger {self.ledger}", typed[0])


class DraftsAndStudioCarryPeers(unittest.TestCase):
    def _fleet(self, **extra):
        return {"session": "hub", "working_directory": "~",
                "agents": [{"name": "Director", "role": "orchestrator",
                            "runtime": "claude_code"},
                           {"name": "W", "role": "worker", "runtime": "codex"}],
                **extra}

    def test_peers_normalize_and_dedupe(self):
        from nxb.studio_drafts import normalize
        self.assertEqual(
            normalize(self._fleet(peers=["product", "product",
                                         " backend "]))["peers"],
            ["product", "backend"])
        self.assertEqual(normalize(self._fleet())["peers"], [])

    def test_a_self_peer_and_a_bad_name_are_readable_draft_errors(self):
        from nxb.studio_drafts import DraftError, normalize
        with self.assertRaises(DraftError):
            normalize(self._fleet(peers=["hub"]))
        with self.assertRaises(DraftError):
            normalize(self._fleet(peers=["two words"]))

    def test_peers_round_trip_through_validate_save_and_get(self):
        from nxb.studio_drafts import get_draft, save_draft, validate
        tmp = tempfile.mkdtemp()
        try:
            ledger = os.path.join(tmp, "l.db")
            self.assertEqual(
                validate(self._fleet(peers=["product"]))["draft"]["peers"],
                ["product"])
            rec = save_draft(ledger, self._fleet(peers=["product"]))
            self.assertEqual(get_draft(ledger, rec["draft_id"])["peers"],
                             ["product"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_mcp_schema_offers_peers_on_validate_and_save(self):
        from nxb.mcp import _TOOLS
        seen = 0
        for tool in _TOOLS:
            if tool["name"] in ("nxb_studio_draft_validate",
                                "nxb_studio_draft_save"):
                self.assertIn("peers", tool["inputSchema"]["properties"])
                seen += 1
        self.assertEqual(seen, 2)

    def test_the_launch_body_carries_peers_into_the_plan(self):
        from nxb.studio import Studio
        tmp = tempfile.mkdtemp()
        try:
            studio = Studio(os.path.join(tmp, "l.db"))
            _, _, plan = studio._launch_args({
                "session": "hub", "dir": tmp, "peers": ["product"],
                "agents": [{"name": "D", "role": "orchestrator",
                            "runtime": "claude_code"}]})
            self.assertEqual(plan["peers"], ["product"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_codex_offers_max_and_not_ultra(self):
        """MEASURED 2026-09-07 on codex-cli 0.153.4: `codex exec -m
        gpt-6-astra -c model_reasoning_effort="max"` answered. `ultra` is
        nested delegation, not a single-agent effort, and stays out."""
        from nxb.studio import Studio
        tmp = tempfile.mkdtemp()
        try:
            efforts = Studio(os.path.join(tmp, "l.db")).models()["codex"]["efforts"]
            self.assertIn("max", efforts)
            self.assertNotIn("ultra", efforts)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class ATypedRoleIsNotATask(unittest.TestCase):
    """RIG-22. MEASURED 2026-09-07: every Codex pane in a 25-pane programme
    began executing its role the moment it was typed, with no directive and
    no task id. A role arriving as a conversational message must say it is
    not a task, as the enrolment rule already does of itself."""

    def test_the_typed_role_preamble_forbids_starting(self):
        import inspect
        src = inspect.getsource(rig.stand_up)
        self.assertIn("THIS IS NOT A TASK", src)
        self.assertIn("do NOTHING now", src)
        self.assertIn("marked directive carrying an nxb task id", src)


class LongTextIsPastedNotTyped(unittest.TestCase):
    """RIG-23. MEASURED 2026-09-07: a ~1.3 KB message typed with send-keys
    into a live Claude Code pane arrived as its last two dozen characters."""

    def _calls(self, text):
        calls = []
        def fake_tmux(*args, **kw):
            calls.append(args); return __import__("types").SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(rig, "_tmux", fake_tmux), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            rig.send_line("%1", text)
        return calls

    def test_short_text_is_typed(self):
        calls = self._calls("hello")
        self.assertEqual(calls[0][:3], ("send-keys", "-t", "%1"))
        self.assertEqual(calls[-1], ("send-keys", "-t", "%1", "Enter"))

    def test_long_text_goes_through_a_bracketed_paste_then_enter(self):
        calls = self._calls("x" * (rig.PASTE_THRESHOLD + 1))
        self.assertEqual(calls[0][:2], ("load-buffer", "-b"))
        self.assertEqual(calls[1][0], "paste-buffer")
        self.assertIn("-p", calls[1])
        self.assertEqual(calls[-1], ("send-keys", "-t", "%1", "Enter"))
