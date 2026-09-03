"""The runtime's own failure announcement, and the abort that consumes it.

The point of these tests is that the detector must fire on the MEASURED frames
and stay silent on the measured healthy ones. So they read the real evidence
files rather than restating what the frames look like: a test that asserts
against a hand-typed copy of a frame stops being about the runtime the moment
the runtime changes.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxb.adapters.codex import CodexAdapter, _BoundedWriter
from nxb.failsignal import detect
from nxb.h3 import collect_report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(ROOT, "evidence")


def _frames(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


class DetectorMatchesMeasuredFrames(unittest.TestCase):
    def test_codex_outage_frames_all_fire(self):
        path = os.path.join(EV, "nxb-022", "stdout-broken.jsonl")
        errs = [e for e in _frames(path) if e.get("type") == "error"]
        self.assertTrue(errs, "evidence file has no error frames")
        for e in errs:
            self.assertEqual(detect(e, runtime_id="codex")["reason"],
                             "runtime_announced_error")

    def test_codex_non_fatal_warning_does_not_fire(self):
        """The distinction that makes this structural rather than prose.

        A recoverable warning arrives as item.completed carrying an item of
        type error. Only the TOP-LEVEL error type is fatal.
        """
        path = os.path.join(EV, "nxb-002-codex", "spawn-failed-badmodel.jsonl")
        warnings = [e for e in _frames(path)
                    if e.get("type") == "item.completed"
                    and (e.get("item") or {}).get("type") == "error"]
        self.assertTrue(warnings, "evidence file has no item-level error")
        for e in warnings:
            self.assertIsNone(detect(e, runtime_id="codex"))

    def test_claude_code_retry_fires_and_healthy_does_not(self):
        broken = os.path.join(EV, "nxb-022", "cc-broken.jsonl")
        healthy = os.path.join(EV, "nxb-022", "cc-healthy.jsonl")
        fired = [detect(e, runtime_id="claude_code") for e in _frames(broken)]
        self.assertTrue(any(f for f in fired))
        for e in _frames(healthy):
            self.assertIsNone(detect(e, runtime_id="claude_code"),
                              f"false positive on healthy frame: {e.get('subtype')}")

    def test_unknown_runtime_is_silent_not_an_error(self):
        self.assertIsNone(detect({"type": "error"}, runtime_id="nobody"))

    def test_non_dict_is_silent(self):
        self.assertIsNone(detect("error", runtime_id="codex"))


class _FakeChild:
    """A real child process emitting chosen frames, then sleeping.

    A mock would not exercise the loop that has now carried this project's
    blocking bug four times.
    """

    def __init__(self, tmp, frames, sleep_after=30):
        body = "".join("print(%r, flush=True)\n" % json.dumps(f) for f in frames)
        script = body + "import time; time.sleep(%d)\n" % sleep_after
        self.proc = subprocess.Popen([sys.executable, "-c", script],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1)
        self.events_path = os.path.join(tmp, "events.jsonl")
        self.out_path = os.path.join(tmp, "out.txt")
        self.handle = {
            "proc": self.proc,
            "events": _BoundedWriter(open(self.events_path, "w", encoding="utf-8")),
            "errs": open(os.path.join(tmp, "err.txt"), "w", encoding="utf-8"),
            "out_path": self.out_path,
        }


class TheAbortConsumesTheAnnouncement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.adapter = CodexAdapter()

    def test_abort_returns_long_before_the_budget(self):
        child = _FakeChild(self.tmp, [{"type": "thread.started", "thread_id": "t"},
                                      {"type": "error", "message": "boom"}])
        t0 = time.monotonic()
        out = self.adapter.drain(child.handle, budget=20,
                                 abort_on_announced_failure=True)
        elapsed = time.monotonic() - t0
        self.assertTrue(out["aborted_on_announcement"])
        self.assertEqual(out["announced_failure"]["reason"], "runtime_announced_error")
        self.assertLess(elapsed, 5, "abort did not beat the budget")

    def test_an_abort_is_not_reported_as_a_timeout(self):
        child = _FakeChild(self.tmp, [{"type": "error", "message": "boom"}])
        out = self.adapter.drain(child.handle, budget=20,
                                 abort_on_announced_failure=True)
        self.assertFalse(out["drain_timed_out"])

    def test_without_the_flag_it_observes_but_does_not_abort(self):
        """Ordinary dispatch must not have the broker overrule a live child."""
        child = _FakeChild(self.tmp, [{"type": "error", "message": "boom"}],
                           sleep_after=1)
        out = self.adapter.drain(child.handle, budget=6,
                                 abort_on_announced_failure=False)
        self.assertFalse(out["aborted_on_announcement"])
        self.assertIsNotNone(out["announced_failure"])
        self.assertTrue(out["error"])


class TheReasonNamesWhatTheRuntimeSaid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out.txt")

    def _collect(self, terminal, raw=None):
        if raw is not None:
            with open(self.out, "w", encoding="utf-8") as fh:
                fh.write(raw)
        return collect_report(parent_receipt_id="rcpt-p", runtime_ref="t",
                              out_path=self.out, terminal=terminal,
                              declaration={"runtime_id": "codex"})[1]

    def test_announcement_beats_no_output_file(self):
        parts = self._collect({"announced_failure":
                               {"reason": "runtime_announced_error"}})
        self.assertEqual(parts["reason"], "runtime_announced_error")
        self.assertEqual(parts["delivery"], "RUNTIME_FAILED")

    def test_without_an_announcement_the_old_reason_survives(self):
        parts = self._collect({})
        self.assertEqual(parts["reason"], "no_output_file")

    def test_an_announcement_never_discards_a_delivered_report(self):
        """If the report arrived, the runtime recovered. Keep the answer."""
        report = json.dumps({"dispatch_key": "k", "status": "COMPLETE",
                             "summary": "ok"})
        parts = self._collect({"announced_failure":
                               {"reason": "runtime_announced_error"}}, raw=report)
        self.assertNotEqual(parts["delivery"], "RUNTIME_FAILED")


if __name__ == "__main__":
    unittest.main()
