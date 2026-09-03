"""Hostile spawn conditions, supplied deliberately rather than by accident.

nxb-010's most valuable findings came from a hung process, a harness timeout
and a mistake. Waiting for accidents is not a test strategy, so these are the
conditions the accidents would have produced, made cheap with fake runtimes:
no tokens, no network, deterministic.
"""

import os
import shutil
import stat
import tempfile
import unittest

from nxb.adapters.codex import CodexAdapter
from nxb.dispatch import Broker
from nxb.h2 import SpawnHop
from nxb.ledger import Ledger
from nxb.receipt import digest_units
from nxb.runtimes import register
from tests.test_dispatch import (EXAMPLE_RUNTIME_ID, envelope,
                                 live_declaration)


def fake_runtime(directory, name, script):
    path = os.path.join(directory, name)
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n" + script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class HostileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run = os.path.join(self.tmp, "run")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spawn(self, binary, timeout=3):
        return CodexAdapter(binary=binary).spawn(
            work_dir=self.tmp, prompt="p", run_dir=self.run,
            start_timeout=timeout)


class ChildMisbehaves(HostileCase):
    def test_a_child_that_emits_nothing_is_refused_and_killed(self):
        b = fake_runtime(self.tmp, "silent", "sleep 30\n")
        r = self.spawn(b)
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "no_start_signal_within_timeout")
        self.assertTrue(r["killed"])

    def test_a_child_that_exits_instantly_saying_nothing_is_refused(self):
        b = fake_runtime(self.tmp, "quiet", "exit 0\n")
        r = self.spawn(b)
        self.assertFalse(r["started"])

    def test_a_partial_start_signal_then_silence_is_refused(self):
        """A line that never terminates is never a line."""
        b = fake_runtime(self.tmp, "partial",
                         'printf \'{"type":"thread.\'\nsleep 30\n')
        r = self.spawn(b)
        self.assertFalse(r["started"])
        self.assertTrue(r["killed"])

    def test_a_start_signal_with_no_thread_id_is_MALFORMED_not_a_timeout(self):
        """Reporting this as a timeout sends the operator to the wrong place."""
        b = fake_runtime(self.tmp, "noid",
                         'echo \'{"type":"thread.started"}\'\nsleep 30\n')
        r = self.spawn(b, timeout=5)
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "malformed_start_signal")

    def test_garbage_before_the_start_signal_is_survived(self):
        b = fake_runtime(self.tmp, "noisy",
                         'echo "not json at all"\n'
                         'echo \'{"type":"other"}\'\n'
                         'echo \'{"type":"thread.started","thread_id":"t-1"}\'\n'
                         'sleep 0.2\n')
        r = self.spawn(b)
        self.assertTrue(r["started"])
        self.assertEqual(r["thread_id"], "t-1")
        CodexAdapter._kill(r["proc"])
        r["events"].close()
        r["errs"].close()
        r["proc"].stdout.close()

    def test_a_missing_binary_is_refused_not_raised(self):
        r = self.spawn(os.path.join(self.tmp, "does-not-exist"))
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "runtime_binary_unavailable")

    def test_a_non_executable_binary_is_refused_not_raised(self):
        path = os.path.join(self.tmp, "notexec")
        open(path, "w").write("#!/bin/sh\necho hi\n")
        r = self.spawn(path)
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "runtime_binary_unavailable")


class TheHopNeverRaises(HostileCase):
    def test_an_adapter_that_raises_becomes_a_refusal(self):
        class Exploding:
            runtime_id = "codex"
            model = "m"

            def spawn(self, **kw):
                raise RuntimeError("adapter is broken")

        ledger = Ledger(os.path.join(self.tmp, "l.db"))
        registry = {}
        register(live_declaration(), registry)
        parent = Broker(ledger, registry=registry).dispatch(envelope())["pending_ref"]
        out = SpawnHop(ledger, Exploding()).spawn(
            parent, work_dir=self.tmp, prompt="p", run_dir=self.run,
            start_timeout=1)
        self.assertEqual(out["state"], "REFUSED")
        self.assertTrue(out["reason"].startswith("adapter_raised"))
        ledger.close()


class CanaryFailsWhileWorkIsInFlight(HostileCase):
    def test_a_disproof_does_not_retroactively_kill_an_accepted_dispatch(self):
        """A runtime going DISPROVEN blocks NEW work. It does not rewrite history."""
        from nxb.proof import ProofStore
        ledger = Ledger(os.path.join(self.tmp, "l.db"))
        store = ProofStore(os.path.join(self.tmp, "proofs.json"))
        registry = {}
        register(live_declaration(), registry)
        broker = Broker(ledger, registry=registry, proof_store=store)

        first = broker.dispatch(envelope(dispatch_key="inflight"))
        self.assertEqual(first["state"], "OBSERVED")

        store.put_disproof(EXAMPLE_RUNTIME_ID, at="2026-08-28T16:00:00Z",
                           reason="canary_failed")

        second = broker.dispatch(envelope(dispatch_key="after"))
        self.assertEqual(second["state"], "REFUSED")
        self.assertEqual(second["reason"], f"runtime_disproven: {EXAMPLE_RUNTIME_ID}")

        # The in-flight one is untouched and still resolvable by its key.
        again = broker.dispatch(envelope(dispatch_key="inflight"))
        self.assertEqual(again["state"], "OBSERVED")
        self.assertEqual(again["pending_ref"], first["pending_ref"])
        ledger.close()


if __name__ == "__main__":
    unittest.main()
