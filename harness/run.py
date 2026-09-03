"""Run the differential suite. `python3 harness/run.py [--json out.json]`"""

import json, sys, pathlib, itertools

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from differ import (ARMS, EQUIV, build_workspaces, prove_isolation, run_job,
                    compare_receipts, compare_returns)
from corpus import CASES, INTERNAL_PAIRS

DECL = {
    "runtime_id": "claude_code", "spawn": "x", "start_signal": "peer_message_status",
    "start_timeout": 30, "identity": "ref+pid", "terminal_signal": None,
    "refusal_signal": None, "cancel": "SIGINT", "progress_signal": "peer_idle_notice",
    "last_proven_at": None,
    "_null_reasons": {"terminal_signal": "UNMEASURED", "refusal_signal": "UNMEASURED"},
}

findings = []


def finding(kind, probe, detail, verdict="UNWRITTEN", entry=None):
    findings.append({"kind": kind, "probe": probe, "detail": detail,
                     "verdict": verdict,
                     "missing_clause": (entry or {}).get("missing_clause"),
                     "basis": (entry or {}).get("basis")})


def envelope(units, digest, key="k-1", count=None):
    return {"dispatch_key": key, "runtime_id": "claude_code",
            "declared_count": len(units) if count is None else count,
            "declared_digest": digest, "units": units, "dispatcher_id": "harness"}


def main():
    ws = build_workspaces()
    listing, isolation_problems = prove_isolation()
    print("=" * 78)
    print("ISOLATION: %d files across %d arms; problems: %s"
          % (len(listing), len(ARMS), isolation_problems or "none"))
    for p in isolation_problems:
        finding("ISOLATION", "workspace", p, "MUST_MATCH")
    names = [a["name"] for a in ARMS]

    # ---------------------------------------------------------- 1. digests
    print("\n" + "=" * 78 + "\nPROBE 1  canonicalisation: digest and payload_bytes\n" + "=" * 78)
    digests = {n: {} for n in names}
    for cid, units, why in CASES:
        row = {}
        for n in names:
            r = run_job(n, {"op": "digest", "units": units}, ws)
            row[n] = r
            digests[n][cid] = r
        vals = [(row[n].get("digest") if row[n].get("ok") else "RAISED:" + str(row[n].get("raised"))[:40]) for n in names]
        byts = [row[n].get("bytes") for n in names]
        agree = len(set(vals)) == 1
        bagree = len(set(byts)) == 1
        if not agree or not bagree:
            mark = "DIVERGE"
            for field, got in (("payload_digest", vals), ("payload_bytes", byts)):
                if len(set(got)) > 1:
                    v, e = EQUIV["receipt"][field].get("verdict"), EQUIV["receipt"][field]
                    finding("DIVERGENCE", "digest/%s" % cid,
                            "%s: %s" % (field, dict(zip(names, got))) + "  [%s]" % why, v, e)
        else:
            mark = "agree  "
        print("  %-8s %-18s %s" % (mark, cid, dict(zip(names, [str(v)[:18] for v in vals]))))

    # ------------------------------------------------- 2. within-arm pairs
    print("\n" + "=" * 78 + "\nPROBE 2  within-arm collision pairs\n" + "=" * 78)
    for a_id, b_id, expect, why in INTERNAL_PAIRS:
        for n in names:
            da, db = digests[n][a_id].get("digest"), digests[n][b_id].get("digest")
            same = da == db and da is not None
            ok = (same and expect == "same") or (not same and expect == "distinct")
            print("  %-8s %-6s %s vs %s  expect %s" % ("ok" if ok else "FAIL", n, a_id, b_id, expect))
            if not ok:
                finding("DIVERGENCE", "pair/%s" % n,
                        "%s vs %s expected %s: %s" % (a_id, b_id, expect, why), "MUST_MATCH")

    # ---------------------------------------------------- 3. full dispatch
    print("\n" + "=" * 78 + "\nPROBE 3  dispatch: receipts and returns\n" + "=" * 78)
    for cid, units, why in CASES:
        per = {}
        for n in names:
            d = digests[n][cid].get("digest") or "0" * 64
            per[n] = run_job(n, {"op": "dispatch_seq", "declaration": DECL, "prove": True,
                                 "envelopes": [envelope(units, d, "k-" + cid)]}, ws)
        a, b = per[names[0]], per[names[1]]
        if a.get("ok") != b.get("ok"):
            finding("DIVERGENCE", "dispatch/%s" % cid,
                    "one arm raised and the other did not: %s=%s  %s=%s"
                    % (names[0], a.get("raised", "returned"), names[1], b.get("raised", "returned")),
                    "MUST_MATCH", EQUIV["process"]["raises"])
            print("  RAISE-DIVERGE %-18s %s / %s" % (cid, a.get("raised", "ok")and str(a.get("raised","ok"))[:28], str(b.get("raised", "ok"))[:28]))
            continue
        if not a.get("ok"):
            print("  both-raised   %-18s %s" % (cid, str(a.get("raised"))[:44]))
            continue
        diffs = compare_returns(a["returns"][0], b["returns"][0])
        if diffs:
            print("  DIVERGE       %-18s %s" % (cid, [d[0] for d in diffs]))
            for f, mode, va, vb, v, e in diffs:
                finding("DIVERGENCE", "dispatch/%s" % cid,
                        "%s %s: %s=%r %s=%r" % (f, mode, names[0], va, names[1], vb), v, e)
        else:
            print("  agree         %-18s state=%s" % (cid, a["returns"][0]["state"]))

    # ------------------------------------------------- 4. CROSS-ARM dispatch
    print("\n" + "=" * 78 + "\nPROBE 4  cross-arm: arm A computes declared_digest, arm B brokers it\n" + "=" * 78)
    for cid, units, why in CASES:
        for sender, broker in itertools.permutations(names, 2):
            d = digests[sender][cid].get("digest")
            if not d:
                continue
            r = run_job(broker, {"op": "dispatch_seq", "declaration": DECL, "prove": True,
                                 "envelopes": [envelope(units, d, "x-%s-%s" % (cid, sender))]}, ws)
            if not r.get("ok"):
                continue
            ret = r["returns"][0]
            if ret["state"] != "OBSERVED":
                print("  REFUSED  sender=%-9s broker=%-9s %-18s %s"
                      % (sender, broker, cid, ret.get("reason")))
                finding("INTEROP", "cross/%s" % cid,
                        "%s computed the digest, %s refused it: %s  [%s]"
                        % (sender, broker, ret.get("reason"), why),
                        "MUST_MATCH", EQUIV["receipt"]["payload_digest"])

    # ------------------------------------------- 5. behavioural divergences
    print("\n" + "=" * 78 + "\nPROBE 5  known behavioural paths\n" + "=" * 78)
    u = [{"summary": "one unit"}]
    seqs = {
        "repeat-changed-payload": lambda d: [envelope(u, d, "r1"), envelope([{"summary": "DIFFERENT"}], d, "r1")],
        "repeat-after-refused":   lambda d: [envelope(u, d, "r2", count=99), envelope(u, d, "r2")],
    }
    for label, mk in seqs.items():
        per = {}
        for n in names:
            d = digests[n]["ascii-baseline"]["digest"]
            per[n] = run_job(n, {"op": "dispatch_seq", "declaration": DECL, "prove": True,
                                 "envelopes": mk(d)}, ws)
        states = {n: [r["state"] for r in per[n]["returns"]] for n in names}
        print("  %-24s %s" % (label, states))
        if len(set(map(tuple, states.values()))) > 1:
            finding("DIVERGENCE", "sequence/%s" % label,
                    "state sequences differ: %s" % states, "MUST_MATCH",
                    EQUIV["dispatch_return"]["state"])

    # --------------------------------------------------- 6. registration
    print("\n" + "=" * 78 + "\nPROBE 6  registration: null capability with and without a reason\n" + "=" * 78)
    for label, decl in (("with-reasons", DECL),
                        ("without-reasons", {**DECL, "_null_reasons": {}}),
                        ("null-start-signal", {**DECL, "start_signal": None})):
        got = {n: run_job(n, {"op": "register", "declaration": decl}, ws) for n in names}
        summary = {n: (got[n].get("registered"), got[n].get("reason")) for n in names}
        print("  %-20s %s" % (label, summary))
        if len(set(str(v) for v in summary.values())) > 1:
            finding("DIVERGENCE", "register/%s" % label, "registration disagreed: %s" % summary,
                    "UNWRITTEN", {"missing_clause": "Whether a null capability without a "
                                  "MEASURED_ABSENT/UNMEASURED reason may be registered.",
                                  "basis": "unwritten_clause"})

    # ------------------------------------------------------------- report
    print("\n" + "=" * 78 + "\nSUMMARY\n" + "=" * 78)
    by = {}
    for f in findings:
        by.setdefault(f["verdict"], []).append(f)
    print("  findings: %d   %s" % (len(findings), {k: len(v) for k, v in by.items()}))
    print("\n  MUST_MATCH divergences are DEFECTS in an implementation:")
    for f in by.get("MUST_MATCH", [])[:14]:
        print("    - %-26s %s" % (f["probe"], f["detail"][:110]))
    print("\n  UNWRITTEN divergences are MISSING CONTRACT CLAUSES:")
    seen = set()
    for f in by.get("UNWRITTEN", []):
        c = f["missing_clause"] or f["detail"][:80]
        if c in seen:
            continue
        seen.add(c)
        print("    - %s" % c)
    if "--json" in sys.argv:
        out = pathlib.Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps({"findings": findings, "isolation": listing}, indent=2), encoding="utf-8")
        print("\n  wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
