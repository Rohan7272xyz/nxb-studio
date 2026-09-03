"""H3 and H4: the loop closing.

The measured constraints these encode, so they are not rediscovered:
  - H4 cannot block; the dispatcher is mid-turn by construction.
  - A push proves nothing; only a collect is evidence of delivery.
  - There is no timer, because there is no measured budget to put in one.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from nxb.h3 import (collect_report, directive_for, h3_validate, ratifiable,
                    refusal_scope, report_json_schema)
from nxb.h4 import Outbox


def outcome(key="k-1", delivery="REPORT_PRESENT", report=None):
    o = {"dispatch_key": key, "parent_receipt_id": "rcpt-1",
         "delivery": delivery,
         "provenance": {"runtime_id": "codex", "pinned_model": "m",
                        "refusal_scope": []},
         "effect": "UNCHECKED"}
    if report is not None:
        o["report"] = report
    return o


def good_report(task_id="k-1"):
    return {"task_id": task_id, "status": "COMPLETE", "summary": "s",
            "files_changed": "none", "commands_run": "none", "evidence": "e",
            "risks": "none", "next_action": "none", "was_refused": False}


class SchemaIsGeneratedNotCopied(unittest.TestCase):
    def test_the_runtime_schema_comes_from_the_published_contract(self):
        s = report_json_schema("k-9")
        self.assertEqual(s["properties"]["task_id"]["const"], "k-9")
        self.assertIn("was_refused", s["required"])
        self.assertEqual(s["properties"]["status"]["enum"],
                         ["COMPLETE", "BLOCKED", "FAILED"])
        self.assertFalse(s["additionalProperties"])

    def test_the_directive_tells_the_worker_the_broker_is_blind_to_refusals(self):
        body = directive_for("k-1", "do a thing")
        self.assertIn("was_refused", body)
        self.assertIn("CANNOT see a refusal", body)


class H3ObservesWithoutJudging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _collect(self, terminal=None):
        return collect_report(
            parent_receipt_id="rcpt-1", runtime_ref="t-1", out_path=self.out,
            terminal=terminal or {}, declaration={"refusal_signal": None})

    def test_a_missing_output_file_is_NO_REPORT_not_an_error(self):
        receipt, parts = self._collect()
        self.assertEqual(parts["delivery"], "NO_REPORT")
        self.assertEqual(parts["reason"], "no_output_file")
        self.assertEqual(receipt["hop"], "H3")

    def test_an_unparseable_report_is_NO_REPORT_not_a_crash(self):
        open(self.out, "w").write("this is not json")
        _, parts = self._collect()
        self.assertEqual(parts["delivery"], "NO_REPORT")
        self.assertTrue(parts["reason"].startswith("report_invalid"))

    def test_a_report_missing_a_required_field_is_refused(self):
        bad = good_report()
        del bad["evidence"]
        open(self.out, "w").write(json.dumps(bad))
        _, parts = self._collect()
        self.assertEqual(parts["delivery"], "NO_REPORT")

    def test_a_turn_that_failed_outranks_a_present_file(self):
        """F-14 generalised: the file's presence is not a success signal."""
        open(self.out, "w").write(json.dumps(good_report()))
        _, parts = self._collect(terminal={"turn_failed": True})
        self.assertEqual(parts["delivery"], "RUNTIME_FAILED")

    def test_a_good_report_is_carried_through_unjudged(self):
        open(self.out, "w").write(json.dumps(good_report()))
        _, parts = self._collect()
        self.assertEqual(parts["delivery"], "REPORT_PRESENT")
        self.assertEqual(parts["report"]["status"], "COMPLETE")

    def test_the_h3_receipt_carries_no_verdict(self):
        open(self.out, "w").write(json.dumps(good_report()))
        receipt, _ = self._collect()
        for f in ("ok", "valid", "status", "success", "verdict"):
            self.assertNotIn(f, receipt)

    def test_a_worker_claiming_BLOCKED_is_carried_not_overridden(self):
        r = good_report()
        r["status"] = "BLOCKED"
        r["was_refused"] = True
        open(self.out, "w").write(json.dumps(r))
        _, parts = self._collect()
        self.assertEqual(parts["delivery"], "REPORT_PRESENT")
        self.assertEqual(parts["report"]["status"], "BLOCKED")


class LayersStaySeparate(unittest.TestCase):
    def test_broker_delivery_and_worker_status_are_different_fields(self):
        o = outcome(report=good_report())
        self.assertEqual(o["delivery"], "REPORT_PRESENT")
        self.assertEqual(o["report"]["status"], "COMPLETE")
        h3_validate("outcome", o)

    def test_runtime_blindness_is_recorded_as_a_runtime_property(self):
        """Scope, not a boolean. A runtime can report one kind and not another.

        The boolean this replaced answered "can it report a refusal" with a yes
        that covered Claude Code's permission layer and NOT the sandbox case the
        question was written for [nxb-029/033].
        """
        sig = {"refusal_signal": "an event"}
        self.assertEqual(refusal_scope({**sig, "_refusal_scope": None}), [])
        self.assertEqual(refusal_scope({}), [])
        self.assertEqual(
            refusal_scope({**sig, "_refusal_scope": ["harness_mediated"]}),
            ["harness_mediated"])
        # a token outside the closed vocabulary is dropped, never passed through
        self.assertEqual(
            refusal_scope({**sig, "_refusal_scope": ["harness_mediated", "invented"]}),
            ["harness_mediated"])
        # a scope claimed with NO signal behind it is not a scope
        self.assertEqual(
            refusal_scope({"refusal_signal": None,
                           "_refusal_scope": ["harness_mediated"]}), [])
        # the tier that is open on every runtime measured so far
        self.assertNotIn("sandbox",
                         refusal_scope({**sig, "_refusal_scope": ["harness_mediated"]}))

    def test_an_outcome_may_not_carry_ok_or_success(self):
        for bad in ("ok", "success"):
            o = outcome()
            o[bad] = True
            with self.assertRaises(ValueError):
                h3_validate("outcome", o)


class H4NeverBlocksAndHasNoTimer(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.box = Outbox(self.conn)

    def test_collect_returns_the_outcome_not_an_acknowledgement(self):
        self.box.put(outcome(report=good_report()))
        got = self.box.collect("k-1")
        self.assertEqual(got["state"], "DELIVERED")
        self.assertEqual(got["outcome"]["report"]["status"], "COMPLETE")
        self.assertNotIn("success", got)

    def test_an_uncollected_outcome_shows_in_the_pending_list(self):
        self.box.put(outcome())
        self.assertEqual([p["dispatch_key"] for p in self.box.pending()], ["k-1"])

    def test_the_pending_list_is_the_alarm_and_never_clears_itself(self):
        """No timer, because no budget has been measured."""
        self.box.put(outcome())
        for _ in range(3):
            self.assertEqual(len(self.box.pending()), 1)

    def test_collecting_clears_it_from_pending(self):
        self.box.put(outcome())
        self.box.collect("k-1")
        self.assertEqual(self.box.pending(), [])

    def test_redelivery_is_on_demand_and_nothing_is_consumed_by_reading(self):
        self.box.put(outcome(report=good_report()))
        first = self.box.collect("k-1")
        second = self.box.collect("k-1")
        self.assertEqual(first["outcome"], second["outcome"])

    def test_an_unknown_key_is_named_as_such_not_reported_as_empty(self):
        got = self.box.collect("never-dispatched")
        self.assertEqual(got["state"], "UNKNOWN_KEY")

    def test_peek_does_not_mark_delivered(self):
        self.box.put(outcome())
        self.assertEqual(self.box.peek("k-1")["state"], "PENDING")
        self.assertEqual(len(self.box.pending()), 1)

    def test_a_re_put_does_not_lose_that_it_was_already_delivered(self):
        self.box.put(outcome())
        self.box.collect("k-1")
        self.box.put(outcome(delivery="NO_REPORT"))
        self.assertEqual(self.box.peek("k-1")["state"], "DELIVERED")


if __name__ == "__main__":
    unittest.main()


class RatificationRefusesOnFalsifiedOnly(unittest.TestCase):
    """The trap, tested for its absence.

    F-20 as originally written refused any outcome whose effect was not checked
    AND whose runtime could not report refusals. For Codex that is every
    outcome ever produced, so the rule would have refused one hundred percent
    of results forever, for a reason no operator can act on. It was removed
    before it was ever wired; these tests keep it removed.
    """

    def _mk(self, effect="UNCHECKED", status="COMPLETE",
                 delivery="REPORT_PRESENT"):
        o = outcome(delivery=delivery, report=good_report())
        o["report"]["status"] = status
        o["effect"] = effect
        o["provenance"]["refusal_scope"] = []
        return o

    def test_UNCHECKED_does_not_refuse_even_on_a_blind_runtime(self):
        """The whole point. A Codex outcome is ratifiable."""
        ok, reason = ratifiable(self._mk(effect="UNCHECKED"))
        self.assertTrue(ok, f"refused an unchecked outcome: {reason}")

    def test_a_blind_runtime_alone_never_refuses_anything(self):
        o = self._mk()
        o["provenance"]["refusal_scope"] = []
        self.assertTrue(ratifiable(o)[0])

    def test_FALSIFIED_refuses(self):
        ok, reason = ratifiable(self._mk(effect="FALSIFIED"))
        self.assertFalse(ok)
        self.assertEqual(reason, "effect_falsified")

    def test_VERIFIED_ratifies(self):
        self.assertTrue(ratifiable(self._mk(effect="VERIFIED"))[0])

    def test_a_worker_reporting_BLOCKED_is_not_ratified(self):
        ok, reason = ratifiable(self._mk(status="BLOCKED"))
        self.assertFalse(ok)
        self.assertIn("BLOCKED", reason)

    def test_a_missing_report_is_not_ratified(self):
        ok, _ = ratifiable(self._mk(delivery="NO_REPORT"))
        self.assertFalse(ok)

    def test_exactly_one_effect_value_refuses(self):
        refusing = [e for e in ("UNCHECKED", "VERIFIED", "FALSIFIED")
                    if not ratifiable(self._mk(effect=e))[0]]
        self.assertEqual(refusing, ["FALSIFIED"])


class EffectCheckIsOptionalAndCheap(unittest.TestCase):
    def test_the_two_conflated_facts_are_now_separate_fields(self):
        o = outcome(report=good_report())
        o["effect"] = "UNCHECKED"
        o["provenance"]["refusal_scope"] = []
        h3_validate("outcome", o)
        self.assertIn("effect", o)
        self.assertIn("refusal_scope", o["provenance"])
        self.assertNotIn("effect_unverified", o)

    def test_an_outcome_must_carry_an_effect(self):
        o = outcome(report=good_report())
        del o["effect"]
        with self.assertRaises(ValueError):
            h3_validate("outcome", o)

    def test_an_unknown_effect_value_is_refused(self):
        o = outcome(report=good_report())
        o["effect"] = "PROBABLY_FINE"
        with self.assertRaises(ValueError):
            h3_validate("outcome", o)
