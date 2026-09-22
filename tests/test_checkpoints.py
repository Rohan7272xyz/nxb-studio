"""nxb-082: checkpoint then reset, section patches, map notes, the dashboard.

MEASURED on the Pact programme: 421M of 1,364M input tokens sat above a 100K
ceiling (31 percent); workers read 967 markdown files against 416 code
files; 59 status-style operator turns cost 150M input; every state-note
update rewrote the whole note. Each class below pins the mechanism that
removes one of those.
"""

import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from nxb import context as ctx
from nxb import gauge, rig
from nxb.context import (BASE_FILENAME, CHECKPOINT_CAP_CHARS, MAP_CAP_CHARS,
                         Vault, checkpoint_key, map_key, orientation_line,
                         state_key)
from nxb.keystroke import load_rig, save_rig
from nxb.roster import Roster, RosterEntry
from nxb.tasks import TaskRegistry

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _ledger():
    tmp = tempfile.mkdtemp()
    ledger = os.path.join(tmp, "ledger.db")
    TaskRegistry(ledger).close()
    return tmp, ledger


def _mint(ledger, worker):
    reg = TaskRegistry(ledger)
    try:
        task_id, refusal = reg.mint(worker, Roster([RosterEntry(
            "%1", name=worker, alive=True, source="rig")]))
    finally:
        reg.close()
    assert refusal is None, refusal
    return task_id


class TheGaugeReadsTheTranscriptTail(unittest.TestCase):
    def test_a_claude_transcript_yields_the_last_context(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "sid.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for n in (10_000, 40_000):
                handle.write(json.dumps({
                    "type": "assistant", "timestamp": f"t{n}",
                    "message": {"usage": {"input_tokens": 5,
                                          "cache_read_input_tokens": n,
                                          "cache_creation_input_tokens": 100}}})
                    + "\n")
            handle.write(json.dumps({"type": "user"}) + "\n")
        with mock.patch.object(gauge, "_claude_transcript", lambda s: path):
            out = gauge.pane_context({"runtime": "claude_code",
                                      "session_id": "sid"})
        self.assertEqual(out["tokens"], 40_105)
        self.assertEqual(out["at"], "t40000")

    def test_a_codex_rollout_yields_the_last_context_and_the_window(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "rollout-x-tid.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            # A large prefix, so the read is proven to come from the tail.
            handle.write(json.dumps({"type": "filler", "x": "y" * 1000}) + "\n")
            for n in (120_000, 209_452):
                handle.write(json.dumps({
                    "type": "event_msg", "timestamp": f"t{n}",
                    "payload": {"type": "token_count", "info": {
                        "last_token_usage": {"input_tokens": n},
                        "model_context_window": 258_400}}}) + "\n")
        with mock.patch.object(gauge, "_codex_rollout", lambda t: path):
            out = gauge.pane_context({"runtime": "codex", "thread_id": "tid"})
        self.assertEqual(out["tokens"], 209_452)
        self.assertEqual(out["window"], 258_400)

    def test_fullness_uses_the_panes_own_ceiling(self):
        with mock.patch.object(gauge, "pane_context",
                               lambda e: {"tokens": 80_000, "window": 258_400}):
            tokens, limit, fraction = gauge.fullness(
                {"runtime": "codex", "thread_id": "t", "context_limit": 100_000})
        self.assertEqual((tokens, limit), (80_000, 100_000))
        self.assertAlmostEqual(fraction, 0.8)

    def test_a_stale_session_id_is_healed_from_the_registry(self):
        """MEASURED 2026-09-12: a reset re-read the registry before the
        rotated id was written; the record kept the old id and the watcher
        was blind to that pane for 21 minutes."""
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "live.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "assistant", "timestamp": "t",
                                     "message": {"usage": {
                                         "input_tokens": 1,
                                         "cache_read_input_tokens": 60_000,
                                         "cache_creation_input_tokens": 0}}})
                         + "\n")
        entry = {"runtime": "claude_code", "name": "demo W",
                 "session_id": "stale", "context_limit": 100_000}
        with mock.patch.object(gauge, "_claude_transcript",
                               lambda sid: path if sid == "live" else None), \
                mock.patch("nxb.roster.session_registry_ids",
                           lambda: {"demo W": "live"}):
            out = gauge.pane_context(entry)
        self.assertEqual(out["tokens"], 60_001)
        self.assertEqual(out["session_id"], "live")
        self.assertEqual(entry["session_id"], "live", "the entry is healed")

    def test_no_transcript_is_an_honest_unknown(self):
        with mock.patch.object(gauge, "_claude_transcript", lambda s: None):
            out = gauge.pane_context({"runtime": "claude_code",
                                      "session_id": "nope"})
        self.assertIsNone(out["tokens"])
        self.assertIn("reason", out)

    def test_the_default_ceiling_is_now_100k_on_both_runtimes(self):
        self.assertEqual(rig.DEFAULT_CONTEXT_LIMIT,
                         {"claude_code": 100_000, "codex": 100_000})


class PatchChangesOneSection(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.vault = Vault(self.ledger)
        self.vault.put(state_key("demo"),
                       "# demo\n\n## Done\n- nothing\n\n## Open\n- task A\n- task B\n\n"
                       "## Rules\n- none\n", summary="s", tags=["x"], author="op")

    def tearDown(self):
        self.vault.close()

    def test_replace_keeps_every_other_section(self):
        out = self.vault.patch(state_key("demo"), "Done", "- task A (sha 123)")
        self.assertEqual((out["state"], out["action"]), ("PATCHED", "REPLACED"))
        body = self.vault.get(state_key("demo"))["body"]
        self.assertIn("## Done\n- task A (sha 123)\n", body)
        self.assertIn("## Open\n- task A\n- task B\n", body)
        self.assertIn("## Rules\n- none", body)
        self.assertNotIn("- nothing", body)
        meta = self.vault.get(state_key("demo"))["meta"]
        self.assertEqual((meta["summary"], meta["tags"], meta["author"]),
                         ("s", ["x"], "op"))

    def test_append_adds_under_the_heading(self):
        self.vault.patch(state_key("demo"), "open", "- task C", append=True)
        body = self.vault.get(state_key("demo"))["body"]
        self.assertIn("## Open\n- task A\n- task B\n- task C\n", body)

    def test_a_missing_section_is_added_at_the_end(self):
        out = self.vault.patch(state_key("demo"), "Decisions", "- D1")
        self.assertEqual(out["action"], "ADDED")
        body = self.vault.get(state_key("demo"))["body"]
        self.assertTrue(body.rstrip().endswith("## Decisions\n- D1"))

    def test_the_cap_still_holds_after_a_patch(self):
        out = self.vault.patch(state_key("demo"), "Done", "x" * 30_000)
        self.assertEqual(out["reason"], ctx.CONTEXT_NOTE_TOO_BIG)
        self.assertIn("- nothing", self.vault.get(state_key("demo"))["body"])

    def test_a_missing_note_is_named(self):
        self.assertEqual(self.vault.patch("notes/none", "A", "b")["reason"],
                         ctx.CONTEXT_NOT_FOUND)


class MapsAndCheckpointsAreBoundedNotes(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.vault = Vault(self.ledger)

    def tearDown(self):
        self.vault.close()

    def test_keys(self):
        self.assertEqual(map_key("/Users/rohan/dev/nxb-demo"), "maps/nxb-demo")
        self.assertEqual(checkpoint_key("demo", "demo Tester"),
                         "rigs/demo/checkpoints/Tester")

    def test_a_map_is_capped_and_missing_says_how(self):
        missing = self.vault.map("/x/proj")
        self.assertEqual(missing["state"], "MISSING")
        self.assertIn("maps/proj", missing["write_with"])
        self.assertEqual(self.vault.put("maps/proj", "x" * (MAP_CAP_CHARS + 1))
                         ["reason"], ctx.CONTEXT_NOTE_TOO_BIG)
        self.assertEqual(self.vault.put("maps/proj", "modules...")["kind"], "map")
        self.assertEqual(self.vault.map("/x/proj")["state"], "NOTE")

    def test_a_checkpoint_is_capped_above_what_is_asked_for(self):
        """RIG-36. The request asks for about 8,000; a worker that writes
        8,700 is accepted, not sent round a trim loop. The hard cap holds."""
        key = checkpoint_key("demo", "demo Tester")
        self.assertEqual(self.vault.put(key, "x" * (CHECKPOINT_CAP_CHARS + 700))
                         ["state"], "WRITTEN")
        self.assertEqual(self.vault.put(
            key, "x" * (ctx.CHECKPOINT_HARD_CAP_CHARS + 1))["reason"],
            ctx.CONTEXT_NOTE_TOO_BIG)
        self.assertEqual(self.vault.put(key, "goal: ...")["kind"], "checkpoint")
        self.assertEqual(self.vault.checkpoint("demo", "demo Tester")["state"],
                         "NOTE")

    def test_the_orientation_line_names_the_map_when_it_exists(self):
        self.vault.put(state_key("demo"), "state")
        line = orientation_line(self.ledger, "demo", "/x/proj")
        self.assertIn("state note", line)
        self.assertNotIn("map", line)
        self.vault.put("maps/proj", "modules")
        line = orientation_line(self.ledger, "demo", "/x/proj")
        self.assertIn("maps/proj.md", line)
        self.assertIn("instead of exploring", line)


class TheDashboardIsWrittenOnce(unittest.TestCase):
    def test_a_new_vault_gets_the_base_and_an_edited_one_is_kept(self):
        tmp, ledger = _ledger()
        vault = Vault(ledger)
        path = os.path.join(vault.root, BASE_FILENAME)
        self.assertTrue(os.path.exists(path))
        text = open(path, encoding="utf-8").read()
        self.assertIn("views:", text)
        self.assertIn('note.kind == "card"', text)
        self.assertIn('file.inFolder("reports")', text)
        vault.close()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("# operator edit\n")
        Vault(ledger).close()
        self.assertTrue(open(path, encoding="utf-8").read().endswith(
            "# operator edit\n"))
        self.assertEqual(Vault(ledger).ensure_base()["state"], "PRESENT")

    def test_the_base_is_not_indexed_as_a_note(self):
        tmp, ledger = _ledger()
        vault = Vault(ledger)
        try:
            self.assertEqual(vault.list("")["count"], 0)
        finally:
            vault.close()


class RelocateMovesTheVaultAndRecordsIt(unittest.TestCase):
    def test_notes_move_and_every_new_vault_finds_them(self):
        tmp, ledger = _ledger()
        vault = Vault(ledger)
        vault.put("notes/a", "about herons")
        target = os.path.join(tmp, "Obsidian", "NXB")
        out = vault.relocate(target)
        vault.close()
        self.assertEqual(out["state"], "RELOCATED")
        self.assertTrue(os.path.exists(os.path.join(target, "notes", "a.md")))
        self.assertEqual(open(ctx.vault_path_file(ledger)).read().strip(),
                         target)
        again = Vault(ledger)
        try:
            self.assertEqual(again.root, target)
            self.assertEqual(again.search("herons")["hits"][0]["key"], "notes/a")
        finally:
            again.close()

    def test_a_non_empty_target_is_refused(self):
        tmp, ledger = _ledger()
        target = os.path.join(tmp, "full")
        os.makedirs(target)
        open(os.path.join(target, "x.md"), "w").close()
        vault = Vault(ledger)
        try:
            self.assertEqual(vault.relocate(target)["state"], "REFUSED")
        finally:
            vault.close()

    def test_the_env_var_still_wins(self):
        tmp, ledger = _ledger()
        with mock.patch.dict(os.environ, {ctx.VAULT_ENV: os.path.join(tmp, "env")}):
            self.assertTrue(ctx.vault_dir(ledger).endswith("/env"))


class CheckpointThenReset(unittest.TestCase):
    """RIG-31. The pane writes the note, nxb verifies it, then resets and
    continues. An unconfirmed checkpoint resets nothing."""

    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.task = _mint(self.ledger, "demo Tester")
        save_rig(self.ledger, "demo", {
            "session": "demo", "work_dir": "/x/proj",
            "panes": [{"name": "demo Tester", "runtime": "claude_code",
                       "role": "worker", "pane": "%1", "enrolment": "launch",
                       "session_id": "s1", "context_limit": 100_000},
                      {"name": "demo Lead", "runtime": "claude_code",
                       "role": "orchestrator", "pane": "%2",
                       "enrolment": "launch", "session_id": "s2",
                       "context_limit": 100_000}]})
        vault = Vault(self.ledger)
        vault.put(state_key("demo"), "state")
        vault.close()

    def _run(self, entry, *, fraction, confirm=True, **kw):
        typed = []

        def fake_send(pane, text, **k):
            typed.append(text)
            if confirm and "CHECKPOINT NOTE" in text:
                v = Vault(self.ledger)
                v.put(checkpoint_key("demo", entry["name"]),
                      "goal: finish\nnext: step 4")
                v.close()
        screen = (rig.CHECKPOINT_MARKER.format(name=entry["name"])
                  if confirm else "still working")
        with mock.patch("nxb.gauge.fullness",
                        lambda e, **k: (int(fraction * 100_000), 100_000,
                                        fraction)), \
                mock.patch.object(rig, "send_line", fake_send), \
                mock.patch.object(rig, "capture", lambda p: screen), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic",
                                  _clock()):
            out = rig.checkpoint_pane(entry, session="demo",
                                      ledger=self.ledger, repo="/r", **kw)
        return out, typed

    def _entry(self, name):
        return next(p for p in load_rig(self.ledger, "demo")["panes"]
                    if p["name"] == name)

    def test_below_the_threshold_nothing_is_typed(self):
        out, typed = self._run(self._entry("demo Tester"), fraction=0.5)
        self.assertEqual(out["state"], "SKIPPED")
        self.assertEqual(typed, [])

    def test_a_worker_mid_task_is_checkpointed_reset_and_continued(self):
        out, typed = self._run(self._entry("demo Tester"), fraction=0.85)
        self.assertEqual(out["state"], "CHECKPOINTED", out)
        self.assertEqual(out["continued"], self.task)
        self.assertEqual(len(typed), 2)
        request, continuation = typed
        self.assertIn("CHECKPOINT NOTE", request)
        self.assertIn(self.task, request, "the request names the held task")
        self.assertIn(f"--key rigs/demo/checkpoints/Tester", request)
        self.assertFalse(request.startswith("[NXB-AUTOMATED]"),
                         "the request is the operator talking")
        self.assertTrue(continuation.startswith("[NXB-AUTOMATED]"),
                        "the continuation is a directive the rule validates")
        self.assertIn(f"task_id={self.task}", continuation)
        self.assertIn("checkpoints/Tester.md FIRST", continuation)
        self.assertIn("ORIENT FIRST", continuation)
        record = self._entry("demo Tester")
        self.assertTrue(record.get("last_checkpoint_at"))

    def test_an_unconfirmed_checkpoint_resets_nothing(self):
        out, typed = self._run(self._entry("demo Tester"), fraction=0.9,
                               confirm=False, deadline=10)
        self.assertEqual(out["reason"], rig.RIG_CHECKPOINT_UNCONFIRMED)
        self.assertEqual(len(typed), 1, "only the request was typed")
        self.assertFalse(self._entry("demo Tester").get("last_checkpoint_at"))

    def test_an_orchestrator_gets_an_unmarked_continuation(self):
        out, typed = self._run(self._entry("demo Lead"), fraction=0.95)
        self.assertEqual(out["state"], "CHECKPOINTED")
        self.assertEqual(out["continued"], "plan")
        self.assertFalse(typed[1].startswith("[NXB-AUTOMATED]"))
        self.assertIn("continue your plan", typed[1])

    def test_a_worker_with_nothing_outstanding_is_not_checkpointed(self):
        """A worker that has just filed is reset for free by its next
        dispatch; checkpointing it would spend a full-context turn."""
        from nxb.keystroke import file_reply
        file_reply("demo Tester", self.task, "SUMMARY: done.", ledger=self.ledger)
        out, typed = self._run(self._entry("demo Tester"), fraction=0.95)
        self.assertEqual(out["state"], "SKIPPED")
        self.assertIn("no outstanding task", out["detail"])
        self.assertEqual(typed, [])

    def test_force_checkpoints_regardless_of_the_gauge(self):
        out, typed = self._run(self._entry("demo Tester"), fraction=0.1,
                               force=True)
        self.assertEqual(out["state"], "CHECKPOINTED")

    def test_the_refusal_is_published(self):
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        self.assertIn(rig.RIG_CHECKPOINT_UNCONFIRMED, vocab["refusal_vocabulary"])


def _clock():
    tick = [0.0]

    def monotonic():
        tick[0] += 4.0
        return tick[0]
    return monotonic


class TheWatcherReadsTheGaugeAndTypesNothingElse(unittest.TestCase):
    def test_one_pass_reports_every_pane_and_checkpoints_the_full_ones(self):
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "codex", "role": "worker",
             "pane": "%1", "enrolment": "typed", "thread_id": "t1"},
            {"name": "demo B", "runtime": "codex", "role": "worker",
             "pane": "%2", "enrolment": "typed", "thread_id": "t2"}]})
        calls = []

        def fake_plan(entry, **kw):
            calls.append(entry["name"])
            if entry["name"] == "demo A":
                return {"action": "finish", "held": [], "note_path": "/n",
                        "reused": True, "worker": "demo A",
                        "context_fraction": 0.9}
            return {"action": "skip", "result": {
                "state": "SKIPPED", "worker": "demo B",
                "context_fraction": 0.2}}
        lines = []
        with mock.patch.object(rig, "_live_panes", lambda s: {"%1", "%2"}), \
                mock.patch.object(rig, "_plan_checkpoint", fake_plan), \
                mock.patch.object(rig, "_finish_checkpoint",
                                  lambda e, p, **k: {
                                      "state": "CHECKPOINTED",
                                      "worker": e["name"],
                                      "context_fraction": 0.9,
                                      "reused_note": True}), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.watch("demo", ledger=ledger, once=True,
                            out=lines.append)
        self.assertEqual(out["checkpointed"], ["demo A"])
        self.assertEqual(calls, ["demo A", "demo B"])
        self.assertIn("A=90%", lines[0])
        self.assertIn("checkpointed: demo A (from its note)", lines[0])

    def test_a_refused_checkpoint_or_an_exception_does_not_kill_the_watcher(self):
        """MEASURED 2026-09-12: the first watcher on pact-dev died on a
        KeyError summarising a refused checkpoint, and the pane it guarded
        sailed to 106K. A pass must contain its failures."""
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "codex", "role": "worker",
             "pane": "%1", "enrolment": "typed", "thread_id": "t1"}]})
        lines = []
        with mock.patch.object(rig, "_live_panes", lambda s: {"%1"}), \
                mock.patch.object(rig, "_plan_checkpoint",
                                  lambda e, **k: {"action": "finish",
                                                  "held": [], "note_path": "/n",
                                                  "reused": True,
                                                  "worker": e["name"]}), \
                mock.patch.object(rig, "_finish_checkpoint",
                                  lambda e, p, **k: {"state": "REFUSED",
                                                     "reason": "rig_pane_busy",
                                                     "worker": e["name"]}), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.watch("demo", ledger=ledger, once=True, out=lines.append)
        self.assertEqual(out["state"], "PASS")
        self.assertIn("refused: A: rig_pane_busy", lines[0])

        def boom(*a, **k):
            raise RuntimeError("tmux vanished")
        lines = []
        with mock.patch.object(rig, "checkpoint_rig", boom):
            out = rig.watch("demo", ledger=ledger, once=True, out=lines.append)
        self.assertEqual(out["state"], "ERROR")
        self.assertIn("pass failed: RuntimeError", lines[0])

    def test_health_carries_the_gauge(self):
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "codex", "role": "worker",
             "pane": "%1", "enrolment": "typed", "thread_id": "t1",
             "context_limit": 100_000}]})
        with mock.patch.object(rig, "_tmux", lambda *a, **k: mock.Mock(
                returncode=1, stdout="", stderr="")), \
                mock.patch("nxb.gauge.fullness",
                           lambda e, **k: (55_000, 100_000, 0.55)):
            out = rig.health("demo", ledger=ledger)
        pane = out["panes"][0]
        self.assertEqual((pane["context_tokens"], pane["context_fraction"]),
                         (55_000, 0.55))


class RigPanesGetTheCoreToolSet(unittest.TestCase):
    """nxb-082.2. MEASURED: a default interactive pane's first request is
    about 42.7K tokens; with only Bash, Read, Edit, Write, Glob and Grep it
    is about 23.4K. The rest is tool schemas a rig pane never uses, paid on
    every request."""

    def _cmd(self, spec):
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, refusal = rig.launch_command(
                dict(spec), ledger=os.path.join(tmp, "l.db"), repo="/r")
        self.assertIsNone(refusal)
        return cmd

    def test_the_default_is_the_core_set(self):
        cmd = self._cmd({"name": "W", "runtime": "claude_code", "role": "worker"})
        self.assertIn("--tools Bash,Read,Edit,Write,Glob,Grep", cmd)

    def test_all_keeps_everything_and_a_list_is_honoured(self):
        self.assertNotIn("--tools", self._cmd(
            {"name": "W", "runtime": "claude_code", "role": "worker",
             "tools": "all"}))
        cmd = self._cmd({"name": "W", "runtime": "claude_code", "role": "worker",
                         "tools": "Bash, Read, WebFetch"})
        self.assertIn("--tools Bash,Read,WebFetch", cmd)

    def test_codex_is_untouched(self):
        self.assertNotIn("--tools", self._cmd(
            {"name": "W", "runtime": "codex", "role": "worker"}))

    def test_the_command_still_fits_a_pty_line(self):
        cmd = self._cmd({"name": "Worker 3", "runtime": "claude_code",
                         "role": "orchestrator", "model": "claude-fable-5-1",
                         "effort": "xhigh"})
        self.assertLess(len(cmd.encode()), 512)

    def test_the_record_drafts_and_schema_carry_it(self):
        from nxb.keystroke import PANE_RECORD_KEYS
        from nxb.mcp import _AGENT_SCHEMA
        from nxb.studio_drafts import normalize
        self.assertIn("tools", PANE_RECORD_KEYS)
        self.assertIn("tools", _AGENT_SCHEMA["properties"])
        draft = normalize({"session": "s", "working_directory": "~", "agents": [
            {"name": "W", "role": "worker", "runtime": "claude_code",
             "tools": "all"}]})
        self.assertEqual(draft["agents"][0]["tools"], "all")
        plan = rig.compose_agents([{"name": "W", "runtime": "claude_code",
                                    "tools": "core"}])
        self.assertEqual(plan["panes"][0]["tools"], "core")


class UsageReadsThePanesOwnTranscripts(unittest.TestCase):
    def test_per_pane_totals_and_the_largest_context(self):
        tmp, ledger = _ledger()
        path = os.path.join(tmp, "s1.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for cr in (20_000, 50_000):
                handle.write(json.dumps({"type": "assistant", "message": {
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": cr,
                              "cache_creation_input_tokens": 500,
                              "output_tokens": 300}}}) + "\n")
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "claude_code", "role": "worker",
             "pane": "%1", "enrolment": "launch", "session_id": "s1"}]})
        with mock.patch.object(gauge, "_claude_transcript", lambda s: path):
            out = rig.usage("demo", ledger=ledger)
        pane = out["panes"][0]
        self.assertEqual(pane["requests"], 2)
        self.assertEqual(pane["uncached"], 1_020)
        self.assertEqual(pane["cache_read"], 70_000)
        self.assertEqual(pane["output"], 600)
        self.assertEqual(pane["max_context"], 50_510)
        self.assertEqual(out["total"]["requests"], 2)


class TheBriefAndToolsCarryIt(unittest.TestCase):
    def test_the_brief_patches_maps_and_checkpoints(self):
        from nxb.enroll import orchestrator_rule
        text = orchestrator_rule("hub D", ledger="/l/x.db", repo="/r",
                                 session="hub")
        self.assertIn('context patch --key rigs/hub/STATE --section "Done"', text)
        self.assertIn("context map --session hub", text)
        self.assertIn("CHECKPOINTS.", text)
        self.assertNotIn("context put --key rigs/hub/STATE", text)
        for line in text.splitlines():
            if "python3 -m nxb" in line:
                self.assertTrue(line.strip().startswith("PYTHONPATH=/r "), line)

    def test_the_mcp_tools_patch_and_map(self):
        from nxb import mcp
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ,
                             {mcp.LEDGER_ENV: os.path.join(tmp, "l.db")}):
            def call(tool, **args):
                return json.loads(
                    mcp.call_tool(tool, args)["content"][0]["text"])
            call("nxb_context_put", key="rigs/d/STATE", body="# S\n\n## Done\n- a\n")
            out = call("nxb_context_patch", key="rigs/d/STATE",
                       section="Done", body="- a\n- b", append=False)
            self.assertEqual(out["state"], "PATCHED")
            self.assertEqual(call("nxb_context_map", work_dir="/x/p")["state"],
                             "MISSING")
            call("nxb_context_put", key="maps/p", body="modules")
            self.assertEqual(call("nxb_context_map", work_dir="/x/p")["state"],
                             "NOTE")

    def test_the_cli_patches_maps_and_relocates(self):
        import subprocess
        import sys
        tmp = tempfile.mkdtemp()
        ledger = os.path.join(tmp, "l.db")

        def cli(*args):
            proc = subprocess.run(
                [sys.executable, "-m", "nxb", "context", *args,
                 "--ledger", ledger], capture_output=True, text=True,
                cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)))
            return proc.returncode, json.loads(proc.stdout or "{}")
        self.assertEqual(cli("put", "--key", "rigs/d/STATE", "--body",
                             "# S\n\n## Open\n- x")[1]["state"], "WRITTEN")
        code, out = cli("patch", "--key", "rigs/d/STATE", "--section",
                        "Open", "--body", "- y")
        self.assertEqual((code, out["state"]), (0, "PATCHED"))
        code, out = cli("map", "--dir", "/x/proj")
        self.assertEqual((code, out["state"]), (4, "MISSING"))
        code, out = cli("relocate", "--to", os.path.join(tmp, "Obs", "NXB"))
        self.assertEqual((code, out["state"]), (0, "RELOCATED"))
        code, out = cli("state", "--session", "d")
        self.assertEqual(out["state"], "NOTE")
        self.assertIn("/Obs/NXB/", out["path"])


if __name__ == "__main__":
    unittest.main()


class TheSecondLiveRunFixes(unittest.TestCase):
    """RIG-36. MEASURED 2026-09-12 on pact-dev, second live run: the lead
    confirmed a note six passes running and was refused busy each time; a
    worker that confirmed a minute late sat idle for twenty minutes; two
    five-minute waits in series left the rig unwatched while both builders
    sailed past their ceilings; a worker asked for 8,000 characters wrote
    8,713 and spent seven requests trimming; and the checkpoint stamp was
    erased by the pass that made it."""

    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.task = _mint(self.ledger, "demo Tester")
        self.task2 = _mint(self.ledger, "demo Builder")
        save_rig(self.ledger, "demo", {
            "session": "demo", "work_dir": "/x/proj",
            "panes": [{"name": "demo Tester", "runtime": "claude_code",
                       "role": "worker", "pane": "%1", "enrolment": "launch",
                       "session_id": "s1", "context_limit": 100_000},
                      {"name": "demo Builder", "runtime": "claude_code",
                       "role": "worker", "pane": "%2", "enrolment": "launch",
                       "session_id": "s2", "context_limit": 100_000},
                      {"name": "demo Lead", "runtime": "claude_code",
                       "role": "orchestrator", "pane": "%3",
                       "enrolment": "launch", "session_id": "s3",
                       "context_limit": 100_000}]})
        vault = Vault(self.ledger)
        vault.put(state_key("demo"), "state")
        vault.close()

    def _entry(self, name):
        return next(p for p in load_rig(self.ledger, "demo")["panes"]
                    if p["name"] == name)

    def _note(self, name, *, age_s=0):
        vault = Vault(self.ledger)
        out = vault.put(checkpoint_key("demo", name), "goal: x\nnext: 4")
        vault.close()
        if age_s:
            import os
            then = time.time() - age_s
            os.utime(out["path"], (then, then))
        return out["path"]

    def _run_pane(self, entry, *, fraction, screens, **kw):
        """`screens` is a list consumed one per capture; the last repeats."""
        typed, shown = [], list(screens)

        def fake_capture(pane):
            return shown.pop(0) if len(shown) > 1 else shown[0]

        def fake_send(pane, text, **k):
            typed.append(text)
        with mock.patch("nxb.gauge.fullness",
                        lambda e, **k: (int(fraction * 100_000), 100_000,
                                        fraction)), \
                mock.patch.object(rig, "send_line", fake_send), \
                mock.patch.object(rig, "capture", fake_capture), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.checkpoint_pane(entry, session="demo",
                                      ledger=self.ledger, repo="/r", **kw)
        return out, typed

    def test_a_pane_that_printed_its_marker_is_reset_without_being_asked(self):
        """Below the threshold too: it stopped as asked and is waiting."""
        self._note("demo Tester")
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")
        out, typed = self._run_pane(self._entry("demo Tester"), fraction=0.5,
                                    screens=[marker])
        self.assertEqual(out["state"], "CHECKPOINTED", out)
        self.assertTrue(out["reused_note"])
        self.assertEqual(len(typed), 1, "only the continuation was typed")
        self.assertTrue(typed[0].startswith("[NXB-AUTOMATED]"))
        self.assertIn(self.task, typed[0])

    def test_a_note_older_than_the_last_reset_is_asked_for_again(self):
        self._note("demo Tester", age_s=100)
        entry = self._entry("demo Tester")
        import datetime
        entry["last_checkpoint_at"] = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=50)).isoformat(timespec="seconds")
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")
        out, typed = self._run_pane(entry, fraction=0.9, screens=[marker],
                                    deadline=10)
        self.assertIn("CHECKPOINT NOTE", typed[0], "a fresh note was requested")

    def test_a_note_older_than_half_an_hour_is_not_reused(self):
        self._note("demo Tester", age_s=rig.CHECKPOINT_NOTE_FRESH_S + 60)
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")
        out, typed = self._run_pane(self._entry("demo Tester"), fraction=0.9,
                                    screens=[marker], deadline=10)
        self.assertIn("CHECKPOINT NOTE", typed[0])

    def test_a_confirmed_pane_still_mid_turn_keeps_its_note_and_is_not_asked_again(self):
        """The lead's loop: six requests, six busy refusals. Now: zero."""
        path = self._note("demo Lead")
        busy = rig.CHECKPOINT_MARKER.format(name="demo Lead") + " esc to interrupt"
        out, typed = self._run_pane(self._entry("demo Lead"), fraction=0.93,
                                    screens=[busy])
        self.assertEqual(out["reason"], rig.RIG_PANE_BUSY)
        self.assertTrue(out["confirmed"])
        self.assertEqual(out["checkpoint"], path)
        self.assertEqual(typed, [], "nothing typed into a 140K context")

    def test_the_reset_waits_for_the_turn_to_end(self):
        self._note("demo Tester")
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")
        busy = marker + " esc to interrupt"
        out, typed = self._run_pane(self._entry("demo Tester"), fraction=0.9,
                                    screens=[busy, busy, busy, marker])
        self.assertEqual(out["state"], "CHECKPOINTED", out)
        self.assertEqual(len(typed), 1)

    def test_a_pass_asks_every_full_pane_before_waiting_on_any(self):
        typed = []

        names = {"%1": "demo Tester", "%2": "demo Builder", "%3": "demo Lead"}

        def fake_send(pane, text, **k):
            typed.append((pane, text))
            if "CHECKPOINT NOTE" in text:
                self._note(names[pane])

        def fake_capture(pane):
            asked = [p for p, t in typed if "CHECKPOINT NOTE" in t]
            if len(asked) < 3:
                return "working"
            return " ".join(rig.CHECKPOINT_MARKER.format(name=n)
                            for n in names.values())
        with mock.patch("nxb.gauge.fullness",
                        lambda e, **k: (90_000, 100_000, 0.9)), \
                mock.patch.object(rig, "_live_panes",
                                  lambda s: {"%1", "%2", "%3"}), \
                mock.patch.object(rig, "send_line", fake_send), \
                mock.patch.object(rig, "capture", fake_capture), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.checkpoint_rig("demo", ledger=self.ledger)
        kinds = ["ask" if "CHECKPOINT NOTE" in t else "go" for _, t in typed]
        self.assertEqual(kinds[:3], ["ask", "ask", "ask"],
                         "every request goes out before any continuation")
        self.assertEqual(sorted(out["checkpointed"]),
                         ["demo Builder", "demo Lead", "demo Tester"])

    def test_the_stamp_and_a_healed_session_id_both_survive_the_pass(self):
        self._note("demo Tester")
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")

        def healing_fullness(entry, **k):
            if entry["name"] == "demo Tester":
                entry["session_id"] = "s1-rotated"
                return 50_000, 100_000, 0.5
            return 10_000, 100_000, 0.1
        with mock.patch("nxb.gauge.fullness", healing_fullness), \
                mock.patch.object(rig, "_live_panes",
                                  lambda s: {"%1", "%2", "%3"}), \
                mock.patch.object(rig, "send_line", lambda p, t, **k: None), \
                mock.patch.object(rig, "capture",
                                  lambda p: marker if p == "%1" else "idle"), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.checkpoint_rig("demo", ledger=self.ledger)
        self.assertEqual(out["checkpointed"], ["demo Tester"])
        record = self._entry("demo Tester")
        self.assertTrue(record.get("last_checkpoint_at"), record)
        self.assertEqual(record.get("session_id"), "s1-rotated")

    def test_the_codex_ready_marker_survives_a_narrow_pane(self):
        """22-column worker panes truncate the placeholder; the prefix holds."""
        with mock.patch.object(rig, "capture",
                               lambda p: "› Ask Codex to do anyt\n  gpt-6"):
            self.assertEqual(rig.pane_state("%9", "codex"), "READY")

    def test_reset_empties_the_composer_before_clearing_a_claude_pane(self):
        order = []

        def fake_tmux(*args):
            order.append(args)
            return mock.Mock(returncode=0, stdout="", stderr="")

        def fake_send(pane, text, **k):
            order.append(("send", text))
        with mock.patch.object(rig, "_tmux", fake_tmux), \
                mock.patch.object(rig, "send_line", fake_send), \
                mock.patch.object(rig, "capture",
                                  lambda p: "bypass permissions on"), \
                mock.patch.object(rig, "refresh_session_ids",
                                  lambda entries: (entries[0].__setitem__(
                                      "session_id", "s1b") or
                                      {"demo Tester": "s1b"})), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.reset_pane(self._entry("demo Tester"), session="demo",
                                 ledger=self.ledger, repo="/r")
        self.assertEqual(out["state"], "RESET", out)
        kill = order.index(("send-keys", "-t", "%1", "C-u"))
        clear = order.index(("send", "/clear"))
        self.assertLess(kill, clear)

    def test_the_request_asks_for_about_the_cap_and_names_the_hard_limit(self):
        text = rig._checkpoint_request(
            {"name": "demo Tester"}, ledger="/l", repo="/r", key="k",
            outstanding=["nxbt-1"])
        self.assertIn("about 8000 characters", text)
        self.assertIn("never more than 12000", text)
        self.assertIn("cut whole sections", text)


class ANarrowPaneStillReadsBusy(unittest.TestCase):
    """RIG-37. MEASURED 2026-09-13: a 53-column pane cut the footer to
    "esc to inte…" and a builder ten minutes into xcodebuild read idle."""

    def test_the_spinner_line_and_the_cut_footer_both_mean_busy(self):
        from nxb.keystroke import busy_screen
        self.assertTrue(busy_screen("✳ Seasoning… (17m 10s · ↓ 14.1k tokens)\n"
                                    "  ⏵⏵ bypass permissions on · 1 shell · esc to inte…"))
        self.assertTrue(busy_screen("· Flambéing… (6m 45s · ↓ 7.5k tokens)"))
        self.assertTrue(busy_screen("✳ Compacting conversation… (17m 15s)"))
        self.assertTrue(busy_screen("• Working (1m 01s • esc to interrupt)"))
        self.assertFalse(busy_screen("✻ Worked for 14s · done 11:27 PM · 1 shell still running\n"
                                     "  ⏵⏵ bypass permissions on · 1 shell · ← 1 agent"))
        self.assertFalse(busy_screen("[NXB-CHECKPOINT pact-dev Builder 2]\n❯ "))
        self.assertFalse(busy_screen("› Ask Codex to do anything"))


class TheRigReportsItsOwnCost(unittest.TestCase):
    """RIG-38. The window keeps its drafted size; health names narrow panes;
    the watcher names a stalled worker; a collected task logs how long it
    took and how many checkpoints it cost."""

    def test_the_window_is_pinned_to_its_drafted_size(self):
        calls = []

        def fake_tmux(*args):
            calls.append(args)
            if args[0] == "list-panes":
                return mock.Mock(returncode=0, stdout="%1\n", stderr="")
            if args[0] == "split-window":
                return mock.Mock(returncode=0, stdout="%2\n", stderr="")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(rig, "_tmux", fake_tmux):
            ids, refusal = rig._build_window("demo", ["/a", "/b"],
                                             "main-horizontal",
                                             width=240, height=60)
        self.assertIsNone(refusal)
        self.assertEqual(ids, ["%1", "%2"])
        flat = [" ".join(map(str, c)) for c in calls]
        pin = next(i for i, c in enumerate(flat) if "window-size manual" in c)
        size = next(i for i, c in enumerate(flat)
                    if c.startswith("resize-window") and "-x 240 -y 60" in c)
        first_split = next(i for i, c in enumerate(flat)
                           if c.startswith("split-window"))
        self.assertLess(pin, first_split)
        self.assertLess(size, first_split)

    def test_health_names_a_narrow_pane(self):
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "codex", "role": "worker",
             "pane": "%1", "enrolment": "typed", "thread_id": "t1"}]})

        def fake_tmux(*args):
            if args[0] == "list-panes" and "#{pane_id} #{pane_width}" in args:
                return mock.Mock(returncode=0, stdout="%1 22\n", stderr="")
            if args[0] == "list-panes":
                return mock.Mock(returncode=0, stdout="%1\n", stderr="")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(rig, "_tmux", fake_tmux), \
                mock.patch.object(rig, "capture", lambda p: ""), \
                mock.patch("nxb.gauge.fullness", lambda e, **k: (None, None, None)):
            out = rig.health("demo", ledger=ledger)
        self.assertEqual(out["panes"][0]["width"], 22)
        self.assertTrue(out["panes"][0]["narrow"])

    def test_the_watcher_names_a_stalled_worker(self):
        tmp, ledger = _ledger()
        task = _mint(ledger, "demo A")
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "claude_code", "role": "worker",
             "pane": "%1", "enrolment": "launch", "session_id": "s1"}]})
        with mock.patch.object(rig, "_live_panes", lambda s: {"%1"}), \
                mock.patch.object(rig, "capture", lambda p: "❯ "), \
                mock.patch("nxb.keystroke.last_activity_s", lambda e: 700):
            stalled = rig._stalls("demo", ledger=ledger)
        self.assertEqual(stalled, [f"A (11 min, {task})"])
        lines = []
        with mock.patch.object(rig, "_live_panes", lambda s: {"%1"}), \
                mock.patch.object(rig, "_plan_checkpoint",
                                  lambda e, **k: {"action": "skip", "result": {
                                      "state": "SKIPPED", "worker": "demo A",
                                      "context_fraction": 0.3}}), \
                mock.patch.object(rig, "_stalls",
                                  lambda s, **k: ["A (11 min, nxbt-x)"]), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            rig.watch("demo", ledger=ledger, once=True, out=lines.append)
        self.assertIn("| stalled: A (11 min, nxbt-x)", lines[0])

    def test_a_collected_task_logs_its_duration_and_checkpoints(self):
        import datetime
        from nxb.context import log_key, record_report, task_cost
        from nxb.tasks import TaskRegistry
        tmp, ledger = _ledger()
        task = _mint(ledger, "demo A")
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "claude_code", "role": "worker",
             "pane": "%1", "enrolment": "launch", "session_id": "s1",
             "checkpoint_task": task, "checkpoints": 2}]})
        import sqlite3
        then = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(minutes=41)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(ledger)
        conn.execute("UPDATE issued_tasks SET issued_at = ? WHERE task_id = ?",
                     (then, task))
        conn.commit(); conn.close()
        cost = task_cost(ledger, task_id=task, worker="demo A", session="demo")
        self.assertEqual((cost["took_min"], cost["checkpoints"]), (41, 2))
        out = record_report(ledger, task_id=task, worker="demo A",
                            answer="SUMMARY: done.\n" + "x" * 7000,
                            session="demo")
        self.assertEqual((out["took_min"], out["checkpoints"]), (41, 2))
        vault = Vault(ledger)
        log = vault.get(log_key("demo"))["body"]
        vault.close()
        self.assertIn("(took 41 min, 2 checkpoints)", log)


class ARequestIsNeverStackedBehindAnUnansweredOne(unittest.TestCase):
    """RIG-39. MEASURED 2026-09-13 12:41 and 12:47 AM: two passes each typed
    a request into a builder mid-turn; both queued, then sat unsent behind
    an API error. A pending request is waited for, not repeated."""

    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.task = _mint(self.ledger, "demo Tester")
        save_rig(self.ledger, "demo", {
            "session": "demo", "work_dir": "/x/proj",
            "panes": [{"name": "demo Tester", "runtime": "claude_code",
                       "role": "worker", "pane": "%1", "enrolment": "launch",
                       "session_id": "s1", "context_limit": 100_000}]})
        vault = Vault(self.ledger)
        vault.put(state_key("demo"), "state")
        vault.close()

    def _entry(self):
        return next(p for p in load_rig(self.ledger, "demo")["panes"]
                    if p["name"] == "demo Tester")

    def _stamp(self, age_s):
        import datetime
        return (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=age_s)).isoformat(timespec="seconds")

    def _run(self, entry, **kw):
        typed = []
        with mock.patch("nxb.gauge.fullness",
                        lambda e, **k: (90_000, 100_000, 0.9)), \
                mock.patch.object(rig, "send_line",
                                  lambda p, t, **k: typed.append(t)), \
                mock.patch.object(rig, "capture", lambda p: "working"), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.checkpoint_pane(entry, session="demo", ledger=self.ledger,
                                      repo="/r", deadline=10, **kw)
        return out, typed

    def test_a_recent_unanswered_request_is_waited_for(self):
        entry = self._entry()
        entry["checkpoint_requested_at"] = self._stamp(120)
        out, typed = self._run(entry)
        self.assertEqual(out["state"], "PENDING", out)
        self.assertEqual(typed, [])

    def test_an_old_unanswered_request_is_repeated_and_stamped(self):
        entry = self._entry()
        entry["checkpoint_requested_at"] = self._stamp(rig.CHECKPOINT_PENDING_S + 60)
        out, typed = self._run(entry)
        self.assertEqual(out["reason"], rig.RIG_CHECKPOINT_UNCONFIRMED)
        self.assertEqual(len(typed), 1)
        self.assertTrue(self._entry().get("checkpoint_requested_at"),
                        "the new request is stamped on the record")
        self.assertEqual(out["context_fraction"], 0.9,
                         "a refusal still carries the gauge")

    def test_the_stamp_clears_when_the_reset_lands(self):
        entry = self._entry()
        entry["checkpoint_requested_at"] = self._stamp(120)
        vault = Vault(self.ledger)
        vault.put(checkpoint_key("demo", "demo Tester"), "goal\nnext: 2")
        vault.close()
        marker = rig.CHECKPOINT_MARKER.format(name="demo Tester")
        with mock.patch("nxb.gauge.fullness",
                        lambda e, **k: (90_000, 100_000, 0.9)), \
                mock.patch.object(rig, "send_line", lambda p, t, **k: None), \
                mock.patch.object(rig, "capture", lambda p: marker), \
                mock.patch.object(rig, "reset_pane",
                                  lambda e, **k: {"state": "RESET"}), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.checkpoint_pane(entry, session="demo", ledger=self.ledger,
                                      repo="/r")
        self.assertEqual(out["state"], "CHECKPOINTED")
        self.assertIsNone(self._entry().get("checkpoint_requested_at"))


class AClearIsProvenByTheRegistry(unittest.TestCase):
    """RIG-39. A queued message reads busy, and a Claude reset without a
    rotated session id is refused with nothing typed after the clear."""

    def test_a_queued_or_pasted_message_reads_busy(self):
        from nxb.keystroke import busy_screen
        self.assertTrue(busy_screen("❯ Press up to edit queued messages"))
        self.assertTrue(busy_screen("❯ [Pasted text #9 +2 lines]"))

    def test_a_clear_whose_id_did_not_rotate_is_refused(self):
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "claude_code", "role": "worker",
             "pane": "%1", "enrolment": "launch", "session_id": "s1"}]})
        typed = []
        with mock.patch.object(rig, "_tmux", lambda *a: mock.Mock(
                returncode=0, stdout="", stderr="")), \
                mock.patch.object(rig, "send_line",
                                  lambda p, t, **k: typed.append(t)), \
                mock.patch.object(rig, "capture",
                                  lambda p: "bypass permissions on"), \
                mock.patch.object(rig, "refresh_session_ids",
                                  lambda entries: {}), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.reset_pane(load_rig(ledger, "demo")["panes"][0],
                                 session="demo", ledger=ledger, repo="/r")
        self.assertEqual(out["reason"], rig.RIG_RESET_UNCONFIRMED)
        self.assertEqual(typed, ["/clear"], "nothing typed after the clear")
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        self.assertIn(rig.RIG_RESET_UNCONFIRMED, vocab["refusal_vocabulary"])

    def test_a_rotated_id_is_a_reset(self):
        tmp, ledger = _ledger()
        save_rig(ledger, "demo", {"session": "demo", "panes": [
            {"name": "demo A", "runtime": "claude_code", "role": "worker",
             "pane": "%1", "enrolment": "launch", "session_id": "s1"}]})

        def rotate(entries):
            entries[0]["session_id"] = "s2"
            return {"demo A": "s2"}
        with mock.patch.object(rig, "_tmux", lambda *a: mock.Mock(
                returncode=0, stdout="", stderr="")), \
                mock.patch.object(rig, "send_line", lambda p, t, **k: None), \
                mock.patch.object(rig, "capture",
                                  lambda p: "bypass permissions on"), \
                mock.patch.object(rig, "refresh_session_ids", rotate), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.reset_pane(load_rig(ledger, "demo")["panes"][0],
                                 session="demo", ledger=ledger, repo="/r")
        self.assertEqual((out["state"], out["session_id"]), ("RESET", "s2"))


class OnePaneCanBeRelaunchedInPlace(unittest.TestCase):
    """RIG-40. A new ceiling or a wedged pane no longer needs the whole rig
    resumed: one pane leaves its runtime, relaunches with the record's
    flags, and continues its held task from its note."""

    def setUp(self):
        self.tmp, self.ledger = _ledger()
        self.task = _mint(self.ledger, "demo Tester")
        save_rig(self.ledger, "demo", {
            "session": "demo", "work_dir": "/x/proj",
            "panes": [{"name": "demo Tester", "runtime": "claude_code",
                       "role": "worker", "pane": "%1", "enrolment": "launch",
                       "session_id": "s-old", "context_limit": 100_000,
                       "tools": "core", "dir": "/x/proj"}]})
        vault = Vault(self.ledger)
        vault.put(state_key("demo"), "state")
        vault.put(checkpoint_key("demo", "demo Tester"), "goal\nnext: 3")
        vault.close()

    def test_relaunch_changes_the_ceiling_and_continues_from_the_note(self):
        calls, typed, cmds = [], [], iter(["claude", "claude", "zsh"])
        screen = {"text": ""}

        def fake_tmux(*args):
            calls.append(args)
            if args[0] == "display":
                return mock.Mock(returncode=0, stdout=next(cmds, "zsh") + "\n")
            if args[0] == "list-panes":
                return mock.Mock(returncode=0, stdout="%1\n", stderr="")
            return mock.Mock(returncode=0, stdout="", stderr="")

        def fake_send(pane, text, **k):
            typed.append(text)
            if text.startswith("echo NXB-SHELL-READY-"):
                screen["text"] = text.split(" ", 1)[1]   # the prompt echoes it

        def fake_launch(spec, **k):
            return (f"claude --autocompact {spec['context_limit'] + 45000} "
                    f"--session-id {spec['session_id']}", "launch", None)
        with mock.patch.object(rig, "_tmux", fake_tmux), \
                mock.patch.object(rig, "_live_panes", lambda s: {"%1"}), \
                mock.patch.object(rig, "send_line", fake_send), \
                mock.patch.object(rig, "launch_command", fake_launch), \
                mock.patch.object(rig, "await_ready", lambda p, r, **k: (True, None)), \
                mock.patch.object(rig, "refresh_session_ids", lambda e: {}), \
                mock.patch.object(rig, "capture", lambda p: screen["text"]), \
                mock.patch.object(rig.time, "sleep", lambda s: None):
            out = rig.relaunch_pane("demo Tester", session="demo",
                                    ledger=self.ledger, repo="/r",
                                    context_limit=140_000)
        self.assertEqual(out["state"], "RELAUNCHED", out)
        self.assertEqual(out["context_limit"], 140_000)
        self.assertEqual(out["continued"], self.task)
        respawn = [c for c in calls if c[:2] == ("respawn-pane", "-k")]
        self.assertEqual(len(respawn), 1, "the pane's process is replaced in place")
        self.assertTrue(typed[0].startswith("echo NXB-SHELL-READY-"),
                        "the shell proves its prompt before the launch")
        self.assertIn("--autocompact 185000", typed[1])
        self.assertTrue(typed[2].startswith("[NXB-AUTOMATED]"))
        self.assertIn("after a relaunch", typed[2])
        self.assertIn("checkpoints/Tester.md FIRST", typed[2])
        record = load_rig(self.ledger, "demo")["panes"][0]
        self.assertEqual(record["context_limit"], 140_000)
        self.assertNotEqual(record["session_id"], "s-old")
        self.assertEqual(record["enrolment"], "launch")

    def test_a_runtime_that_will_not_leave_is_refused_and_nothing_launched(self):
        typed = []
        with mock.patch.object(rig, "_tmux", lambda *a: mock.Mock(
                returncode=0, stdout="claude\n", stderr="")), \
                mock.patch.object(rig, "_live_panes", lambda s: {"%1"}), \
                mock.patch.object(rig, "send_line",
                                  lambda p, t, **k: typed.append(t)), \
                mock.patch.object(rig, "capture", lambda p: "still here"), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch.object(rig.time, "monotonic", _clock()):
            out = rig.relaunch_pane("demo Tester", session="demo",
                                    ledger=self.ledger, repo="/r")
        self.assertEqual(out["reason"], rig.RIG_RELAUNCH_UNCONFIRMED)
        self.assertEqual(typed, [], "nothing launched after a refusal")
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        self.assertIn(rig.RIG_RELAUNCH_UNCONFIRMED, vocab["refusal_vocabulary"])
