"""Durable Studio drafts: the common state behind the page and MCP."""

import json
import os
import tempfile
import unittest

from nxb.studio_drafts import (DraftConflict, DraftError, delete_draft,
                               get_draft, list_drafts, normalize, save_draft,
                               validate)


def fleet(session="release-gate"):
    return {
        "session": session,
        "working_directory": "~",
        "layout": "main-horizontal",
        "agents": [
            {"name": "Gate Captain", "role": "orchestrator",
             "runtime": "codex", "model": "gpt-5.6-sol",
             "effort": "xhigh", "instructions": "Own the final decision."},
            {"name": "Journey Judge", "role": "worker",
             "runtime": "claude", "model": "sonnet", "effort": "high"},
        ],
    }


class DraftShape(unittest.TestCase):
    def test_a_model_can_submit_a_complete_fleet_in_one_object(self):
        draft = normalize(fleet())
        self.assertEqual(draft["session"], "release-gate")
        self.assertEqual([a["runtime"] for a in draft["agents"]],
                         ["codex", "claude_code"])
        self.assertEqual([a["node_id"] for a in draft["agents"]], [1, 2])
        self.assertEqual(draft["agents"][0]["y"], 60)
        self.assertEqual(draft["agents"][1]["y"], 300)

    def test_launch_invariants_are_reused_at_the_draft_boundary(self):
        cases = [
            ({**fleet(), "session": "two words"}, "session may not"),
            ({**fleet(), "agents": []}, "no agents"),
            ({**fleet(), "agents": [
                {"name": "same", "runtime": "codex"},
                {"name": "same", "runtime": "codex"}]}, "both called"),
            ({**fleet(), "agents": [
                {"name": "one", "runtime": "codex", "role": "orchestrator"},
                {"name": "two", "runtime": "codex", "role": "orchestrator"}]},
             "at most one"),
            ({**fleet(), "agents": [
                {"name": "bad", "runtime": "imaginary"}]}, "unknown runtime"),
        ]
        for value, message in cases:
            with self.subTest(message=message), self.assertRaises(DraftError) as cm:
                normalize(value)
            self.assertIn(message, str(cm.exception))

    def test_validation_warns_about_paths_without_rejecting_an_idea(self):
        spec = fleet()
        spec["working_directory"] = "/definitely/not/here"
        result = validate(spec)
        self.assertTrue(result["valid"])
        self.assertIn("does not exist yet", result["warnings"][0])

    def test_the_browser_may_persist_an_empty_half_typed_tab(self):
        draft = normalize({"session": "", "agents": []}, strict=False)
        self.assertEqual(draft["agents"], [])


class DurableDrafts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self.tmp.name, "ledger.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_list_get_and_atomic_file(self):
        saved = save_draft(self.ledger, fleet())
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(get_draft(self.ledger, saved["draft_id"]), saved)
        self.assertEqual(list_drafts(self.ledger), [saved])
        path = os.path.join(self.tmp.name, "studio-drafts",
                            saved["draft_id"] + ".json")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["session"], "release-gate")
        self.assertEqual(oct(os.stat(path).st_mode)[-3:], "600")

    def test_updates_are_compare_and_swap(self):
        first = save_draft(self.ledger, fleet())
        changed = fleet()
        changed["agents"][1]["name"] = "Independent Judge"
        second = save_draft(self.ledger, changed,
                            draft_id=first["draft_id"], expected_revision=1)
        self.assertEqual(second["revision"], 2)
        with self.assertRaises(DraftConflict) as cm:
            save_draft(self.ledger, fleet(), draft_id=first["draft_id"],
                       expected_revision=1)
        self.assertIn("revision 2", str(cm.exception))

    def test_an_mcp_update_preserves_studio_owned_liveness_by_node_id(self):
        first = save_draft(self.ledger, fleet())
        browser = dict(first)
        browser["agents"] = [dict(a) for a in first["agents"]]
        browser["agents"][0]["deployed_name"] = "release-gate Gate Captain"
        second = save_draft(self.ledger, browser, draft_id=first["draft_id"],
                            expected_revision=1, source="studio", strict=False)
        model_copy = dict(second)
        model_copy["agents"] = [dict(a) for a in second["agents"]]
        model_copy["agents"][0].pop("deployed_name")
        third = save_draft(self.ledger, model_copy,
                           draft_id=first["draft_id"], expected_revision=2,
                           source="mcp", strict=True)
        self.assertEqual(third["agents"][0]["deployed_name"],
                         "release-gate Gate Captain")

    def test_an_update_must_name_the_revision_it_read(self):
        first = save_draft(self.ledger, fleet())
        with self.assertRaises(DraftConflict):
            save_draft(self.ledger, fleet(), draft_id=first["draft_id"])

    def test_two_drafts_cannot_claim_one_future_tmux_session(self):
        save_draft(self.ledger, fleet())
        with self.assertRaises(DraftConflict) as cm:
            save_draft(self.ledger, fleet())
        self.assertIn("already uses session", str(cm.exception))

    def test_delete_is_revision_guarded_and_recoverable(self):
        saved = save_draft(self.ledger, fleet())
        with self.assertRaises(DraftConflict):
            delete_draft(self.ledger, saved["draft_id"], expected_revision=99)
        result = delete_draft(self.ledger, saved["draft_id"],
                              expected_revision=saved["revision"])
        self.assertEqual(result["state"], "TRASHED")
        self.assertTrue(os.path.exists(result["recoverable_from"]))
        with self.assertRaises(DraftError):
            get_draft(self.ledger, saved["draft_id"])

    def test_boolean_is_not_a_revision_even_though_python_calls_it_an_int(self):
        saved = save_draft(self.ledger, fleet())
        with self.assertRaises(DraftError):
            save_draft(self.ledger, fleet(), draft_id=saved["draft_id"],
                       expected_revision=True)
        with self.assertRaises(DraftError):
            delete_draft(self.ledger, saved["draft_id"],
                         expected_revision=True)


if __name__ == "__main__":
    unittest.main()
