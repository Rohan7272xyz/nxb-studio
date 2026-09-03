"""nxb-037: H2-8, process-group isolation.

Reproduced with a SYNTHETIC tree on purpose. Worker 1's nxb-017 note records
that their prediction real children would orphan FAILED twice while a synthetic
tree orphaned instantly, so a real-binary test that passes proves nothing about
this class. The synthetic case is the one that can fail.
"""

import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest

from nxb.adapters._process import ProcessAdapter
from nxb.adapters.claude_code import ClaudeCodeAdapter

INIT = '{"type":"system","subtype":"init","session_id":"pg-test-0001"}'


class ProcessGroups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pidfile = os.path.join(self.tmp, "gc.pid")
        self.script = os.path.join(self.tmp, "tree")
        with open(self.script, "w") as h:
            h.write("#!/bin/sh\n"
                    "sh -c 'while :; do sleep 1; done' &\n"
                    f"echo \"$!\" > {self.pidfile}\n"
                    f"echo '{INIT}'\n"
                    "while :; do sleep 1; done\n")
        os.chmod(self.script, os.stat(self.script).st_mode | stat.S_IEXEC)

    def tearDown(self):
        try:
            gc = int(open(self.pidfile).read().strip())
            os.kill(gc, signal.SIGKILL)
        except (OSError, ValueError):
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spawn(self):
        a = ClaudeCodeAdapter(binary=self.script)
        h = a.spawn(work_dir=self.tmp, prompt="p",
                    run_dir=os.path.join(self.tmp, "r"), start_timeout=5)
        self.assertTrue(h["started"])
        return a, h

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def test_a_child_runs_in_its_own_process_group(self):
        _, h = self._spawn()
        try:
            self.assertNotEqual(os.getpgid(h["proc"].pid), os.getpgid(0))
        finally:
            ProcessAdapter._kill(h["proc"])

    def test_killing_a_child_reaps_its_own_children(self):
        """The measured defect: a grandchild outlived a clean kill."""
        a, h = self._spawn()
        gc = int(open(self.pidfile).read().strip())
        self.assertTrue(self._alive(gc))
        a._kill(h["proc"])
        time.sleep(0.4)
        self.assertFalse(self._alive(gc), "the grandchild became a stray")

    def test_the_group_id_is_captured_while_the_child_lives(self):
        """After the leader is reaped os.getpgid raises, so a group resolved at
        kill time is exactly the group you can no longer find."""
        _, h = self._spawn()
        try:
            self.assertEqual(getattr(h["proc"], "_nxb_pgid", None),
                             os.getpgid(h["proc"].pid))
        finally:
            ProcessAdapter._kill(h["proc"])

    def test_the_breaker_also_reaps_the_subtree(self):
        a, h = self._spawn()
        gc = int(open(self.pidfile).read().strip())
        ProcessAdapter._break(h["proc"])
        time.sleep(0.4)
        self.assertFalse(self._alive(gc))


class TheSelfKillGuard(unittest.TestCase):
    """If start_new_session ever failed to take effect, a killpg would reap the
    broker and every sibling. Refusing to signal a group we are inside is the
    difference between reaping a subtree and reaping ourselves."""

    def test_a_child_in_our_own_group_is_never_signalled(self):
        p = subprocess.Popen(["sleep", "5"])          # deliberately NOT isolated
        try:
            self.assertEqual(os.getpgid(p.pid), os.getpgid(0))
            self.assertIsNone(ProcessAdapter._own_group(p))
            self.assertFalse(ProcessAdapter._signal_group(p, signal.SIGKILL))
            self.assertTrue(p.poll() is None, "we signalled our own group")
        finally:
            p.kill()
            p.wait()

    def test_a_dead_child_does_not_raise(self):
        p = subprocess.Popen(["true"], start_new_session=True)
        p.wait()
        self.assertFalse(ProcessAdapter._signal_group(p, signal.SIGKILL))


if __name__ == "__main__":
    unittest.main()
