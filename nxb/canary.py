"""The canary, now a round trip with a trivial payload.

This file used to hand-roll H1, H2, the drain and its own terminal check,
because when it was written there was no H3 and no round trip to reuse. Closing
the loop deleted most of it: a canary is not a special code path, it is the
smallest possible dispatch.

What survives is the part that was always canary-specific: recording a proof on
success and a disproof on failure.
"""

import os
import uuid

from nxb.proof import codex_evidence_verifier, make_proof
from nxb.receipt import digest_units, utc_now
from nxb.roundtrip import RoundTrip

CANARY_UNIT = {"instruction": "Reply with status COMPLETE and a one-word "
                              "summary. Do nothing else."}

#: The canary's OWN deadline, deliberately not the dispatch drain_budget.
#:
#: Measurement says neither runtime returns on its own when the API is dead:
#: Codex was still emitting "Reconnecting..." when killed at 60s, and Claude
#: Code was still retrying on a doubling backoff at 69s. [M: nxb-022] So a
#: canary that inherits a generous drain budget sits out the entire outage on
#: every run, and the broker has to impose the bound.
#:
#: PROVISIONAL. It is roughly 8x the one measured healthy canary round trip
#: (3.5s to turn.completed, evidence/nxb-022/timeline.json). One sample is not
#: a distribution and this number is not yet earned. See CANARY-DEADLINE-BASIS
#: in FINDINGS.json.
#:
#: What makes a provisional constant tolerable here: since the runtime's own
#: failure announcement is now consumed, this deadline is the BACKSTOP rather
#: than the detector. It no longer sets how fast a dead API is noticed, so
#: getting it wrong costs a slower abort in the cases nothing is announced,
#: not a missed failure. That is the opposite of the timer this project twice
#: found gets widened until it stops firing.
CANARY_DEADLINE_S = 30.0


def run_canary(*, ledger, registry, adapter, proof_store, run_root, work_dir,
               start_timeout=5, deadline=CANARY_DEADLINE_S):
    """One full-path canary: H1 to H4. Returns a result dict; never raises."""
    runtime_id = adapter.runtime_id
    key = "canary-" + uuid.uuid4().hex[:12]
    units = [CANARY_UNIT]
    envelope = {
        "dispatch_key": key, "runtime_id": runtime_id, "declared_count": 1,
        "declared_digest": digest_units(units), "units": units,
        "dispatcher_id": "nxb-canary",
    }

    rt = RoundTrip(ledger=ledger, registry=registry, adapter=adapter,
                   run_root=run_root, work_dir=work_dir)
    # canary=True makes the drain abort the moment the runtime announces its
    # own failure, instead of waiting out `deadline` to discover the output
    # file is missing. The deadline remains as the backstop for a runtime that
    # fails without saying so.
    out = rt.dispatch(envelope, canary=True,
                      start_timeout=start_timeout, drain_budget=deadline)

    if out["state"] != "OBSERVED":
        return _fail(runtime_id, key, "h1_" + out.get("reason", "refused"),
                     proof_store)

    collected = rt.collect(key)
    outcome = collected.get("outcome", {})
    delivery = outcome.get("delivery")

    # A canary that started but did not come back is NOT a pass. The whole
    # point is the full chain; a partial chain proves only the part it reached.
    if delivery != "REPORT_PRESENT":
        return _fail(runtime_id, key,
                     outcome.get("reason") or delivery or "no_outcome",
                     proof_store)

    thread_id = outcome["provenance"]["runtime_ref"]
    evidence = adapter.evidence_for(thread_id)
    if evidence is None:
        # An unprovable pass is not a proof.
        return _fail(runtime_id, key, "no_verifiable_evidence", proof_store)

    proof = make_proof(
        runtime_id=runtime_id, proven_at=utc_now(), method="canary",
        runtime_ref=thread_id, evidence_path=evidence,
    )
    proof_store.put(proof)
    # nxb-031: this return value used to be discarded, so a canary could report
    # ok while its own proof FAILED verification and a standing disproof
    # survived untouched. That is the same shape as C14 -- a verdict
    # disagreeing with its own evidence -- and it contradicts the rule applied
    # four lines above, that an unprovable pass is not a proof. Treated as a
    # bug rather than as a choice.
    if not proof_store.clear_disproof(runtime_id, proof=proof,
                                      verifier=codex_evidence_verifier):
        return _fail(runtime_id, key, "proof_failed_verification", proof_store)

    return {"ok": True, "runtime_id": runtime_id, "dispatch_key": key,
            "proof": proof, "outcome": outcome}


def _fail(runtime_id, key, reason, proof_store):
    if proof_store is not None:
        proof_store.put_disproof(runtime_id, at=utc_now(), reason=reason)
    return {"ok": False, "runtime_id": runtime_id, "dispatch_key": key,
            "reason": reason}
