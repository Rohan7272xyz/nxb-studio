"""The whole loop: H1 dispatch, H2 spawn, H3 report, H4 collect.

The first time in this project that a dispatch can return an answer.

Two calls make the round trip, and each returns the thing rather than an
acknowledgement that a thing happened:

    rt.dispatch(envelope)  -> H1 receipt, then H2, then H3, then an outbox entry
    rt.collect(key)        -> the outcome

`dispatch` blocks only on hops that CAN block. H1 is local. H2 is bounded by
start_timeout. H3 is bounded by drain_budget, and both budgets are the runtime's
own measured numbers rather than invented ones. H4 does not block at all: the
outcome lands in a durable outbox and waits to be collected.
"""

from nxb.dispatch import Broker
from nxb.h2 import SpawnHop
from nxb.h3 import (collect_report, directive_for, refusal_scope,
                    report_json_schema)
from nxb.h4 import Outbox
from nxb.receipt import render_directive, utc_now


class RoundTrip:
    def __init__(self, *, ledger, registry, adapter, proof_store=None,
                 prover=None, run_root, work_dir):
        self.ledger = ledger
        self.registry = registry
        self.adapter = adapter
        self.broker = Broker(ledger, registry=registry,
                             proof_store=proof_store, prover=prover)
        self.outbox = Outbox(ledger._conn)
        self.run_root = run_root
        self.work_dir = work_dir

    def dispatch(self, envelope, *, start_timeout=None, drain_budget=120,
                 canary=False, effect_check=None):
        """H1 through H3, ending with an outcome in the outbox.

        The work comes from `envelope["units"]`. Before nxb-021 there was a
        separate `body` argument carrying the instruction while `units` was
        hashed, counted, refused on and never sent, so the digest and count
        guards protected a decoy. There is one payload now.
        """
        import json
        import os

        key = envelope["dispatch_key"]

        # nxb-031. A replay must return the answer, not re-run the pipeline,
        # AND NOT BEFORE THE DIVERGENCE CHECK.
        #
        # Two defects, one ordering. Measured: retrying with the same key
        # destroyed the result it was retrying to obtain, because spawn_once
        # correctly refused the duplicate and this method recorded that refusal
        # as a fresh RUNTIME_FAILED outcome, clobbering a delivered report.
        # My first fix short-circuited to the outbox BEFORE H1, which silently
        # reintroduced F1: a changed directive under a reused key got the old
        # answer back with exit 0, which is the exact defect a cold user found.
        #
        # So H1 runs first and refuses divergence; only an envelope H1 accepted
        # as identical may be answered from the outbox.
        h1 = self.broker.dispatch(envelope, canary=canary)
        if h1["state"] != "OBSERVED":
            return h1

        existing = self.outbox.peek(key)
        if existing.get("state") != "UNKNOWN_KEY" and existing.get("outcome"):
            return {"state": "OBSERVED", "dispatch_key": key, "replayed": True,
                    "outcome": existing["outcome"]}

        parent = h1["pending_ref"]
        run_dir = os.path.join(self.run_root, key)
        os.makedirs(run_dir, exist_ok=True)

        # The report schema is GENERATED from the published contract and handed
        # to the runtime, so the runtime constrains the report rather than the
        # broker parsing prose. [M: nxb-002, --output-schema works.]
        schema_path = os.path.join(run_dir, "report-schema.json")
        with open(schema_path, "w", encoding="utf-8") as handle:
            json.dump(report_json_schema(key), handle)

        declaration = self.registry.get(envelope["runtime_id"], {})
        # The runtime's DECLARED start_timeout is the source of truth. It was
        # measured, put in the declaration, and then ignored in favour of a
        # default argument; the never-read guard caught that in nxb-020.
        if start_timeout is None:
            start_timeout = declaration.get("start_timeout") or 5

        body = render_directive(envelope["units"])
        hop = SpawnHop(self.ledger, self.adapter)
        h2 = hop.spawn(parent, work_dir=self.work_dir,
                       prompt=directive_for(key, body), run_dir=run_dir,
                       start_timeout=start_timeout, schema_path=schema_path)

        if h2["state"] != "STARTED":
            if str(h2.get("reason", "")).startswith("already_spawned"):
                # A spawn that already happened is not a new failure. Recording
                # one would overwrite whatever the first spawn produced.
                # RT-2: carry the exposure up. dispatch_status stays
                # DID_NOT_HAPPEN and is known to be wrong for the same reason
                # the layer below keeps DID_NOT_START: the right term is
                # embargoed, and inventing one here would pre-empt a decision
                # that is not a worker's to make.
                out = {"state": "REFUSED", "dispatch_key": key,
                       "reason": h2.get("reason"),
                       "dispatch_status": "DID_NOT_HAPPEN",
                       "receipt": h1["receipt"], "pending_ref": parent,
                       "h2": h2}
                for k in ("runtime_ref", "evidence_path"):
                    if h2.get(k):
                        out[k] = h2[k]
                return out
            outcome = self._outcome(key, parent, "RUNTIME_FAILED", None,
                                    h2.get("reason"), declaration, None,
                                    effect="UNCHECKED")
            self.outbox.put(outcome)
            # A response whose state reads as success must not carry a failure
            # in a nested field. The spawn refused, so the response refuses.
            return {"state": "REFUSED", "dispatch_key": key,
                    "reason": h2.get("reason", "spawn_refused"),
                    "dispatch_status": "DID_NOT_HAPPEN",
                    "receipt": h1["receipt"], "pending_ref": parent,
                    "h2": h2}

        terminal = self.adapter.drain(hop.last_handle, budget=drain_budget,
                                      abort_on_announced_failure=canary)
        h3_receipt, parts = collect_report(
            parent_receipt_id=parent,
            runtime_ref=h2["receipt"]["runtime_ref"],
            out_path=hop.last_handle["out_path"],
            terminal=terminal, declaration=declaration,
        )
        # Verification is cheap where the effect is externally checkable, and
        # absent where it is not. Both are honest; only FALSIFIED refuses.
        effect = "UNCHECKED"
        if effect_check is not None:
            try:
                effect = "VERIFIED" if effect_check(parts["report"]) else "FALSIFIED"
            except Exception:                                  # noqa: BLE001
                effect = "UNCHECKED"

        outcome = self._outcome(key, parent, parts["delivery"], parts["report"],
                                parts["reason"], declaration, h2["receipt"],
                                effect=effect)
        self.outbox.put(outcome)

        return {"state": "OBSERVED", "dispatch_key": key,
                "receipt": h1["receipt"], "pending_ref": parent,
                "h2": h2, "h3_receipt": h3_receipt, "terminal": terminal}

    def collect(self, dispatch_key):
        """H4. Returns the outcome; never blocks; safe to call repeatedly."""
        return self.outbox.collect(dispatch_key)

    def pending(self):
        return self.outbox.pending()

    @staticmethod
    def _outcome(key, parent, delivery, report, reason, declaration, h2_receipt,
                 *, effect="UNCHECKED"):
        return {
            "dispatch_key": key,
            "parent_receipt_id": parent,
            "delivery": delivery,
            **({"report": report} if report is not None else {}),
            **({"reason": reason} if reason else {}),
            # R-030/R-031 survive from the provenance work: pin what was asked
            # for, record what the runtime said, carry both with the answer.
            "provenance": {
                "runtime_id": declaration.get("runtime_id"),
                "pinned_model": h2_receipt.get("pinned_model") if h2_receipt else None,
                "runtime_ref": h2_receipt.get("runtime_ref") if h2_receipt else None,
                "recorded_at": utc_now(),
                # A property of the RUNTIME, recorded once, never mixed into
                # the per-outcome effect field.
                # WHAT KINDS of refusal this runtime can report, not whether
                # it can report "a refusal". A boolean here read as the stronger
                # claim; see nxb/h3.py REFUSAL_SCOPE. Recorded, never refused on.
                "refusal_scope": refusal_scope(declaration),
            },
            "effect": effect,
        }
