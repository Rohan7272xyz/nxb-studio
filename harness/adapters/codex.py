"""Adapter: the Codex blind implementation (nxb-009).

Runs in its own interpreter. Both implementations are packages named `nxb` and
cannot co-import; the harness crosses a PROCESS boundary rather than renaming
either one, so neither artefact under test is modified. See harness/README.md.

Protocol: one JSON job on stdin, one JSON result line on stdout. Always exits 0.
An exception inside the implementation is DATA ("raised"), not an adapter
failure, because whether an input raises rather than returning one of the three
shapes is itself a thing the harness compares.
"""
import json, sys, os

IMPL = os.environ.get("NXB_IMPL", "/Users/rohan/dev/nexus-bridge/evidence/nxb-009/codex-implementation")
sys.path.insert(0, IMPL)

from nxb.dispatch import Broker
from nxb.schema import units_digest, units_bytes
from nxb.runtimes import RegistrationRefused

digest_units, canonical_bytes = units_digest, units_bytes


def _broker(decl, prove):
    b = Broker(":memory:")
    b.register_runtime(dict(decl))
    if prove:
        # This arm gates on liveness unconditionally and invented an explicit
        # proof call. The reference has no equivalent; see nxb-009 C-6.
        b.prove_liveness(decl["runtime_id"], "2026-08-28T16:00:00Z")
    return b


def run(job):
    op = job["op"]
    if op == "digest":
        return {"digest": digest_units(job["units"]),
                "bytes": len(canonical_bytes(job["units"]))}
    if op == "register":
        try:
            Broker(":memory:").register_runtime(dict(job["declaration"]))
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
