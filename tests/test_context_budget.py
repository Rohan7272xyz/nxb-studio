"""nxb-079: the context budget.

MEASURED on the 25-pane Pact programme, 2026-09-07 to 09-10 (see
docs/CONTEXT-BUDGET-nxb-079.md): 11,779 Codex requests carried 1.48 billion
input tokens; 68 orchestrator turns that polled `rig collect` in a loop were
43 percent of it; Claude reviewer panes ran to 930K of context and re-read it
on every request; two host restarts rebuilt every pane from nothing and
re-dispatched work whose ids were still open; a stall watcher typed thirteen
nudges overnight. Each class below pins one of the mechanisms that closes one
of those.
"""

import inspect
import json
import os
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from nxb import enroll, keystroke, rig
from nxb.keystroke import (collect_reply, dispatch, file_reply, load_rig,
                           marked_directive, outstanding_tasks, save_rig,
                           send_directive)
from nxb.roster import Roster, RosterEntry
from nxb.tasks import TaskRegistry

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _ledger():
    """A REAL ledger in a temp dir, so `outstanding` and filing are exercised."""
    tmp = tempfile.mkdtemp()
    return os.path.join(tmp, "ledger.db")


def _mint(ledger, worker="W"):
    reg = TaskRegistry(ledger)
    try:
        task_id, refusal = reg.mint(
            worker, Roster([RosterEntry("%1", name=worker, alive=True,
                                        source="rig")]))
    finally:
        reg.close()
    assert refusal is None, refusal
    return task_id


def _pane(name="W", runtime="codex", enrolment="typed"):
    return {"name": name, "runtime": runtime, "pane": "%9",
            "enrolment": enrolment, "thread_id": "t"}


class CollectWaitsInsideItself(unittest.TestCase):
    """RIG-24. One command that waits replaces a polling loop of model
    round-trips, each of which re-sends the orchestrator's whole context."""

    def _run(self, ledger, task_id, *, wait, screen="", on_sleep=None):
        """A FAKE CLOCK: sleeping advances it, so a 600-second wait costs
        no wall time and the deadline arithmetic is still exercised."""
        sleeps, clock = [], [0.0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
            if on_sleep:
                on_sleep(len(sleeps))
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (_pane(), "s", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: screen), \
                mock.patch.object(keystroke.time, "sleep", fake_sleep), \
                mock.patch.object(keystroke.time, "monotonic",
                                  lambda: clock[0]):
            out = collect_reply("W", task_id, ledger=ledger, wait=wait)
        return out, sleeps

    def test_a_reply_filed_during_the_wait_returns_before_the_deadline(self):
        ledger = _ledger()
        task_id = _mint(ledger)

        def file_on_second_sleep(n):
            if n == 2:
                file_reply("W", task_id, "42", ledger=ledger)
        out, sleeps = self._run(ledger, task_id, wait=600,
                                on_sleep=file_on_second_sleep)
        self.assertEqual(out["state"], "ANSWERED")
        self.assertEqual(out["source"], "outbox")
        self.assertEqual(out["answer"], "42")
        self.assertIn("waited_s", out)
        self.assertEqual(len(sleeps), 2, "it returned as soon as the reply "
                                         "landed, not at the deadline")

    def test_the_backoff_grows_and_never_sleeps_past_the_deadline(self):
        ledger = _ledger()
        task_id = _mint(ledger)
        with mock.patch.object(keystroke, "_WAIT_POLL_MAX_S", 15.0):
            out, sleeps = self._run(ledger, task_id, wait=60)
        self.assertEqual(out["state"], "WAITING")
        self.assertTrue(sleeps, "a wait with no answer must actually wait")
        self.assertEqual(sleeps[0], 2.0)
        body = sleeps[:-1]              # the last one is clipped to the deadline
        self.assertTrue(all(b >= a for a, b in zip(body, body[1:])))
        self.assertLessEqual(max(sleeps), 15.0)
        self.assertLessEqual(sum(sleeps), 60.0 + 1e-9,
                             "the last sleep is clipped to the deadline")
        self.assertEqual(out["waited_s"], 60.0)

    def test_without_wait_it_never_sleeps(self):
        ledger = _ledger()
        task_id = _mint(ledger)
        out, sleeps = self._run(ledger, task_id, wait=0)
        self.assertEqual(out["state"], "WAITING")
        self.assertEqual(sleeps, [])
        self.assertNotIn("waited_s", out)

    def test_a_WAITING_payload_is_small(self):
        """Every byte of it lands in the orchestrator's context and stays
        there until compaction. The Pact Director polled 704 times."""
        ledger = _ledger()
        task_id = _mint(ledger)
        screen = "\n".join(f"line {i} " + "x" * 120 for i in range(300))
        out, _ = self._run(ledger, task_id, wait=0, screen=screen)
        self.assertEqual(out["state"], "WAITING")
        self.assertLessEqual(len(out["tail"].splitlines()),
                             keystroke.WAITING_TAIL_LINES)
        self.assertLessEqual(len(out["tail"]),
                             keystroke.WAITING_TAIL_CHARS + 1)
        self.assertLess(len(out["detail"]), 320)
        self.assertIn("busy", out)

    def test_an_answer_read_off_the_pane_is_RECORDED(self):
        """RIG-27. Until it is on disk, a task collected from a screen counts
        as outstanding forever, and mint would refuse the worker's next task
        on the strength of a reply that was already read."""
        ledger = _ledger()
        task_id = _mint(ledger)
        self.assertEqual([t["task_id"] for t in outstanding_tasks(ledger, "W")],
                         [task_id])
        screen = (marked_directive(task_id, "W", "count", ledger=ledger,
                                   repo="/r")
                  + "\n42\n" + keystroke.done_marker(task_id) + "\n")
        out, _ = self._run(ledger, task_id, wait=0, screen=screen)
        self.assertEqual(out["state"], "ANSWERED")
        self.assertEqual(out["source"], "pane")
        self.assertEqual(outstanding_tasks(ledger, "W"), [])
        again, _ = self._run(ledger, task_id, wait=0, screen="")
        self.assertEqual(again["state"], "ANSWERED",
                         "the recorded answer survives the screen scrolling")
        self.assertEqual(again["source"], "pane")
        self.assertEqual(again["answer"], "42")

    def test_a_mocked_ledger_path_records_nothing(self):
        """The record is written only when the ledger is real, so a test
        pointing at /tmp/l.db cannot leave a file that changes the next run."""
        out, _ = self._run("/tmp/nxb-does-not-exist/l.db", "nxbt-x", wait=0,
                           screen=(marked_directive("nxbt-x", "W", "c")
                                   + "\n1\n[NXB-DONE nxbt-x]\n"))
        self.assertEqual(out["state"], "ANSWERED")
        self.assertFalse(os.path.exists("/tmp/nxb-does-not-exist"))


class AwaitAnyReturnsOnTheFirstAnswer(unittest.TestCase):
    def test_returns_when_any_task_answers_and_names_the_rest(self):
        from nxb.keystroke import await_any
        ledger = _ledger()
        a, b = _mint(ledger, "A"), _mint(ledger, "B")
        file_reply("B", b, "done", ledger=ledger)
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (_pane(name=w), "s", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: ""), \
                mock.patch.object(keystroke.time, "sleep", lambda s: None):
            out = await_any([a, b, "nxbt-unknown"], ledger=ledger, wait=30)
        self.assertEqual(out["state"], "ANSWERED")
        self.assertEqual([x["task_id"] for x in out["answered"]], [b])
        self.assertEqual([x["task_id"] for x in out["waiting"]], [a])
        self.assertEqual(out["unknown_task_ids"], ["nxbt-unknown"])


class MintRefusesABusyWorker(unittest.TestCase):
    """RIG-27. One outstanding directive per worker, enforced where ids are
    issued rather than asked for in a brief."""

    def _mint(self, ledger, supersede=None):
        from nxb.minting import mint_task
        roster = types.SimpleNamespace(entries=[
            RosterEntry("%1", name="W", alive=True, source="rig")])
        with mock.patch("nxb.roster.discover", lambda: roster), \
                mock.patch("nxb.rig.live_rig_sessions", lambda l: []):
            return mint_task(ledger, "W", supersede=supersede)

    def test_a_second_id_is_refused_until_the_first_is_filed(self):
        from nxb.minting import TASK_WORKER_BUSY
        ledger = _ledger()
        first, refusal = self._mint(ledger)
        self.assertIsNone(refusal)
        second, refusal = self._mint(ledger)
        self.assertIsNone(second)
        self.assertEqual(refusal["reason"], TASK_WORKER_BUSY)
        self.assertIn(first, refusal["detail"])
        self.assertTrue(any("--wait" in r for r in refusal["remedy"]))
        file_reply("W", first, "done", ledger=ledger)
        third, refusal = self._mint(ledger)
        self.assertIsNone(refusal)
        self.assertNotEqual(third, first)

    def test_supersede_revokes_the_old_id_in_the_same_step(self):
        ledger = _ledger()
        first, _ = self._mint(ledger)
        second, refusal = self._mint(ledger, supersede=first)
        self.assertIsNone(refusal)
        reg = TaskRegistry(ledger)
        try:
            self.assertEqual(reg.validate(first, "W")["verdict"],
                             "task_revoked")
            self.assertTrue(reg.validate(second, "W")["valid"])
        finally:
            reg.close()

    def test_superseding_an_id_the_worker_does_not_hold_is_refused(self):
        ledger = _ledger()
        self._mint(ledger)
        _, refusal = self._mint(ledger, supersede="nxbt-nope")
        self.assertIsNotNone(refusal)
        self.assertIn("nothing to supersede", refusal["detail"])

    def test_the_refusal_is_published(self):
        from nxb.minting import TASK_WORKER_BUSY
        vocab = json.loads((ROOT / "contract" / "roster.json").read_text())
        self.assertIn(TASK_WORKER_BUSY, vocab["refusal_vocabulary"])


class ALiveWorkerIsNeverSuperseded(unittest.TestCase):
    """RIG-35. MEASURED on pact-dev: an orchestrator superseded a task whose
    worker had the fix done and the tests running, because a WAITING looked
    idle. The transcript's age is the liveness signal, and it is enforced."""

    def _mint(self, ledger, *, supersede=None, force=False, age=None,
              busy=False):
        from nxb.minting import mint_task
        roster = types.SimpleNamespace(entries=[
            RosterEntry("%1", name="W", alive=True, source="rig")])
        pane = {"name": "W", "runtime": "claude_code", "pane": "%1",
                "enrolment": "launch", "session_id": "s"}
        with mock.patch("nxb.roster.discover", lambda: roster), \
                mock.patch("nxb.rig.live_rig_sessions", lambda l: []), \
                mock.patch("nxb.keystroke._resolve",
                           lambda w, l, s: (pane, "s", None)), \
                mock.patch("nxb.keystroke.last_activity_s", lambda e: age), \
                mock.patch("nxb.rig.capture",
                           lambda p: "… esc to interrupt" if busy else "idle"):
            return mint_task(ledger, "W", supersede=supersede, force=force)

    def test_superseding_a_worker_that_just_spoke_is_refused(self):
        from nxb.minting import TASK_WORKER_ACTIVE
        ledger = _ledger()
        first, _ = self._mint(ledger)
        second, refusal = self._mint(ledger, supersede=first, age=40)
        self.assertIsNone(second)
        self.assertEqual(refusal["reason"], TASK_WORKER_ACTIVE)
        self.assertEqual(refusal["last_activity_s"], 40)
        self.assertIn("live work", refusal["detail"])

    def test_a_busy_screen_refuses_too_and_a_still_worker_may_be_superseded(self):
        ledger = _ledger()
        first, _ = self._mint(ledger)
        _, refusal = self._mint(ledger, supersede=first, age=None, busy=True)
        self.assertEqual(refusal["reason"], "task_worker_active")
        second, refusal = self._mint(ledger, supersede=first, age=900)
        self.assertIsNone(refusal)
        self.assertNotEqual(second, first)

    def test_force_overrides(self):
        ledger = _ledger()
        first, _ = self._mint(ledger)
        second, refusal = self._mint(ledger, supersede=first, age=5, force=True)
        self.assertIsNone(refusal)

    def test_waiting_carries_the_transcripts_age(self):
        ledger = _ledger()
        task_id = _mint(ledger)
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (_pane(), "s", None)), \
                mock.patch("nxb.rig.capture_history", lambda p, **k: ""), \
                mock.patch.object(keystroke, "last_activity_s", lambda e: 42):
            out = collect_reply("W", task_id, ledger=ledger)
        self.assertEqual(out["state"], "WAITING")
        self.assertEqual(out["last_activity_s"], 42)
        self.assertIn("42 s ago", out["detail"])
        self.assertIn("never supersede", out["detail"])

    def test_the_refusal_is_published_and_the_brief_teaches_it(self):
        from nxb.enroll import orchestrator_rule
        from nxb.minting import TASK_WORKER_ACTIVE
        vocab = json.loads((ROOT / "contract" / "roster.json").read_text())
        self.assertIn(TASK_WORKER_ACTIVE, vocab["refusal_vocabulary"])
        self.assertIn("Never supersede a working worker",
                      orchestrator_rule("O", ledger="/l", repo="/r", session="s"))


class SendStartsTheWorkerFresh(unittest.TestCase):
    """RIG-25. A worker that carries its last task's context pays for it on
    every request of the next one."""

    def _send(self, ledger, task_id, *, fresh, reset_state="RESET",
              pane=None):
        calls = {"reset": [], "typed": []}

        def fake_reset(entry, **kw):
            calls["reset"].append(entry["name"])
            return {"state": reset_state, "detail": "x"}

        def fake_send_line(p, text, **kw):
            calls["typed"].append(text)
        with mock.patch.object(keystroke, "_resolve",
                               lambda w, l, s: (pane or _pane(), "s", None)), \
                mock.patch("nxb.rig.reset_pane", fake_reset), \
                mock.patch("nxb.rig.send_line", fake_send_line):
            out = send_directive("W", task_id, "do it", ledger=ledger,
                                 fresh=fresh)
        return out, calls

    def test_send_resets_an_idle_worker_BEFORE_typing(self):
        ledger = _ledger()
        task_id = _mint(ledger)
        out, calls = self._send(ledger, task_id, fresh=True)
        self.assertEqual(out["state"], "TYPED")
        self.assertEqual(out["context"], "fresh")
        self.assertEqual(calls["reset"], ["W"])
        self.assertEqual(len(calls["typed"]), 1)
        self.assertTrue(calls["typed"][0].startswith(enroll.MARKER))
        self.assertIn("--wait", out["collect_with"])

    def test_a_fresh_send_REFUSES_a_worker_with_an_unfiled_task(self):
        ledger = _ledger()
        older = _mint(ledger)
        reg = TaskRegistry(ledger)
        try:            # a second id, minted around the busy check on purpose
            newer, _ = reg.mint("W", Roster([RosterEntry(
                "%1", name="W", alive=True, source="rig")]))
        finally:
            reg.close()
        out, calls = self._send(ledger, newer, fresh=True)
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], keystroke.KEYSTROKE_WORKER_BUSY)
        self.assertEqual([t["task_id"] for t in out["outstanding"]], [older])
        self.assertEqual(calls["reset"], [], "a busy worker is never cleared")
        self.assertEqual(calls["typed"], [], "and nothing was typed")

    def test_keep_context_types_without_a_reset_and_names_the_queue(self):
        ledger = _ledger()
        older = _mint(ledger)
        reg = TaskRegistry(ledger)
        try:
            newer, _ = reg.mint("W", Roster([RosterEntry(
                "%1", name="W", alive=True, source="rig")]))
        finally:
            reg.close()
        out, calls = self._send(ledger, newer, fresh=False)
        self.assertEqual(out["state"], "TYPED")
        self.assertEqual(out["context"], "kept")
        self.assertEqual(calls["reset"], [])
        self.assertEqual(out["queued_behind"], [older])

    def test_a_failed_reset_means_NOTHING_was_typed(self):
        ledger = _ledger()
        task_id = _mint(ledger)
        out, calls = self._send(ledger, task_id, fresh=True,
                                reset_state="REFUSED")
        self.assertEqual(out["state"], "REFUSED")
        self.assertIn("NOT typed", out["detail"])
        self.assertEqual(calls["typed"], [])

    def test_the_refusal_is_published(self):
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        self.assertIn(keystroke.KEYSTROKE_WORKER_BUSY,
                      vocab["refusal_vocabulary"])


class DispatchIsOneCall(unittest.TestCase):
    """RIG-24. mint + send in one command: one model round-trip, not two."""

    def test_dispatch_mints_then_sends_and_reports_both(self):
        ledger = _ledger()
        with mock.patch("nxb.minting.mint_task",
                        lambda l, w, **kw: ("nxbt-minted", None)), \
                mock.patch.object(keystroke, "send_directive",
                                  lambda w, t, b, **kw: {"state": "TYPED",
                                                         "task_id": t}):
            out = dispatch("W", "body", ledger=ledger)
        self.assertEqual(out["state"], "TYPED")
        self.assertEqual(out["task_id"], "nxbt-minted")
        self.assertTrue(out["minted"])

    def test_a_directive_that_never_landed_revokes_its_id(self):
        """Otherwise the worker is left 'busy' on a task it never received,
        and the next dispatch is refused for it."""
        ledger = _ledger()
        task_id = _mint(ledger)
        with mock.patch("nxb.minting.mint_task",
                        lambda l, w, **kw: (task_id, None)), \
                mock.patch.object(keystroke, "send_directive",
                                  lambda w, t, b, **kw: {"state": "REFUSED",
                                                         "reason": "x"}):
            out = dispatch("W", "body", ledger=ledger)
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["revoked_task_id"], task_id)
        self.assertEqual(outstanding_tasks(ledger, "W"), [])

    def test_a_mint_refusal_is_returned_as_is(self):
        with mock.patch("nxb.minting.mint_task",
                        lambda l, w, **kw: (None, {"state": "REFUSED",
                                                   "reason": "r"})):
            out = dispatch("W", "body", ledger="/tmp/x/l.db")
        self.assertEqual(out["reason"], "r")


class EveryLaunchCarriesAContextCeiling(unittest.TestCase):
    """RIG-25. The model is not the cost; the context each request carries
    is. Both CLIs take a ceiling, and every pane gets one."""

    def _cmd(self, spec):
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, refusal = rig.launch_command(
                dict(spec), ledger=os.path.join(tmp, "l.db"), repo="/r")
        self.assertIsNone(refusal)
        return cmd

    def test_the_runtime_defaults_are_passed_when_nothing_is_set(self):
        cc = self._cmd({"name": "W", "runtime": "claude_code", "role": "worker"})
        cx = self._cmd({"name": "W", "runtime": "codex", "role": "worker"})
        self.assertIn(f"--autocompact "
                      f"{rig.runtime_backstop('claude_code', rig.DEFAULT_CONTEXT_LIMIT['claude_code'])}",
                      cc)
        self.assertIn(f"model_auto_compact_token_limit="
                      f"{rig.runtime_backstop('codex', rig.DEFAULT_CONTEXT_LIMIT['codex'])}", cx)

    def test_the_runtime_flag_sits_ABOVE_the_ceiling_by_the_measured_margin(self):
        """MEASURED 2026-09-12: `--autocompact 100000` compacted a fresh
        Opus worker at 67K tokens, a few reads into its first task, because
        the flag names a window and Claude Code compacts about 33K below it.
        The ceiling nxb checkpoints at is context_limit; the runtime's
        compaction must fire only if the watcher did not."""
        self.assertEqual(rig.runtime_backstop("claude_code", 100_000), 145_000)
        self.assertEqual(rig.runtime_backstop("codex", 100_000), 120_000)
        self.assertEqual(rig.runtime_backstop("claude_code", 60_000), 105_000)
        self.assertEqual(rig.runtime_backstop("codex", 240_000), 250_000)
        self.assertIsNone(rig.runtime_backstop("claude_code", 0))
        cc = self._cmd({"name": "W", "runtime": "claude_code", "role": "worker",
                        "context_limit": 100_000})
        self.assertIn("--autocompact 145000", cc)

    def test_a_per_agent_ceiling_overrides_and_zero_disables(self):
        cc = self._cmd({"name": "W", "runtime": "claude_code", "role": "worker",
                        "context_limit": 300000})
        self.assertIn("--autocompact 345000", cc)
        off = self._cmd({"name": "W", "runtime": "codex", "role": "worker",
                         "context_limit": 0})
        self.assertNotIn("model_auto_compact_token_limit", off)

    def test_a_ceiling_below_the_runtime_floor_is_refused_at_composition(self):
        with self.assertRaises(ValueError):
            rig.compose_agents([{"name": "W", "runtime": "claude_code",
                                 "context_limit": 40000}])
        with self.assertRaises(ValueError):
            rig.compose_agents([{"name": "W", "runtime": "codex",
                                 "context_limit": "lots"}])
        plan = rig.compose_agents([{"name": "W", "runtime": "codex",
                                    "context_limit": 100000}])
        self.assertEqual(plan["panes"][0]["context_limit"], 100000)

    def test_drafts_carry_the_ceiling_and_validate_it(self):
        from nxb.studio_drafts import DraftError, normalize
        spec = {"session": "s", "working_directory": "~", "agents": [
            {"name": "W", "role": "worker", "runtime": "claude_code",
             "context_limit": 250000}]}
        self.assertEqual(normalize(spec)["agents"][0]["context_limit"], 250000)
        spec["agents"][0]["context_limit"] = 1
        with self.assertRaises(DraftError):
            normalize(spec)

    def test_the_mcp_schema_offers_it(self):
        from nxb.mcp import _AGENT_SCHEMA
        self.assertIn("context_limit", _AGENT_SCHEMA["properties"])

    def test_the_studio_page_has_a_field_for_it(self):
        html = (ROOT / "nxb" / "studio.html").read_text()
        self.assertIn('id="fCtx"', html)
        self.assertIn("context_limit", html)

    def test_the_doctor_checks_the_flag_and_the_config_key(self):
        text = (ROOT / "nxb" / "doctor.py").read_text()
        self.assertIn("--autocompact", text)
        self.assertIn("model_auto_compact_token_limit", text)


class TheRecordHoldsWhatAResumeNeeds(unittest.TestCase):
    """RIG-26. A rig that went down with the machine comes back on its
    original conversations, never rebuilt from nothing by default."""

    def _cmd(self, spec):
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _, refusal = rig.launch_command(
                dict(spec), ledger=os.path.join(tmp, "l.db"), repo="/r")
        self.assertIsNone(refusal)
        return cmd

    def test_a_claude_launch_pins_its_session_id(self):
        cmd = self._cmd({"name": "W", "runtime": "claude_code",
                         "role": "worker", "session_id": "abc-123"})
        self.assertIn("--session-id abc-123", cmd)
        self.assertNotIn("--resume", cmd)

    def test_a_claude_resume_line_reopens_the_session(self):
        cmd = self._cmd({"name": "W", "runtime": "claude_code",
                         "role": "worker", "resume_session_id": "abc-123"})
        self.assertIn("--resume abc-123", cmd)
        self.assertIn("-n 'W'", cmd)
        self.assertIn("--append-system-prompt", cmd)

    def test_a_codex_resume_line_puts_flags_before_the_subcommand(self):
        cmd = self._cmd({"name": "W", "runtime": "codex", "role": "worker",
                         "model": "gpt-6-astra", "effort": "max",
                         "resume_thread_id": "01a0-thread"})
        self.assertTrue(cmd.endswith("resume 01a0-thread"), cmd)
        self.assertLess(cmd.index("-m gpt-6-astra"), cmd.index("resume "))
        self.assertLess(cmd.index("model_auto_compact"), cmd.index("resume "))

    def test_the_record_keeps_ids_roles_and_the_window(self):
        ledger = _ledger()
        save_rig(ledger, "r", {
            "session": "r", "peers": ["p"], "work_dir": "/w",
            "layout": "tiled", "width": 200, "height": 50, "repo": "/repo",
            "panes": [{"name": "r A", "runtime": "claude_code",
                       "role": "orchestrator", "pane": "%1",
                       "enrolment": "launch", "session_id": "s1",
                       "instructions": "Lead.", "dir": "/w/a",
                       "context_limit": 200000},
                      {"name": "r B", "runtime": "codex", "role": "worker",
                       "pane": "%2", "enrolment": "typed", "thread_id": "t1",
                       "instructions": "Build.", "context_limit": 0}]})
        back = load_rig(ledger, "r")
        self.assertEqual(back["work_dir"], "/w")
        self.assertEqual(back["layout"], "tiled")
        self.assertEqual(back["panes"][0]["session_id"], "s1")
        self.assertEqual(back["panes"][0]["instructions"], "Lead.")
        self.assertEqual(back["panes"][1]["thread_id"], "t1")
        self.assertEqual(back["panes"][1]["context_limit"], 0)

    def _fake_tmux(self, standing):
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            rc, out = 0, ""
            if args[0] == "has-session":
                rc = 0 if standing else 1
            elif args[0] == "list-panes":
                out = "%1\n"
            elif args[0] == "split-window":
                out = "%2\n"
            return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")
        return fake, calls

    def _record(self, ledger, with_ids=True):
        save_rig(ledger, "r", {
            "session": "r", "peers": [], "work_dir": "/w", "layout": "tiled",
            "panes": [{"name": "r CX", "runtime": "codex", "role": "worker",
                       "pane": "%old1", "enrolment": "typed",
                       "thread_id": "t1" if with_ids else None,
                       "instructions": "Build."},
                      {"name": "r CC", "runtime": "claude_code",
                       "role": "orchestrator", "pane": "%old2",
                       "enrolment": "launch",
                       "session_id": "s1" if with_ids else None}]})

    def test_resume_refuses_a_record_without_conversation_ids(self):
        ledger = _ledger()
        self._record(ledger, with_ids=False)
        fake, _ = self._fake_tmux(standing=False)
        with mock.patch.object(rig, "_tmux", fake), \
                mock.patch.object(rig.shutil, "which", lambda c: "/usr/bin/x"):
            out = rig.resume("r", ledger=ledger)
        self.assertEqual(out["reason"], rig.RIG_NOT_RESUMABLE)

    def test_a_claude_pane_that_never_spoke_is_relaunched_fresh_not_resumed(self):
        """MEASURED on pact-dev: a pinned session id with no transcript is
        refused by `claude --resume`; the pane came back REFUSED while its
        siblings resumed."""
        ledger = _ledger()
        self._record(ledger)
        out, typed = self._resume(ledger, transcripts=())
        self.assertEqual(out["state"], "RESUMED", out)
        self.assertEqual(out["resumed"], ["r CX"])
        self.assertEqual(out["relaunched"], ["r CC"])
        lines = dict(typed)
        self.assertIn("--session-id", lines["%2"])
        self.assertNotIn("--resume", lines["%2"])
        back = load_rig(ledger, "r")
        self.assertNotEqual(back["panes"][1]["session_id"], "s1")

    def test_resume_refuses_a_rig_that_is_standing(self):
        ledger = _ledger()
        self._record(ledger)
        fake, _ = self._fake_tmux(standing=True)
        with mock.patch.object(rig, "_tmux", fake), \
                mock.patch.object(rig.shutil, "which", lambda c: "/usr/bin/x"):
            out = rig.resume("r", ledger=ledger)
        self.assertEqual(out["reason"], rig.RIG_SESSION_EXISTS)

    def _resume(self, ledger, outstanding=(), transcripts=("s1",), **kw):
        fake, calls = self._fake_tmux(standing=False)
        typed = []
        with mock.patch("nxb.gauge._claude_transcript",
                        lambda sid: f"/t/{sid}.jsonl" if sid in transcripts
                        else None), \
                mock.patch.object(rig, "_tmux", fake), \
                mock.patch.object(rig.shutil, "which", lambda c: "/usr/bin/x"), \
                mock.patch.object(rig, "send_line",
                                  lambda p, t, **k: typed.append((p, t))), \
                mock.patch.object(rig, "await_ready",
                                  lambda p, r, **k: (True, None)), \
                mock.patch.object(rig, "capture", lambda p: "r CX footer"), \
                mock.patch.object(rig.time, "sleep", lambda s: None), \
                mock.patch("nxb.keystroke.outstanding_tasks",
                           lambda l, w=None: list(outstanding)):
            out = rig.resume("r", ledger=ledger, **kw)
        return out, typed

    def test_each_pane_reopens_its_own_conversation(self):
        ledger = _ledger()
        self._record(ledger)
        out, typed = self._resume(ledger)
        self.assertEqual(out["state"], "RESUMED", out)
        self.assertEqual(sorted(out["resumed"]), ["r CC", "r CX"])
        self.assertEqual(out["relaunched"], [])
        lines = dict(typed)
        self.assertIn("resume t1", lines["%1"])
        self.assertIn("--resume s1", lines["%2"])
        self.assertIn("-n 'r CC'", lines["%2"])
        self.assertEqual(len(typed), 2, "a resumed pane is not re-enrolled "
                                        "unless asked: its rule is in the "
                                        "transcript it reopened")
        back = load_rig(ledger, "r")
        self.assertEqual([p["pane"] for p in back["panes"]], ["%1", "%2"])
        self.assertTrue(back.get("resumed_at"))
        self.assertEqual(back["panes"][0]["thread_id"], "t1")
        self.assertTrue(out["panes"][0]["name_seen"])

    def test_continue_notes_go_only_to_panes_with_outstanding_tasks(self):
        ledger = _ledger()
        self._record(ledger)
        out, typed = self._resume(
            ledger, outstanding=[{"task_id": "nxbt-1", "worker": "r CX",
                                  "issued_at": "2026-09-12T00:00:00+00:00"}],
            continue_notes=True)
        self.assertEqual(out["outstanding"], {"r CX": ["nxbt-1"]})
        notes = [(p, t) for p, t in typed if "Operator note" in t]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0][0], "%1")
        self.assertIn("nxbt-1", notes[0][1])
        self.assertIn("do not start over", notes[0][1])
        self.assertFalse(notes[0][1].startswith(enroll.MARKER),
                         "a continuation is the operator talking, unmarked")

    def test_the_studio_offers_resume_only_for_a_downed_rig_with_ids(self):
        from nxb.studio import Studio
        ledger = _ledger()
        self._record(ledger)
        with mock.patch("nxb.rig.live_rig_sessions", lambda l: []):
            state = Studio(ledger).state()
        self.assertTrue(state["rigs"][0]["resumable"])
        html = (ROOT / "nxb" / "studio.html").read_text()
        self.assertIn("/api/rig/resume", html)
        self.assertIn("r.resumable", html)

    def test_the_refusal_is_published(self):
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        self.assertIn(rig.RIG_NOT_RESUMABLE, vocab["refusal_vocabulary"])


class TheRoleRidesWithTheRule(unittest.TestCase):
    """RIG-22, tightened. One typed message carries rule and role, under the
    'not a task' preamble, and one acknowledgement confirms both."""

    def test_the_typed_rule_carries_the_role_under_the_preamble(self):
        text = enroll.typed_enrolment_rule("W", ledger="/l", repo="/r",
                                           instructions="Audit  everything.")
        self.assertIn("THIS IS NOT A TASK", text)
        self.assertIn("do NOTHING now", text)
        self.assertIn("marked directive carrying an nxb task id", text)
        self.assertIn("Audit everything.", text)
        self.assertTrue(text.rstrip().endswith("ENROLLED W and nothing else."))
        self.assertLess(text.index("You are the worker named"),
                        text.index("Audit everything."),
                        "the rule leads; the role follows it")

    def test_without_a_role_the_typed_rule_is_unchanged_in_shape(self):
        text = enroll.typed_enrolment_rule("W", ledger="/l", repo="/r")
        self.assertNotIn("STANDING ROLE", text)
        self.assertTrue(text.rstrip().endswith("ENROLLED W and nothing else."))

    def test_the_orchestrator_form_carries_it_too(self):
        text = enroll.typed_orchestrator_rule(
            "hub D", ledger="/l", repo="/r", session="hub",
            instructions="Run the programme.")
        self.assertIn("Run the programme.", text)
        self.assertIn("THIS IS NOT A TASK", text)
        self.assertTrue(text.rstrip().endswith("ENROLLED hub D and nothing else."))

    def test_stand_up_no_longer_types_the_role_as_a_second_message(self):
        src = inspect.getsource(rig.stand_up)
        self.assertNotIn("STANDING ROLE FOR THIS SESSION", src)
        self.assertIn("_typed_rule", src)
        self.assertIn("instructions", inspect.getsource(rig._typed_rule))


class TheBriefTeachesTheBudget(unittest.TestCase):
    def _brief(self, peers=None):
        return enroll.orchestrator_rule("hub D", ledger="/l/x.db", repo="/r",
                                        session="hub", peers=peers)

    def test_dispatch_is_one_command_from_a_file(self):
        text = self._brief()
        self.assertIn("rig dispatch --session hub", text)
        self.assertIn("--message-file", text)
        self.assertIn("Never put a long directive on a command line", text)

    def test_collect_waits_and_polling_is_forbidden(self):
        text = self._brief()
        self.assertIn(f"--wait {enroll.COLLECT_WAIT_S}", text)
        self.assertIn("NEVER poll in a loop", text)
        self.assertIn("NEVER sleep between collects", text)
        self.assertIn("rig await --wait", text)
        self.assertIn("43 percent", text)

    def test_context_is_per_task_and_keep_context_is_the_exception(self):
        text = self._brief()
        self.assertIn("CONTEXT IS PER TASK", text)
        self.assertIn("--keep-context", text)
        self.assertIn("ONE OUTSTANDING DIRECTIVE PER WORKER", text)

    def test_the_seam_is_still_documented(self):
        text = self._brief()
        self.assertIn("python3 -m nxb mint", text)
        self.assertIn("rig send", text)

    def test_peers_are_collected_with_a_longer_wait_and_kept_context(self):
        text = self._brief(peers=["spoke"])
        self.assertIn(f"--wait {enroll.PEER_WAIT_S}", text)
        self.assertIn("--keep-context", text.split("PEER RIGS", 1)[1])

    def test_every_command_in_the_brief_is_complete(self):
        commands = [line.strip() for line in self._brief(peers=["s"]).splitlines()
                    if "python3 -m nxb" in line]
        self.assertGreaterEqual(len(commands), 6)
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command.startswith("PYTHONPATH=/r "))
                self.assertFalse(command.rstrip().endswith("."))

    def test_the_directive_tells_the_worker_not_to_echo_its_report(self):
        text = marked_directive("nxbt-1", "W", "x", ledger="/l", repo="/r")
        self.assertIn("never the whole report again", text)
        self.assertTrue(text.endswith(keystroke._PROTOCOL_TAIL),
                        "the collector's boundary must stay the last words")


class NudgeHasTheGuardsAWatcherLacked(unittest.TestCase):
    """RIG-28. Thirteen overnight nudges, four into one pane in half an hour,
    several into panes that were waiting correctly."""

    def _nudge(self, *, screen="idle", tasks=(), pane=None, **kw):
        typed = []
        pane = pane or _pane()
        with mock.patch("nxb.keystroke._resolve",
                        lambda w, l, s: (pane, "s", None)), \
                mock.patch.object(rig, "capture", lambda p: screen), \
                mock.patch("nxb.keystroke.outstanding_tasks",
                           lambda l, w=None: list(tasks)), \
                mock.patch.object(rig, "send_line",
                                  lambda p, t, **k: typed.append(t)), \
                mock.patch("nxb.keystroke.load_rig", lambda l, s: None):
            out = rig.nudge("W", "still there?", ledger="/tmp/x/l.db", **kw)
        return out, typed

    def test_a_pane_mid_turn_is_never_nudged(self):
        out, typed = self._nudge(screen="… esc to interrupt",
                                 tasks=[{"task_id": "t"}])
        self.assertEqual(out["reason"], rig.RIG_PANE_BUSY)
        self.assertEqual(typed, [])

    def test_a_pane_with_no_task_is_not_nudged_unless_forced(self):
        out, typed = self._nudge()
        self.assertEqual(out["reason"], rig.RIG_NOTHING_TO_NUDGE)
        out, typed = self._nudge(force=True)
        self.assertEqual(out["state"], "TYPED")
        self.assertTrue(typed[0].startswith("Operator note (nxb nudge"))
        self.assertFalse(typed[0].startswith(enroll.MARKER))

    def test_a_second_nudge_inside_the_interval_is_refused(self):
        import datetime
        recent = datetime.datetime.now(datetime.timezone.utc).isoformat()
        pane = dict(_pane(), last_nudge_at=recent)
        out, typed = self._nudge(tasks=[{"task_id": "t"}], pane=pane)
        self.assertEqual(out["reason"], rig.RIG_NUDGE_THROTTLED)
        out, typed = self._nudge(tasks=[{"task_id": "t"}], pane=pane,
                                 force=True)
        self.assertEqual(out["state"], "TYPED")

    def test_the_refusals_are_published(self):
        vocab = json.loads((ROOT / "contract" / "rig.json").read_text())
        for term in (rig.RIG_PANE_BUSY, rig.RIG_NUDGE_THROTTLED,
                     rig.RIG_NOTHING_TO_NUDGE):
            self.assertIn(term, vocab["refusal_vocabulary"])


class HealthReadsAndNeverTypes(unittest.TestCase):
    def test_a_downed_rig_reports_its_outstanding_tasks(self):
        ledger = _ledger()
        task_id = _mint(ledger, "r W")
        save_rig(ledger, "r", {"session": "r", "panes": [
            {"name": "r W", "runtime": "codex", "role": "worker",
             "pane": "%1", "enrolment": "typed", "thread_id": "t1"}]})

        def fake(*args, **kw):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")

        def never(*a, **k):
            raise AssertionError("health typed into a pane")
        with mock.patch.object(rig, "_tmux", fake), \
                mock.patch.object(rig, "send_line", never):
            out = rig.health("r", ledger=ledger)
        self.assertFalse(out["standing"])
        self.assertEqual(out["outstanding_total"], 1)
        pane = out["panes"][0]
        self.assertFalse(pane["alive"])
        self.assertTrue(pane["resumable"])
        self.assertEqual(pane["outstanding"][0]["task_id"], task_id)


if __name__ == "__main__":
    unittest.main()
