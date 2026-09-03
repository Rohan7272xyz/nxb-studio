"""nxb-024: the blocking class, and the canonical form.

These are regression tests for defects that were MEASURED, not reasoned about.
Each names the measurement it holds in place.
"""

import os
import resource
import shutil
import stat
import tempfile
import time
import unittest

from nxb.adapters.codex import CodexAdapter, _BoundedWriter
from nxb.deadline import Deadline
from nxb.receipt import CanonicalisationError, canonical_bytes


def fake(directory, name, script):
    path = os.path.join(directory, name)
    with open(path, "w") as h:
        h.write("#!/bin/sh\n" + script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class TheDeadlineCanInterrupt(unittest.TestCase):
    """The class fix. A deadline that is only CHECKED cannot bound a loop that
    never reaches the check; this one fires from outside."""

    def test_the_breaker_fires_while_the_caller_is_blocked(self):
        fired = []
        with Deadline(0.2, breaker=lambda: fired.append(time.monotonic())):
            time.sleep(0.5)          # an operation the loop cannot interrupt
        self.assertTrue(fired, "the breaker never fired; the deadline is advisory")

    def test_cancelling_stops_the_breaker(self):
        fired = []
        with Deadline(0.2, breaker=lambda: fired.append(1)):
            pass                     # exits immediately, timer cancelled
        time.sleep(0.4)
        self.assertEqual(fired, [], "a completed operation was still broken")

    def test_a_breaker_that_raises_does_not_escape(self):
        def bad():
            raise RuntimeError("breaker is broken")
        with Deadline(0.1, breaker=bad):
            time.sleep(0.3)
        # Reaching here at all is the assertion.

    def test_slice_never_overshoots(self):
        d = Deadline(0.1)
        time.sleep(0.15)
        self.assertEqual(d.slice(5.0), 0.0)


class NoSpinAndNoOvershoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_child_that_closes_stdout_and_lives_does_not_burn_a_core(self):
        """H2-2. Measured 61% of a core before this fix, 0% after.

        At EOF the selector reports the fd readable forever, so the loop span
        without ever blocking and without ever making progress.
        """
        b = fake(self.tmp, "eof", "exec >&-\nsleep 4\n")
        c0 = resource.getrusage(resource.RUSAGE_SELF)
        t0 = time.monotonic()
        r = CodexAdapter(binary=b).spawn(
            work_dir=self.tmp, prompt="p",
            run_dir=os.path.join(self.tmp, "r"), start_timeout=2)
        wall = time.monotonic() - t0
        c1 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (c1.ru_utime - c0.ru_utime) + (c1.ru_stime - c0.ru_stime)
        self.assertFalse(r["started"])
        self.assertLess(cpu / wall, 0.25,
                        f"burned {100 * cpu / wall:.0f}% of a core waiting")

    def test_the_budget_is_held_against_a_child_that_ignores_signals(self):
        """The deadline used to overshoot to 6.2s on a 4s budget, because the
        kill path waited three seconds twice after the loop had already ended."""
        b = fake(self.tmp, "stubborn", "trap '' INT\nexec >&-\nsleep 6\n")
        t0 = time.monotonic()
        CodexAdapter(binary=b).spawn(
            work_dir=self.tmp, prompt="p",
            run_dir=os.path.join(self.tmp, "r2"), start_timeout=2)
        self.assertLess(time.monotonic() - t0, 5.0)


class TheWritePathIsBounded(unittest.TestCase):
    """H2-1. The child decides how much it emits; the broker decides how much
    it records."""

    def test_a_bounded_writer_stops_at_its_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "e.jsonl")
            w = _BoundedWriter(open(path, "w"), cap=1000)
            for _ in range(500):
                w.write("x" * 100 + "\n")
            w.flush()
            w.close()
            self.assertTrue(w.truncated)
            self.assertLess(os.path.getsize(path), 1400)

    def test_truncation_is_announced_in_the_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "e.jsonl")
            w = _BoundedWriter(open(path, "w"), cap=50)
            w.write("y" * 200)
            w.close()
            self.assertIn("nxb.truncated", open(path).read())


class TheCanonicalFormIsPortable(unittest.TestCase):
    """N-1 and N-2. A digest over bytes only Python can parse is a digest no
    other runtime can reproduce, in a project built to dispatch across
    runtimes."""

    def test_non_finite_numbers_are_refused_not_encoded(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=bad):
                with self.assertRaises(CanonicalisationError):
                    canonical_bytes([{"n": bad}])

    def test_nesting_does_not_hide_a_non_finite_number(self):
        with self.assertRaises(CanonicalisationError):
            canonical_bytes([{"a": {"b": [1, 2, {"c": float("nan")}]}}])

    def test_untransmittable_text_is_refused(self):
        with self.assertRaises(CanonicalisationError):
            canonical_bytes([{"s": "\ud800"}])

    def test_a_key_can_be_untransmittable_too(self):
        with self.assertRaises(CanonicalisationError):
            canonical_bytes([{"\ud800": "v"}])

    def test_the_form_is_pure_ascii(self):
        out = canonical_bytes([{"s": "héllo wörld", "n": 2}])
        out.decode("ascii")          # raises if it is not
        self.assertNotIn(b"\xc3", out)

    def test_keys_are_sorted_so_two_writers_agree(self):
        a = canonical_bytes([{"b": 1, "a": 2}])
        b = canonical_bytes([{"a": 2, "b": 1}])
        self.assertEqual(a, b)

    def test_an_uncanonicalisable_payload_is_REFUSED_not_receipted(self):
        from nxb.dispatch import Broker
        from nxb.ledger import Ledger
        from nxb.runtimes import register
        from tests.test_dispatch import envelope, live_declaration
        with tempfile.TemporaryDirectory() as tmp:
            reg = {}
            register(live_declaration(), reg)
            led = Ledger(os.path.join(tmp, "l.db"))
            try:
                # Built by hand: the test helper digests units to fill
                # declared_digest, and that digest is exactly what now refuses.
                env = envelope()
                env["units"] = [{"n": float("inf")}]
                out = Broker(led, registry=reg).dispatch(env)
                self.assertEqual(out["state"], "REFUSED")
                self.assertTrue(out["reason"].startswith("uncanonicalisable_payload"))
                self.assertEqual(out["dispatch_status"], "DID_NOT_HAPPEN")
            finally:
                led.close()


if __name__ == "__main__":
    unittest.main()
