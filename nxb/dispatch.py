"""The H1 dispatch call.

R-050, as amended by measurement in nxb-006: a dispatch must be a call that
returns THE RECEIPT, not a call that returns an acknowledgement of
transmission. Measured 2026-08-28: `SendMessage` to a peer that `ListAgents`
itself displays as offline returns `success:true` with a msg_id. A transmission
ack that is uncorrelated with delivery is an emission with extra steps.

Three terminal return shapes and nothing else:

  OBSERVED   the receipt, plus a pending_ref into the durable ledger
  REFUSED    a POSITIVE assertion that the dispatch did not happen
  UNKNOWN    the broker does not know. NEVER rendered as failure (F-24)
"""

from nxb.contract import validate, ContractError
from nxb.ledger import Ledger
from nxb.proof import DISPROVEN, gate_state
from nxb.receipt import (CanonicalisationError, digest_envelope,
                         make_receipt, utc_now)


class _ReceiptToken:
    """Proof that a receipt was durably recorded.

    F-6 enforcement. `_interpret` will not run without one of these, and the
    only way to obtain one is `_observe`, which records the receipt first. The
    check is not a naming convention: the token is re-verified against the
    ledger, so a forged token still cannot unlock interpretation of a payload
    whose receipt was never written.
    """

    __slots__ = ("receipt_id",)

    def __init__(self, receipt_id):
        self.receipt_id = receipt_id


class Broker:
    def __init__(self, ledger, *, observer="nxb-broker", registry=None,
                 proof_store=None, prover=None):
        self.ledger = ledger if isinstance(ledger, Ledger) else Ledger(ledger)
        self.observer = observer
        self.registry = registry if registry is not None else {}
        self.proof_store = proof_store
        #: Optional callable(runtime_id) -> bool. The on-demand canary. When a
        #: runtime is DISPROVEN and a prover is supplied, the broker gives it
        #: one chance to prove itself rather than refusing on stale bad news.
        #: OPT-IN, because an automatic retry loop against a permanently dead
        #: runtime would need a backoff number, and a number nobody has is what
        #: this task exists to delete.
        self.prover = prover

    # ---------------------------------------------------------------- observe

    def _observe(self, envelope, *, envelope_digest=None):
        """Emit and durably record a receipt. Interprets nothing."""
        receipt = make_receipt(envelope, observer=self.observer)
        validate("receipt", receipt)
        self.ledger.record_receipt(
            receipt,
            runtime_id=envelope["runtime_id"],
            dispatcher_id=envelope["dispatcher_id"],
            now=utc_now(),
            envelope_digest=envelope_digest,
        )
        return receipt, _ReceiptToken(receipt["receipt_id"])

    # -------------------------------------------------------------- interpret

    def _interpret(self, token, envelope):
        """Validate the payload. Requires proof a receipt already exists."""
        if not isinstance(token, _ReceiptToken):
            raise AssertionError("F-6: refused to interpret without a receipt token")
        row = self.ledger.find_by_dispatch_key(envelope["dispatch_key"])
        if row is None or row["receipt_id"] != token.receipt_id:
            raise AssertionError(
                "F-6: refused to interpret; no durable receipt for this payload"
            )

        if envelope["payload_digest_declared"] != envelope["payload_digest_observed"]:
            return "REJECTED", "digest_divergence"
        if envelope["declared_count"] != envelope["observed_count"]:
            return "REJECTED", "count_divergence"
        return "ACCEPTED", None

    # ---------------------------------------------------------------- dispatch

    def dispatch(self, envelope, *, canary=False):
        """The call. Returns one of three shapes for ANY INPUT, never raises on one.

        The totality is over ENVELOPES, and that is the whole of it. Two storage
        conditions raise straight through this method, and pretending otherwise
        was the defect CONC-1 recorded:

        * Using one Ledger from a second thread raises LedgerThreadError. The
          broker is single-threaded by contract; open one Ledger per thread or
          per process. [M: nxb-030/038] Before nxb-038 this leaked
          sqlite3.ProgrammingError, which pointed the reader at sqlite instead
          of at the sharing that caused it.
        * Lock contention on the database file can raise
          sqlite3.OperationalError("database is locked") once writers wait
          longer than busy_timeout. Not reachable at measured volumes, 800 of
          800 across 16 processes with no errors, but reachable in principle and
          tracked as CONC-2 rather than caught here. Catching it would turn an
          infrastructure failure into a REFUSED envelope, which is a different
          lie: the envelope was fine and the work did not happen.

        `canary` skips only the liveness gate. A canary that had to be proven
        live before it could prove liveness would be circular.
        """
        key = envelope.get("dispatch_key") if isinstance(envelope, dict) else None

        # R-051, corrected in nxb-021 after a cold user hit it by reflex.
        #
        # The old rule returned the original receipt for ANY repeat of a key.
        # An operator who fixed a typo in one unit and re-ran the same command
        # got state OBSERVED, exit 0, the original receipt and the digest of
        # the OLD payload, with nothing anywhere saying the submitted payload
        # differed. They walked away believing the correction had shipped.
        #
        # Identical envelope  -> the original receipt AND the original
        #                        disposition, so a retry after an unknown
        #                        outcome is still safe and cannot launder a
        #                        refusal into a success.
        # Different envelope  -> REFUSED. A changed payload under a used key is
        #                        a new dispatch wearing an old name.
        submitted_digest = None
        if isinstance(envelope, dict):
            try:
                submitted_digest = digest_envelope(envelope)
            except CanonicalisationError as exc:
                # N-1 and N-2. Refuse rather than mint a receipt over bytes no
                # other runtime can parse or transmit.
                return self._ret("REFUSED", key,
                                 reason="uncanonicalisable_payload",
                                 detail=str(exc),
                                 dispatch_status="DID_NOT_HAPPEN")
            except (TypeError, ValueError):
                submitted_digest = None

        if key is not None:
            existing = self.ledger.find_by_dispatch_key(key)
            if existing is not None:
                import json as _json
                recorded = existing["envelope_digest"]
                if (recorded is not None and submitted_digest is not None
                        and recorded != submitted_digest):
                    return self._ret(
                        "REFUSED", key, reason="dispatch_key_reuse_divergence",
                        detail="this key already carries a different payload; "
                               "use a new dispatch_key for a revision",
                        dispatch_status="DID_NOT_HAPPEN")

                # Identical resubmission: replay the ORIGINAL answer, whatever
                # it was. Pressing up-arrow must not turn a refusal into a
                # success.
                prior = self.ledger.disposition_for(existing["receipt_id"])
                if prior is not None and prior["outcome"] == "REJECTED":
                    return self._ret(
                        "REFUSED", key, reason=prior["reason"] or "rejected",
                        receipt=_json.loads(existing["receipt_json"]),
                        pending_ref=existing["receipt_id"],
                        dispatch_status="DID_NOT_HAPPEN")
                return self._ret(
                    "OBSERVED", key,
                    receipt=_json.loads(existing["receipt_json"]),
                    pending_ref=existing["receipt_id"],
                )

        try:
            validate("envelope", envelope)
        except ContractError as exc:
            return self._ret("REFUSED", key, reason="malformed_envelope",
                             detail=str(exc), dispatch_status="DID_NOT_HAPPEN")

        declaration = self.registry.get(envelope["runtime_id"])
        if declaration is None:
            return self._ret("REFUSED", key, reason="runtime_unregistered",
                             detail=envelope["runtime_id"],
                             dispatch_status="DID_NOT_HAPPEN")

        # F-5, whole. Fail closed on DISPROVEN, fail open on UNPROVEN.
        if not canary and self.proof_store is not None:
            state, action = gate_state(self.proof_store, envelope["runtime_id"])
            if action == "REFUSE":
                # On-demand canary: the only surviving form of "reprove", now
                # attached to the only state that still refuses. Nothing here
                # runs on a timer and an idle system costs nothing.
                proved = False
                if self.prover is not None:
                    proved = bool(self.prover(envelope["runtime_id"]))
                if not proved:
                    return self._ret("REFUSED", key, reason="runtime_disproven",
                                     detail=envelope["runtime_id"],
                                     dispatch_status="DID_NOT_HAPPEN")
            self.last_gate = (state, action)

        # F-6. The receipt is written BEFORE anything looks at the units.
        receipt, token = self._observe(envelope, envelope_digest=submitted_digest)

        enriched = dict(envelope)
        enriched["payload_digest_declared"] = envelope["declared_digest"]
        enriched["payload_digest_observed"] = receipt["payload_digest"]
        enriched["observed_count"] = receipt["observed_count"]

        outcome, reason = self._interpret(token, enriched)

        # F-11. Exactly one disposition per receipt, always.
        self.ledger.record_disposition(
            receipt["receipt_id"], outcome, reason, now=utc_now()
        )

        if outcome == "REJECTED":
            # F-8 / F-9. The receipt still exists and the sender still gets it:
            # the dispatch was observed and refused, which is a different fact
            # from "never seen", and the sender is entitled to both.
            return self._ret("REFUSED", key, reason=reason, receipt=receipt,
                             pending_ref=receipt["receipt_id"],
                             dispatch_status="DID_NOT_HAPPEN")

        return self._ret("OBSERVED", key, receipt=receipt,
                         pending_ref=receipt["receipt_id"])

    # ------------------------------------------------------------------ return

    @staticmethod
    def _ret(state, key, *, receipt=None, pending_ref=None, reason=None,
             detail=None, dispatch_status=None):
        out = {"state": state, "dispatch_key": key or ""}
        if receipt is not None:
            out["receipt"] = receipt
        if pending_ref is not None:
            out["pending_ref"] = pending_ref
        if reason is not None:
            out["reason"] = reason if detail is None else f"{reason}: {detail}"
        if dispatch_status is not None:
            out["dispatch_status"] = dispatch_status
        validate("dispatch_return", out)
        return out
