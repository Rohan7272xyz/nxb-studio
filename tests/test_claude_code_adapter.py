"""nxb-027: the Claude Code spawn adapter, under hostile conditions.

HANDOFF records that across nxb-006 and nxb-010 every refusal that survived
contact survived a test written by the same agent that wrote the code, and the
author's own tests had never once caught the author's own defect. So the happy
path is one test here and the hostile conditions are the rest.
"""

import json
import os
import resource
import shutil
import stat
import tempfile
import time
import unittest

from nxb.adapters.claude_code import ClaudeCodeAdapter
from nxb.adapters._process import _LineReader


def fake(directory, name, script):
    path = os.path.join(directory, name)
    with open(path, "w") as h:
        h.write("#!/bin/sh\n" + script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


INIT = '{"type":"system","subtype":"init","session_id":"s-1"}'
OK = ('{"type":"result","subtype":"success","is_error":false,'
      '"result":"{\\"task_id\\":\\"t\\"}"}')


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_adapter(self, script, *, start_timeout=3, budget=3, name="r"):
        b = fake(self.tmp, name, script)
        a = ClaudeCodeAdapter(binary=b)
        h = a.spawn(work_dir=self.tmp, prompt="p",
                    run_dir=os.path.join(self.tmp, name + "-run"),
                    start_timeout=start_timeout)
        if not h["started"]:
            return h, None, a
        return h, a.drain(h, budget=budget), a


class TheStartSignal(Case):
    def test_system_init_is_the_start_signal_and_carries_the_session_id(self):
        h, _, _ = self.run_adapter(f"echo '{INIT}'\necho '{OK}'\n")
        self.assertTrue(h["started"])
        self.assertEqual(h["thread_id"], "s-1")

    def test_a_child_that_never_emits_init_is_refused_and_killed(self):
        h, _, _ = self.run_adapter('echo \'{"type":"assistant"}\'\nsleep 5\n')
        self.assertFalse(h["started"])
        self.assertEqual(h["reason"], "no_start_signal_within_timeout")
        self.assertTrue(h["killed"])

    def test_an_init_frame_with_no_session_id_is_MALFORMED_not_a_timeout(self):
        h, _, _ = self.run_adapter(
            'echo \'{"type":"system","subtype":"init"}\'\nsleep 5\n')
        self.assertFalse(h["started"])
        self.assertEqual(h["reason"], "malformed_start_signal")

    def test_a_missing_binary_is_refused_not_raised(self):
        a = ClaudeCodeAdapter(binary=os.path.join(self.tmp, "nope"))
        h = a.spawn(work_dir=self.tmp, prompt="p",
                    run_dir=os.path.join(self.tmp, "r"), start_timeout=2)
        self.assertFalse(h["started"])
        self.assertEqual(h["reason"], "runtime_binary_unavailable")


class TheBlockingClass(Case):
    def test_a_partial_line_then_silence_does_not_defeat_the_budget(self):
        t0 = time.monotonic()
        h, _, _ = self.run_adapter(
            'printf \'{"type":"system","subtype":\'\nsleep 6\n', start_timeout=2)
        self.assertFalse(h["started"])
        self.assertLess(time.monotonic() - t0, 5.0)

    def test_a_child_that_closes_stdout_and_lives_does_not_burn_a_core(self):
        c0 = resource.getrusage(resource.RUSAGE_SELF)
        t0 = time.monotonic()
        self.run_adapter("exec >&-\nsleep 4\n", start_timeout=2)
        wall = time.monotonic() - t0
        c1 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (c1.ru_utime - c0.ru_utime) + (c1.ru_stime - c0.ru_stime)
        self.assertLess(cpu / wall, 0.25,
                        f"burned {100 * cpu / wall:.0f}% of a core")

    def test_the_deadline_fires_against_a_child_that_ignores_signals(self):
        t0 = time.monotonic()
        self.run_adapter("trap '' INT\nexec >&-\nsleep 8\n", start_timeout=2)
        self.assertLess(time.monotonic() - t0, 6.0)


class FramesAreNotLostAtTheHandover(Case):
    """The defect the 'who writes the state this depends on' read found.

    `spawn` breaks out of the read loop on the start signal. Before nxb-027 it
    then discarded its reader and `drain` built a new one, so any frame already
    split off, or any byte already buffered, was lost. A child emitting its
    init and its result in ONE write lost the result entirely and the turn read
    as never having completed. This was latent in the Codex path since nxb-010.
    """

    def test_a_result_in_the_same_write_as_init_is_not_lost(self):
        script = "printf '%s\\n%s\\n' '{}' '{}'\nsleep 0.2\n".format(INIT, OK)
        h, term, _ = self.run_adapter(script)
        self.assertTrue(h["started"])
        self.assertTrue(term["turn_completed"], "the result frame was lost")
        self.assertTrue(term["out_present"])

    def test_the_reader_survives_a_consumer_that_breaks(self):
        import io
        r, w = os.pipe()
        os.write(w, b"a\nb\nc\n")
        os.close(w)
        reader = _LineReader(io.FileIO(r, "r"))
        for line in reader.drain_ready():
            break                       # abandon after the first
        self.assertTrue(reader.has_pending)
        self.assertEqual([l.strip() for l in reader.drain_ready()], ["b", "c"])


class OutPathPreservesF14(Case):
    """Claude Code has no `-o`, so the adapter writes out_path itself.

    The deliberate choice: it is written ONLY for a successful result. "Absence
    is a reliable failure signal" is F-14's load-bearing half, and writing an
    error payload into the success channel would destroy it.
    """

    def test_a_successful_result_writes_the_file(self):
        h, term, _ = self.run_adapter(f"echo '{INIT}'\necho '{OK}'\n")
        self.assertTrue(term["out_present"])
        self.assertEqual(json.load(open(h["out_path"]))["task_id"], "t")

    def test_an_errored_result_does_NOT_write_the_file(self):
        bad = ('{"type":"result","subtype":"error_during_execution",'
               '"is_error":true,"result":"boom"}')
        h, term, _ = self.run_adapter(f"echo '{INIT}'\necho '{bad}'\n", name="e")
        self.assertFalse(term["out_present"], "absence must still mean failure")
        self.assertTrue(term["turn_failed"])

    def test_is_error_true_with_success_subtype_still_does_not_write(self):
        odd = ('{"type":"result","subtype":"success","is_error":true,'
               '"result":"x"}')
        h, term, _ = self.run_adapter(f"echo '{INIT}'\necho '{odd}'\n", name="o")
        self.assertFalse(term["out_present"])

    def test_no_result_frame_at_all_leaves_the_file_absent(self):
        h, term, _ = self.run_adapter(f"echo '{INIT}'\nsleep 0.2\n", name="n")
        self.assertFalse(term["out_present"])


class TheSchemaIsInlineNotAPath(Case):
    """Measured nxb-027. Codex's --output-schema takes a PATH; Claude Code's
    --json-schema takes the schema itself. An adapter written by analogy passes
    a path and the child exits 1 parsing the filename as JSON."""

    def test_the_schema_is_inlined_into_the_command(self):
        sp = os.path.join(self.tmp, "s.json")
        with open(sp, "w") as h:
            json.dump({"type": "object", "properties": {"a": {"type": "string"}}}, h)
        cmd = ClaudeCodeAdapter().build_command(
            work_dir=self.tmp, prompt="p", out_path="/tmp/o", schema_path=sp)
        i = cmd.index("--json-schema")
        self.assertNotEqual(cmd[i + 1], sp, "passed the path, which the CLI rejects")
        self.assertEqual(json.loads(cmd[i + 1])["type"], "object")

    def test_the_model_is_pinned_on_every_command(self):
        cmd = ClaudeCodeAdapter().build_command(
            work_dir=self.tmp, prompt="p", out_path="/tmp/o")
        self.assertIn("--model", cmd)


if __name__ == "__main__":
    unittest.main()
