"""Which refusals survive contact."""

import os
import tempfile
import unittest

from nxb.contract import CONTRACT
from nxb.dispatch import Broker, _ReceiptToken
from nxb.ledger import Ledger
from nxb.receipt import digest_units
from nxb.runtimes import register, RegistrationRefused


def live_declaration():
    decl = dict(CONTRACT["examples"]["capability_declaration"])
    decl["start_signal"] = "peer_message_status correlated by msg_id"
    # `last_proven_at` was set here until nxb-044. C-6 removed the field from the
    # schema in nxb-042 and this line kept writing it, so the fixture carried a
    # field the contract no longer defines: the same dropped-value class the
    # removal was closing, one directory away. Liveness comes from the proof
    # store, and a Broker built without one has no gate to satisfy.
    return decl


#: Derived from the contract, never hardcoded. nxb-016 renamed the example
#: runtime to neutralise an identity residue and every test that had spelled
#: the old name out broke. A fixture that restates a contract value is a second
#: copy of the contract.
EXAMPLE_RUNTIME_ID = CONTRACT["examples"]["capability_declaration"]["runtime_id"]


def envelope(**over):
    units = over.pop("units", [{"summary": "one unit"}])
    env = {
        "dispatch_key": "k-001",
        "runtime_id": EXAMPLE_RUNTIME_ID,
        "declared_count": len(units),
        "declared_digest": digest_units(units),
        "units": units,
        "dispatcher_id": "Orchestrator 1",
    }
    env.update(over)
    return env


class BrokerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = Ledger(os.path.join(self.tmp, "ledger.db"))
        self.registry = {}
        register(live_declaration(), self.registry)
        self.broker = Broker(self.ledger, registry=self.registry)

    def tearDown(self):
        self.ledger.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class HappyPath(BrokerCase):
    def test_returns_observed_with_receipt_and_pending_ref(self):
        out = self.broker.dispatch(envelope())
        self.assertEqual(out["state"], "OBSERVED")
        self.assertIn("receipt", out)
        self.assertIn("pending_ref", out)
        self.assertEqual(out["receipt"]["hop"], "H1")

    def test_the_return_value_is_the_receipt_not_a_transmission_ack(self):
        """R-050 as amended by the nxb-006 measurement."""
        out = self.broker.dispatch(envelope())
        self.assertNotIn("success", out)
        self.assertNotIn("ok", out)
        self.assertEqual(out["receipt"]["sender_ref"], "k-001")


class F6ReceiptBeforeInterpretation(BrokerCase):
    def test_receipt_is_durable_before_any_disposition_exists(self):
        out = self.broker.dispatch(envelope())
        rid = out["pending_ref"]
        row = self.ledger.find_by_dispatch_key("k-001")
        self.assertEqual(row["receipt_id"], rid)

    def test_interpretation_without_a_token_is_refused(self):
        with self.assertRaises(AssertionError):
            self.broker._interpret(object(), envelope())

    def test_forged_token_is_refused_because_ledger_is_rechecked(self):
        forged = _ReceiptToken("rcpt-does-not-exist")
        with self.assertRaises(AssertionError):
            self.broker._interpret(forged, envelope())

    def test_a_payload_that_cannot_be_validated_still_gets_a_receipt(self):
        """The flagship. A rejected dispatch is OBSERVED, not vanished."""
        units = [{"summary": "a"}]
        env = envelope(units=units, declared_count=99)
        out = self.broker.dispatch(env)
        self.assertEqual(out["state"], "REFUSED")
        self.assertIn("receipt", out)
        self.assertEqual(out["reason"], "count_divergence")


class F8AndF9Divergence(BrokerCase):
    def test_count_divergence_refuses_even_when_nothing_else_is_wrong(self):
        out = self.broker.dispatch(envelope(declared_count=2))
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], "count_divergence")

    def test_zero_observed_units_still_diverges(self):
        env = envelope(units=[])
        env["declared_count"] = 1
        out = self.broker.dispatch(env)
        self.assertEqual(out["reason"], "count_divergence")

    def test_digest_divergence_refuses_and_does_not_proceed(self):
        env = envelope()
        env["declared_digest"] = "0" * 64
        out = self.broker.dispatch(env)
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], "digest_divergence")


class F5CorrectedInNxb011(BrokerCase):
    """F-5 no longer refuses an UNPROVEN runtime. It refuses a DISPROVEN one.

    The old assertion here was `test_unproven_runtime_is_refused`, and it
    passed. It encoded the behaviour that refused 100% of dispatches and drove
    an operator to forge a proof [M: nxb-006]. Deleting it is the fix.
    """

    def test_an_unproven_runtime_is_now_ALLOWED_speculatively(self):
        out = self.broker.dispatch(envelope())
        self.assertEqual(out["state"], "OBSERVED")

    def test_unregistered_runtime_is_refused(self):
        out = self.broker.dispatch(envelope(runtime_id="codex"))
        self.assertEqual(out["state"], "REFUSED")
        self.assertTrue(out["reason"].startswith("runtime_unregistered"))

    def test_refused_is_a_positive_assertion_not_unknown(self):
        out = self.broker.dispatch(envelope(runtime_id="codex"))
        self.assertEqual(out["dispatch_status"], "DID_NOT_HAPPEN")


class R051Idempotency(BrokerCase):
    def test_repeated_key_returns_the_original_receipt(self):
        first = self.broker.dispatch(envelope())
        second = self.broker.dispatch(envelope())
        self.assertEqual(first["pending_ref"], second["pending_ref"])
        self.assertEqual(first["receipt"]["receipt_id"],
                         second["receipt"]["receipt_id"])

    def test_repeated_key_does_not_create_a_second_receipt(self):
        self.broker.dispatch(envelope())
        self.broker.dispatch(envelope())
        rows = self.ledger._conn.execute("SELECT COUNT(*) c FROM receipts").fetchone()
        self.assertEqual(rows["c"], 1)

    def test_a_changed_payload_under_a_repeated_key_is_REFUSED(self):
        """F1, found by a cold user fixing a typo and re-running.

        This test previously asserted the defect: the repeat returned OBSERVED,
        exit 0, the ORIGINAL receipt and the digest of the OLD payload, so an
        operator believed a correction had shipped when it had not.
        """
        self.broker.dispatch(envelope())
        out = self.broker.dispatch(envelope(units=[{"summary": "DIFFERENT"}]))
        self.assertEqual(out["state"], "REFUSED")
        self.assertTrue(out["reason"].startswith("dispatch_key_reuse_divergence"))
        self.assertEqual(out["dispatch_status"], "DID_NOT_HAPPEN")

    def test_an_identical_repeat_replays_the_original_REFUSAL(self):
        """F2. Pressing up-arrow must not launder a refusal into a success."""
        bad = envelope(declared_digest="0" * 64)
        first = self.broker.dispatch(bad)
        second = self.broker.dispatch(bad)
        self.assertEqual(first["state"], "REFUSED")
        self.assertEqual(second["state"], "REFUSED",
                         "a retry converted a refusal into a success")
        self.assertEqual(second["dispatch_status"], "DID_NOT_HAPPEN")

    def test_an_identical_repeat_after_success_still_replays_the_receipt(self):
        """R-051's original purpose survives: retry after UNKNOWN is safe."""
        first = self.broker.dispatch(envelope())
        second = self.broker.dispatch(envelope())
        self.assertEqual(second["state"], "OBSERVED")
        self.assertEqual(first["pending_ref"], second["pending_ref"])


class F11ExactlyOneDisposition(BrokerCase):
    def test_every_receipt_gets_a_disposition(self):
        out = self.broker.dispatch(envelope())
        self.assertIsNotNone(self.ledger.disposition_for(out["pending_ref"]))

    def test_a_refused_dispatch_also_gets_a_disposition(self):
        out = self.broker.dispatch(envelope(declared_count=7))
        self.assertIsNotNone(self.ledger.disposition_for(out["pending_ref"]))

    def test_a_second_disposition_is_refused_by_the_schema(self):
        import sqlite3
        out = self.broker.dispatch(envelope())
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.record_disposition(out["pending_ref"], "ACCEPTED",
                                           None, now="2026-08-28T00:00:00Z")


class MalformedEnvelope(BrokerCase):
    def test_missing_field_is_refused_not_defaulted(self):
        env = envelope()
        del env["dispatcher_id"]
        out = self.broker.dispatch(env)
        self.assertEqual(out["state"], "REFUSED")
        self.assertTrue(out["reason"].startswith("malformed_envelope"))

    def test_dispatch_never_raises(self):
        for bad in [None, {}, {"dispatch_key": "x"}, []]:
            with self.subTest(payload=bad):
                out = self.broker.dispatch(bad)
                self.assertIn(out["state"], ("REFUSED", "UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
