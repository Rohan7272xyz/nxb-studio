"""nxb-081: the context store. A vault with a size discipline."""

import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from nxb import context as ctx
from nxb import keystroke
from nxb.context import (CONTEXT_BAD_KEY, CONTEXT_EMPTY_BODY,
                         CONTEXT_NOT_FOUND, CONTEXT_NOTE_TOO_BIG,
                         GET_CAP_CHARS, STATE_CAP_CHARS, Vault,
                         extract_summary, orientation_line, record_report,
                         state_key)
from nxb.keystroke import (ANSWER_INLINE_CHARS, collect_reply, file_reply,
                           marked_directive)
from nxb.roster import Roster, RosterEntry
from nxb.tasks import TaskRegistry

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "ledger.db")
        self.vault = Vault(self.ledger)

    def tearDown(self):
        self.vault.close()


class NotesAreFilesWithFrontmatter(Case):
    def test_put_then_get_round_trips_body_and_meta(self):
        out = self.vault.put("notes/decisions", "# D1\nWe chose X.\n",
                             summary="the decisions", tags=["a", "b c"],
                             author="hub Director")
        self.assertEqual(out["state"], "WRITTEN")
        self.assertTrue(out["path"].endswith("/vault/notes/decisions.md"))
        got = self.vault.get("notes/decisions")
        self.assertEqual(got["state"], "NOTE")
        self.assertEqual(got["body"], "# D1\nWe chose X.\n")
        self.assertEqual(got["meta"]["summary"], "the decisions")
        self.assertEqual(got["meta"]["tags"], ["a", "b c"])
        self.assertEqual(got["meta"]["author"], "hub Director")
        self.assertFalse(got["truncated"])
        with open(got["path"], encoding="utf-8") as handle:
            self.assertTrue(handle.read().startswith("---\nkey: notes/decisions"))

    def test_the_vault_sits_beside_the_ledger_unless_pointed_elsewhere(self):
        self.assertEqual(self.vault.root, os.path.join(self.tmp, "vault"))
        with mock.patch.dict(os.environ, {ctx.VAULT_ENV: os.path.join(
                self.tmp, "Obsidian", "NXB")}):
            other = Vault(self.ledger)
            try:
                self.assertTrue(other.root.endswith("/Obsidian/NXB"))
                self.assertTrue(os.path.isdir(other.root))
            finally:
                other.close()

    def test_bad_keys_are_refused(self):
        for bad in ("", "../x", "a/../b", ".hidden", "x\ny", "a|b"):
            with self.subTest(key=bad):
                self.assertEqual(self.vault.put(bad, "x")["reason"],
                                 CONTEXT_BAD_KEY)

    def test_an_empty_body_is_refused_and_a_missing_note_is_named(self):
        self.assertEqual(self.vault.put("notes/x", "  ")["reason"],
                         CONTEXT_EMPTY_BODY)
        out = self.vault.get("notes/nope")
        self.assertEqual(out["reason"], CONTEXT_NOT_FOUND)
        self.assertTrue(out["path"].endswith("notes/nope.md"))


class TheCapsAreTheMechanism(Case):
    def test_a_state_note_over_its_cap_is_REFUSED_with_a_remedy(self):
        out = self.vault.put(state_key("demo"), "x" * (STATE_CAP_CHARS + 1))
        self.assertEqual(out["reason"], CONTEXT_NOTE_TOO_BIG)
        self.assertIn("own note", " ".join(out["remedy"]))
        self.assertEqual(self.vault.state("demo")["state"], "MISSING")
        ok = self.vault.put(state_key("demo"), "x" * STATE_CAP_CHARS)
        self.assertEqual(ok["state"], "WRITTEN")
        self.assertEqual(ok["kind"], "state")

    def test_an_ordinary_note_is_not_capped_on_write_but_get_is_bounded(self):
        big = "word " * 20_000                         # 100K characters
        self.assertEqual(self.vault.put("reports/big", big)["state"], "WRITTEN")
        got = self.vault.get("reports/big")
        self.assertTrue(got["truncated"])
        self.assertEqual(len(got["body"]), GET_CAP_CHARS)
        self.assertEqual(got["chars"], len(big))
        rest = self.vault.get("reports/big", offset=got["next_offset"],
                              max_chars=1000)
        self.assertEqual(rest["offset"], GET_CAP_CHARS)
        self.assertEqual(len(rest["body"]), 1000)

    def test_a_missing_state_note_says_how_to_write_one(self):
        out = self.vault.state("demo")
        self.assertEqual(out["state"], "MISSING")
        self.assertIn("context put --key rigs/demo/STATE", out["write_with"])
        self.assertEqual(out["cap_chars"], STATE_CAP_CHARS)


class SearchReturnsSnippetsNeverBodies(Case):
    def _seed(self):
        self.vault.put("rigs/demo/STATE",
                       "# State\nBackend on main at ea91754. The scheduler "
                       "lane is merged.\n\n## Open\nReminders bug OI-24.\n")
        self.vault.put("reports/nxbt-1",
                       "SUMMARY: the scheduler passed 865 tests.\n\n" +
                       "detail " * 3000 + "\nreminder scheduling fails when "
                       "the global switch is off.\n")
        self.vault.put("notes/unrelated", "gardening and bicycles\n")

    def test_hits_carry_keys_and_short_snippets(self):
        self._seed()
        out = self.vault.search("scheduler")
        self.assertEqual(out["state"], "HITS")
        keys = [h["key"] for h in out["hits"]]
        self.assertIn("rigs/demo/STATE", keys)
        self.assertIn("reports/nxbt-1", keys)
        self.assertNotIn("notes/unrelated", keys)
        for hit in out["hits"]:
            self.assertLess(len(hit["snippet"]), 400)
            self.assertIn("[", hit["snippet"], "the match is marked")

    def test_no_note_takes_every_slot(self):
        self.vault.put("notes/long", "\n\n".join(
            f"## Part {i}\nthe scheduler again {i}" for i in range(40)))
        self._seed()
        out = self.vault.search("scheduler", limit=8)
        per_key = {}
        for h in out["hits"]:
            per_key[h["key"]] = per_key.get(h["key"], 0) + 1
        self.assertLessEqual(max(per_key.values()), ctx.PER_KEY_HITS)
        self.assertGreater(len(per_key), 1)

    def test_a_phrase_falls_back_to_any_term_and_stemming_helps(self):
        self._seed()
        out = self.vault.search("reminders scheduling")
        self.assertEqual(out["state"], "HITS")
        self.assertEqual(self.vault.search("zzqx")["state"], "EMPTY")
        self.assertEqual(self.vault.search("   ")["state"], "EMPTY")

    def test_a_prefix_narrows_it(self):
        self._seed()
        out = self.vault.search("scheduler", prefix="reports/")
        self.assertTrue(out["hits"])
        self.assertTrue(all(h["key"].startswith("reports/")
                            for h in out["hits"]))


class TheIndexIsACacheOfTheFiles(Case):
    def test_a_note_edited_outside_nxb_is_found_after_the_sweep(self):
        self.vault.put("notes/a", "first words\n")
        path = self.vault.path_for("notes/a")
        time.sleep(0.01)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\nsecond words about kumquats\n")
        os.utime(path, None)
        out = self.vault.search("kumquats")
        self.assertEqual(out["state"], "HITS")
        self.assertEqual(out["hits"][0]["key"], "notes/a")

    def test_a_note_dropped_in_by_hand_is_indexed_and_a_deleted_one_removed(self):
        os.makedirs(os.path.join(self.vault.root, "notes"), exist_ok=True)
        with open(os.path.join(self.vault.root, "notes", "hand.md"), "w",
                  encoding="utf-8") as handle:
            handle.write("written in Obsidian, about pelicans\n")
        self.assertEqual(self.vault.search("pelicans")["hits"][0]["key"],
                         "notes/hand")
        os.remove(os.path.join(self.vault.root, "notes", "hand.md"))
        self.assertEqual(self.vault.search("pelicans")["state"], "EMPTY")

    def test_deleting_the_index_loses_nothing(self):
        self.vault.put("notes/a", "about albatrosses\n")
        self.vault.close()
        os.remove(ctx.index_path(self.ledger))
        self.vault = Vault(self.ledger)
        self.assertEqual(self.vault.reindex()["notes"], 1)
        self.assertEqual(self.vault.search("albatross")["state"], "HITS")

    def test_the_index_lives_beside_the_ledger_not_in_the_vault(self):
        self.assertEqual(os.path.dirname(ctx.index_path(self.ledger)), self.tmp)
        self.assertFalse(ctx.index_path(self.ledger).startswith(
            self.vault.root + os.sep))

    def test_list_shows_keys_with_summaries(self):
        self.vault.put("rigs/demo/STATE", "state text", summary="the state")
        self.vault.put("notes/x", "body", summary="x")
        out = self.vault.list("rigs/")
        self.assertEqual([n["key"] for n in out["notes"]], ["rigs/demo/STATE"])
        self.assertEqual(out["notes"][0]["summary"], "the state")


class SummariesComeFromTheWorker(unittest.TestCase):
    def test_a_summary_paragraph_is_extracted_and_capped(self):
        text = "SUMMARY: all green,\n865 tests pass.\n\nThen a lot of detail."
        summary, source = extract_summary(text)
        self.assertEqual((summary, source), ("all green, 865 tests pass.",
                                             "worker"))
        summary, source = extract_summary("## Summary\n" + "x" * 2000 + "\n\nmore")
        self.assertEqual(source, "worker")
        self.assertEqual(len(summary), ctx.SUMMARY_CAP_CHARS + 1)

    def test_a_title_above_the_summary_heading_still_counts(self):
        """MEASURED on the first live run: both workers wrote a title line
        above '## SUMMARY', and a start-anchored match missed it."""
        text = ("# Test Report: calc.py\n\n## SUMMARY\nAll 34 tests passed; "
                "two defects found.\n\n## Test Cases\n1. ...")
        summary, source = extract_summary(text)
        self.assertEqual(source, "worker")
        self.assertEqual(summary, "All 34 tests passed; two defects found.")
        buried = "x" * 5000 + "\n\nSUMMARY: too far down.\n\n"
        self.assertEqual(extract_summary(buried)[1], "head")

    def test_without_one_the_head_is_used_and_labelled(self):
        summary, source = extract_summary("no heading here " * 200)
        self.assertEqual(source, "head")
        self.assertTrue(summary.endswith("…"))


def _mint(ledger, worker):
    reg = TaskRegistry(ledger)
    try:
        task_id, refusal = reg.mint(worker, Roster([RosterEntry(
            "%1", name=worker, alive=True, source="rig")]))
    finally:
        reg.close()
    assert refusal is None, refusal
    return task_id


class CollectHandsOverASummaryAndAPath(unittest.TestCase):
    """RIG-29. A long answer goes to the store; the orchestrator's context
    receives the worker's SUMMARY and where the rest is."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "ledger.db")
        self.task = _mint(self.ledger, "demo W")

    def _collect(self, **kw):
        pane = {"name": "demo W", "runtime": "codex", "pane": "%1",
                "enrolment": "typed"}
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "demo", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: ""):
            return collect_reply("demo W", self.task, ledger=self.ledger,
                                 **kw)

    def test_a_short_answer_still_goes_inline_whole(self):
        file_reply("demo W", self.task, "42", ledger=self.ledger)
        out = self._collect()
        self.assertEqual(out["answer"], "42")
        self.assertTrue(out["answer_inline"])
        self.assertNotIn("answer_path", out)

    def test_a_long_answer_becomes_summary_plus_path(self):
        report = ("SUMMARY: PASS with two P1 residuals; see section 4.\n\n"
                  + "detail line\n" * 2000)
        self.assertGreater(len(report), ANSWER_INLINE_CHARS)
        file_reply("demo W", self.task, report, ledger=self.ledger)
        out = self._collect()
        self.assertEqual(out["state"], "ANSWERED")
        self.assertFalse(out["answer_inline"])
        self.assertEqual(out["answer"],
                         "PASS with two P1 residuals; see section 4.")
        self.assertEqual(out["summary_source"], "worker")
        self.assertEqual(out["answer_chars"], len(report.strip()))
        self.assertTrue(out["answer_path"].endswith(
            f"/vault/reports/{self.task}.md"))
        self.assertIn("--full", out["full_with"])
        with open(out["answer_path"], encoding="utf-8") as handle:
            self.assertIn("detail line", handle.read())
        # A task card and a log line were filed for the rig.
        vault = Vault(self.ledger)
        try:
            card = vault.get(f"rigs/demo/tasks/{self.task}")
            self.assertEqual(card["state"], "NOTE")
            self.assertIn("PASS with two P1", card["body"])
            log = vault.get("rigs/demo/LOG")
            self.assertIn(self.task, log["body"])
            self.assertEqual(vault.search("residuals")["state"], "HITS")
        finally:
            vault.close()

    def test_full_returns_the_whole_text_deliberately(self):
        report = "SUMMARY: ok.\n\n" + "line\n" * 3000
        file_reply("demo W", self.task, report, ledger=self.ledger)
        out = self._collect(full=True)
        self.assertTrue(out["answer_inline"])
        self.assertEqual(out["answer"], report.strip())

    def test_a_second_collect_rewrites_nothing(self):
        report = "SUMMARY: ok.\n\n" + "line\n" * 3000
        file_reply("demo W", self.task, report, ledger=self.ledger)
        first = self._collect()
        stamp = os.stat(first["answer_path"]).st_mtime_ns
        time.sleep(0.01)
        second = self._collect()
        self.assertEqual(os.stat(second["answer_path"]).st_mtime_ns, stamp)
        vault = Vault(self.ledger)
        try:
            log = vault.get("rigs/demo/LOG")["body"]
            self.assertEqual(sum(1 for line in log.splitlines()
                                 if line.startswith("- ")), 1)
        finally:
            vault.close()

    def test_a_mocked_ledger_path_keeps_the_old_whole_answer_shape(self):
        pane = {"name": "W", "runtime": "codex", "pane": "%1",
                "enrolment": "typed"}
        screen = (marked_directive("nxbt-x", "W", "c") + "\n"
                  + "y" * 8000 + "\n[NXB-DONE nxbt-x]\n")
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "s", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: screen):
            out = collect_reply("W", "nxbt-x", ledger="/tmp/nxb-nope/l.db")
        self.assertTrue(out["answer_inline"])
        self.assertEqual(len(out["answer"]), 8000)


class FreshWorkersArePointedAtTheStateNote(unittest.TestCase):
    """RIG-30. About 99K tokens of orientation reading per task, measured;
    one sentence and a bounded note replace it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "ledger.db")
        TaskRegistry(self.ledger).close()

    def test_no_state_note_no_orientation_line(self):
        self.assertIsNone(orientation_line(self.ledger, "demo"))

    def test_the_line_names_the_note_and_sits_before_the_protocols(self):
        vault = Vault(self.ledger)
        try:
            vault.put(state_key("demo"), "what exists\n")
            path = vault.path_for(state_key("demo"))
        finally:
            vault.close()
        line = orientation_line(self.ledger, "demo")
        self.assertIn(path, line)
        text = marked_directive("nxbt-1", "demo W", "do it",
                                ledger=self.ledger, repo="/r",
                                orientation=line)
        self.assertLess(text.index("do it"), text.index("ORIENT FIRST"))
        self.assertLess(text.index("ORIENT FIRST"), text.index("rig reply"))
        self.assertTrue(text.endswith(keystroke._PROTOCOL_TAIL))

    def test_send_directive_carries_it_when_the_note_exists(self):
        vault = Vault(self.ledger)
        try:
            vault.put(state_key("demo"), "what exists\n")
        finally:
            vault.close()
        typed = []
        pane = {"name": "demo W", "runtime": "codex", "pane": "%1",
                "enrolment": "typed"}
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane, "demo", None)), \
                mock.patch("nxb.rig.send_line",
                           lambda p, t, **k: typed.append(t)):
            out = keystroke.send_directive("demo W", "nxbt-1", "do it",
                                           ledger=self.ledger, fresh=False)
        self.assertTrue(out["oriented"])
        self.assertIn("ORIENT FIRST", typed[0])

    def test_the_directive_asks_the_worker_for_a_summary_paragraph(self):
        text = marked_directive("nxbt-1", "W", "x", ledger="/l", repo="/r")
        self.assertIn("SUMMARY:", text)
        self.assertIn("800 characters", text)


class TheBriefAndTheToolsTeachIt(unittest.TestCase):
    def test_the_orchestrator_brief_reads_updates_and_searches_the_note(self):
        from nxb.enroll import orchestrator_rule
        text = orchestrator_rule("hub D", ledger="/l/x.db", repo="/r",
                                 session="hub")
        self.assertIn("context state --session hub", text)
        self.assertIn("context patch --key rigs/hub/STATE", text)
        self.assertIn("context search --query", text)
        self.assertIn("SUMMARY AND A PATH", text)
        commands = [line.strip() for line in text.splitlines()
                    if "python3 -m nxb" in line]
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command.startswith("PYTHONPATH=/r "))
                self.assertFalse(command.rstrip().endswith("."))

    def test_the_refusals_are_published(self):
        vocab = json.loads((ROOT / "contract" / "context.json").read_text())
        for term in (CONTEXT_BAD_KEY, CONTEXT_NOTE_TOO_BIG,
                     CONTEXT_NOT_FOUND, CONTEXT_EMPTY_BODY):
            self.assertIn(term, vocab["refusal_vocabulary"])

    def test_the_mcp_tools_work_end_to_end(self):
        from nxb import mcp
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ,
                             {mcp.LEDGER_ENV: os.path.join(tmp, "l.db")}):
            def call(tool, **args):
                return json.loads(
                    mcp.call_tool(tool, args)["content"][0]["text"])
            self.assertEqual(call("nxb_context_state", session="demo")["state"],
                             "MISSING")
            put = call("nxb_context_put", key="rigs/demo/STATE",
                       body="Backend on main at ea91754.", tags=["state"])
            self.assertEqual(put["state"], "WRITTEN")
            self.assertEqual(call("nxb_context_state", session="demo")["body"],
                             "Backend on main at ea91754.")
            hits = call("nxb_context_search", query="ea91754")
            self.assertEqual(hits["hits"][0]["key"], "rigs/demo/STATE")
            self.assertEqual(call("nxb_context_list", prefix="rigs/")["count"], 1)
            got = call("nxb_context_get", key="rigs/demo/STATE", max_chars=200)
            self.assertEqual(got["state"], "NOTE")

    def test_the_cli_speaks_the_same_store(self):
        import subprocess
        import sys
        tmp = tempfile.mkdtemp()
        ledger = os.path.join(tmp, "l.db")
        note = os.path.join(tmp, "state.md")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("Client merged at 3629784.\n")

        def cli(*args):
            proc = subprocess.run(
                [sys.executable, "-m", "nxb", "context", *args,
                 "--ledger", ledger], capture_output=True, text=True,
                cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)))
            return proc.returncode, json.loads(proc.stdout or "{}")
        code, out = cli("state", "--session", "demo")
        self.assertEqual((code, out["state"]), (4, "MISSING"))
        code, out = cli("put", "--key", "rigs/demo/STATE", "--file", note)
        self.assertEqual((code, out["state"]), (0, "WRITTEN"))
        code, out = cli("state", "--session", "demo")
        self.assertEqual((code, out["state"]), (0, "NOTE"))
        code, out = cli("search", "--query", "3629784")
        self.assertEqual(out["hits"][0]["key"], "rigs/demo/STATE")
        code, out = cli("path", "--session", "demo")
        self.assertTrue(out["root"].endswith("/vault"))


if __name__ == "__main__":
    unittest.main()
