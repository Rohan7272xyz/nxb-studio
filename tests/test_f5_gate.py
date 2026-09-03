"""F-5, whole, after the freshness budget was deleted.

The gate is now two rows. Most of this file's predecessor tested states that no
longer exist: PROVEN_FRESH, PROVEN_STALE, PROOF_INVALID, skew tolerance,
future-dated proofs. Those tests were deleted with the machinery they covered,
which is the point of the task and not a loss of coverage.
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest

from tests.test_dispatch import EXAMPLE_RUNTIME_ID
from nxb.proof import (DISPROVEN, GATE, NEVER_PROVEN, PROVEN, ProofStore,
                       codex_evidence_verifier, gate_state, make_proof)


class ProofCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = ProofStore(os.path.join(self.tmp, "proofs.json"))
        self.evidence = os.path.join(
            self.tmp, "rollout-2026-08-28T12-00-00-thread-abcdef12.jsonl")
        with open(self.evidence, "w") as h:
            h.write('{"thread_id":"thread-abcdef12"}\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def verifier(self, proof):
        """The production verifier, told that this tmpdir is the runtime root.

        nxb-036 requires a proof to resolve INSIDE the named runtime's evidence
        root, because an unrooted path was half of how a one-character ref
        verified /etc/passwd. A test that fabricates evidence has to declare
        where it is fabricating it, which is the point.
        """
        return codex_evidence_verifier(proof, roots={"codex": self.tmp})

    def proof(self, **over):
        p = make_proof(runtime_id="codex", proven_at="2026-08-28T16:00:00Z",
                       method="canary", runtime_ref="thread-abcdef12",
                       evidence_path=self.evidence)
        p.update(over)
        return p

    def gate(self):
        return gate_state(self.store, "codex")


class TheGateIsTwoRows(ProofCase):
    def test_unproven_allows(self):
        self.assertEqual(self.gate(), (NEVER_PROVEN, "ALLOW"))

    def test_proven_allows(self):
        self.store.put(self.proof())
        self.assertEqual(self.gate(), (PROVEN, "ALLOW"))

    def test_disproven_is_the_only_refusal(self):
        self.store.put_disproof("codex", at="2026-08-28T16:00:00Z", reason="x")
        self.assertEqual(self.gate(), (DISPROVEN, "REFUSE"))

    def test_exactly_one_state_refuses(self):
        self.assertEqual([s for s, a in GATE.items() if a == "REFUSE"],
                         [DISPROVEN])

    def test_a_proof_does_not_age(self):
        """The budget is gone: an ancient proof is worth exactly as much as a
        new one, because neither grants anything the gate consults."""
        self.store.put(self.proof(proven_at="1999-01-01T00:00:00Z"))
        self.assertEqual(self.gate(), (PROVEN, "ALLOW"))


class ForgingStillBuysNothing(ProofCase):
    def test_a_forged_proof_reaches_the_same_action_as_no_proof(self):
        before = self.gate()[1]
        self.store.put(self.proof(evidence_path="/nonexistent/x.jsonl"))
        self.assertEqual(self.gate()[1], before)

    def test_a_forged_proof_cannot_lift_a_disproof(self):
        self.store.put_disproof("codex", at="2026-08-28T16:00:00Z", reason="x")
        self.store.put(self.proof(evidence_path="/nonexistent/x.jsonl"))
        self.assertEqual(self.gate(), (DISPROVEN, "REFUSE"))

    def test_clearing_with_an_unverifiable_proof_is_refused(self):
        self.store.put_disproof("codex", at="2026-08-28T16:00:00Z", reason="x")
        ok = self.store.clear_disproof(
            "codex", proof=self.proof(evidence_path="/nonexistent/x.jsonl"),
            verifier=self.verifier)
        self.assertFalse(ok)
        self.assertEqual(self.gate()[0], DISPROVEN)

    def test_clearing_with_a_verifiable_proof_works(self):
        self.store.put_disproof("codex", at="2026-08-28T16:00:00Z", reason="x")
        ok = self.store.clear_disproof("codex", proof=self.proof(),
                                       verifier=self.verifier)
        self.assertTrue(ok)
        self.assertEqual(self.gate()[0], NEVER_PROVEN)


class EvidenceVerifierIsHostileInputSafe(ProofCase):
    """The property audit: can a peer block this loop past its deadline.

    `evidence_path` is attacker-supplied. These tests make deliberate a
    protection that was previously accidental.
    """

    def test_a_fifo_is_refused_without_blocking(self):
        fifo = os.path.join(self.tmp, "rollout-thread-abc.jsonl")
        os.mkfifo(fifo)
        # If open() were reached this would hang forever, so the test itself is
        # the assertion: it has to terminate.
        code = ("import sys; sys.path.insert(0,%r);"
                "from nxb.proof import codex_evidence_verifier as v;"
                "print(v({'evidence_path':%r,'runtime_ref':'thread-abc'}))"
                % (os.getcwd(), fifo))
        out = subprocess.run([os.sys.executable, "-c", code], timeout=10,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False")

    def test_a_directory_is_refused(self):
        d = os.path.join(self.tmp, "rollout-thread-abc.jsonl")
        os.mkdir(d)
        self.assertFalse(codex_evidence_verifier(
            {"evidence_path": d, "runtime_ref": "thread-abc"}))

    def test_reading_is_bounded_in_bytes_not_only_in_lines(self):
        """A single 8MB line with no newline must not be read whole."""
        from nxb.proof import _MAX_EVIDENCE_BYTES
        big = os.path.join(self.tmp, "rollout-thread-zzz.jsonl")
        with open(big, "w") as h:
            h.write("x" * (8 * 1024 * 1024))
        self.assertFalse(codex_evidence_verifier(
            {"evidence_path": big, "runtime_ref": "thread-zzz"}))
        self.assertLess(_MAX_EVIDENCE_BYTES, 8 * 1024 * 1024)

    def test_a_proof_pointing_at_someone_elses_thread_is_refused(self):
        self.assertFalse(codex_evidence_verifier(
            {"evidence_path": self.evidence, "runtime_ref": "thread-OTHER"}))

    def test_a_nonexistent_path_is_refused(self):
        self.assertFalse(codex_evidence_verifier(
            {"evidence_path": "/nope/nope.jsonl", "runtime_ref": "t"}))


class StoreIsHostileInputSafe(ProofCase):
    def test_a_fifo_store_does_not_block_the_loader(self):
        fifo_path = os.path.join(self.tmp, "fifo-store.json")
        os.mkfifo(fifo_path)
        store = ProofStore(fifo_path)
        code = ("import sys; sys.path.insert(0,%r);"
                "from nxb.proof import ProofStore;"
                "print(ProofStore(%r).get('codex'))" % (os.getcwd(), fifo_path))
        out = subprocess.run([os.sys.executable, "-c", code], timeout=10,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "None")

    def test_a_corrupt_store_is_empty_not_fatal(self):
        with open(self.store.path, "w") as h:
            h.write("{not json")
        self.assertEqual(self.gate()[0], NEVER_PROVEN)


class OnDemandProver(unittest.TestCase):
    """The surviving form of 'reprove': opt-in, attached to DISPROVEN."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _broker(self, prover=None):
        from nxb.dispatch import Broker
        from nxb.ledger import Ledger
        from nxb.runtimes import register
        from tests.test_dispatch import live_declaration, EXAMPLE_RUNTIME_ID
        store = ProofStore(os.path.join(self.tmp, "p.json"))
        store.put_disproof(EXAMPLE_RUNTIME_ID, at="2026-08-28T16:00:00Z",
                           reason="canary_failed")
        registry = {}
        register(live_declaration(), registry)
        led = Ledger(os.path.join(self.tmp, "l.db"))
        return Broker(led, registry=registry, proof_store=store,
                      prover=prover), store

    def test_disproven_refuses_when_no_prover_is_supplied(self):
        from tests.test_dispatch import envelope
        broker, _ = self._broker()
        self.assertEqual(broker.dispatch(envelope())["state"], "REFUSED")

    def test_a_prover_that_succeeds_lets_the_dispatch_through(self):
        from tests.test_dispatch import envelope
        calls = []

        def prover(runtime_id):
            calls.append(runtime_id)
            return True

        broker, _ = self._broker(prover=prover)
        self.assertEqual(broker.dispatch(envelope())["state"], "OBSERVED")
        self.assertEqual(calls, [EXAMPLE_RUNTIME_ID])

    def test_a_prover_that_fails_still_refuses(self):
        from tests.test_dispatch import envelope
        broker, _ = self._broker(prover=lambda r: False)
        out = broker.dispatch(envelope())
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], f"runtime_disproven: {EXAMPLE_RUNTIME_ID}")

    def test_the_prover_is_not_consulted_when_nothing_is_disproven(self):
        from nxb.dispatch import Broker
        from nxb.ledger import Ledger
        from nxb.runtimes import register
        from tests.test_dispatch import live_declaration, envelope
        calls = []
        store = ProofStore(os.path.join(self.tmp, "q.json"))
        registry = {}
        register(live_declaration(), registry)
        broker = Broker(Ledger(os.path.join(self.tmp, "m.db")),
                        registry=registry, proof_store=store,
                        prover=lambda r: calls.append(r) or True)
        self.assertEqual(broker.dispatch(envelope())["state"], "OBSERVED")
        self.assertEqual(calls, [], "an idle system must cost nothing")


if __name__ == "__main__":
    unittest.main()
