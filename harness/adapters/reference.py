"""Adapter: the in-repo reference implementation.

Runs in its own interpreter. Both implementations are packages named `nxb` and
cannot co-import; the harness crosses a PROCESS boundary rather than renaming
either one, so neither artefact under test is modified. See harness/README.md.

Protocol: one JSON job on stdin, one JSON result line on stdout. Always exits 0.
An exception inside the implementation is DATA ("raised"), not an adapter
failure, because whether an input raises rather than returning one of the three
shapes is itself a thing the harness compares.
"""
import json, sys, os

IMPL = os.environ.get("NXB_IMPL", "/Users/rohan/dev/nexus-bridge")
sys.path.insert(0, IMPL)

from nxb.dispatch import Broker
from nxb.ledger import Ledger
from nxb.receipt import digest_units, canonical_bytes
from nxb.runtimes import register, RegistrationRefused


def _broker(decl, prove):
    registry = {}
    d = dict(decl)
    if prove:
        d["last_proven_at"] = "2026-08-28T16:00:00Z"
    register(d, registry)
    # proof_store is left None: this arm's liveness gate is a no-op without one,
    # which is how this arm is unblocked. The Codex arm needs prove_liveness().
    return Broker(Ledger(":memory:"), registry=registry)


def run(job):
    op = job["op"]
    if op == "digest":
        return {"digest": digest_units(job["units"]),
                "bytes": len(canonical_bytes(job["units"]))}
    if op == "register":
        try:
            register(dict(job["declaration"]), {})
            return {"registered": True}
        except RegistrationRefused as e:
            return {"registered": False, "reason": e.reason}
    if op == "dispatch_seq":
        b = _broker(job["declaration"], job.get("prove", True))
        return {"returns": [b.dispatch(e) for e in job["envelopes"]]}
    raise ValueError("unknown op " + op)


def main():
    job = json.load(sys.stdin)
    try:
        out = {"ok": True, **run(job)}
    except BaseException as e:
        out = {"ok": False, "raised": "%s: %s" % (type(e).__name__, e)}
    sys.stdout.write(json.dumps(out, ensure_ascii=True, default=str) + "\n")


main()
