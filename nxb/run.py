"""`nxb run`: one command that dispatches a directive and returns the answer.

Everything else in this package was a reliability layer with nothing in front
of it. `RoundTrip` was the only code that spawns a runtime and returns an
answer, and grep found its sole caller in the tree was the canary, with a
hardcoded trivial payload [nxb-030]. So the layer had never been in the path of
a real dispatch, including every dispatch made while building it.

This is the surface that makes the substitution possible. The shape that
matters: THE HUMAN NEVER TOUCHES AN ENVELOPE. The caller supplies a directive
and a runtime; the envelope, the dispatch key and the canonical digest are
computed here.

On the dispatch key, which is the one real design decision:

  A key is generated per invocation by default, so running the same directive
  twice runs it twice. Deriving it from content would have made re-running a
  task impossible, and generating it randomly with no way to name it would
  make R-051's retry safety unreachable. So: `--dispatch-key` is exposed, the
  generated key is PRINTED, and passing it back is how a caller retries an
  UNKNOWN without risking a duplicate. The divergence refusal that F1 cost us
  stays live for exactly that path: reuse a key with a changed directive and
  it refuses rather than handing back the old receipt.
"""

import json
import os
import sys
import uuid

from nxb.adapters.claude_code import ClaudeCodeAdapter
from nxb.adapters.codex import CodexAdapter
from nxb.grants import DEFAULT_GRANT, adapter_kwargs, describe
from nxb.h3 import h3_validate
from nxb.ledger import Ledger
from nxb.receipt import CanonicalisationError, digest_units
from nxb.roundtrip import RoundTrip
from nxb.runtimes import register, RegistrationRefused

#: runtime_id -> adapter. A runtime with no adapter cannot be dispatched to,
#: and saying so by name beats a KeyError.
ADAPTERS = {
    "codex": CodexAdapter,
    "claude_code": ClaudeCodeAdapter,
}

#: Exit codes carry state, and 1 is deliberately unused so a shell's
#: `|| echo failed` cannot merge a refusal with an unknown.
EXIT = {
    "COMPLETE": 0,
    "REFUSED": 3,
    "UNKNOWN": 4,
    "WORKER_NOT_COMPLETE": 5,
    "NO_REPORT": 6,
}

_CONTRACT_RUNTIMES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "contract", "runtimes")


def read_directive(value):
    """Text, `@path`, or `-` for stdin. A shell is what a caller has."""
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        with open(value[1:], encoding="utf-8") as handle:
            return handle.read()
    return value


def load_registry(runtime_id, *, registry_path=None):
    """Register every declaration that will register, and report why not.

    Reads the declarations the repo ships unless told otherwise, so a caller
    does not have to assemble a registry to make one dispatch.
    """
    paths = ([registry_path] if registry_path else
             [os.path.join(_CONTRACT_RUNTIMES, n)
              for n in sorted(os.listdir(_CONTRACT_RUNTIMES))
              if n.endswith(".json")])
    registry, refused = {}, []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
        for name, decl in doc.items():
            if name.startswith("_") or not isinstance(decl, dict):
                continue
            if decl.get("runtime_id") != runtime_id:
                continue
            try:
                register(decl, registry)
            except RegistrationRefused as exc:
                refused.append((name, exc.reason))
    return registry, refused


def run(*, directive, runtime_id, ledger_path, dispatch_key=None,
        registry_path=None, drain_budget=300, model=None, work_dir=None,
        run_root=None, grant=DEFAULT_GRANT, out=sys.stdout, err=sys.stderr):
    """H1 through H4. Returns (exit_code, outcome_or_None).

    `grant` names what the dispatched worker is allowed to hold. It is a
    PARAMETER rather than an adapter default so the choice appears at the call
    site and gets recorded in the outcome, and so the CLI and the MCP path can
    differ deliberately instead of by accident.
    """
    if runtime_id not in ADAPTERS:
        print(f"no adapter for runtime {runtime_id!r}; have "
              f"{sorted(ADAPTERS)}", file=err)
        return EXIT["REFUSED"], None

    registry, refused = load_registry(runtime_id, registry_path=registry_path)
    if runtime_id not in registry:
        print(f"runtime {runtime_id!r} has no registrable declaration.", file=err)
        for name, reason in refused:
            print(f"  {name}: {reason}", file=err)
        return EXIT["REFUSED"], None

    ledger_path = os.path.expanduser(ledger_path)
    if not os.path.isabs(ledger_path):
        # Deliberately NOT absolutised: absolutising is what made the Ledger's
        # own refusal unreachable from every surface above it.
        raise ValueError(f"ledger path must be absolute, got {ledger_path!r}")
    base = os.path.dirname(ledger_path)
    work_dir = work_dir or os.path.join(base, "work")
    run_root = run_root or os.path.join(base, "runs")
    os.makedirs(work_dir, exist_ok=True)
    print(f"ledger: {ledger_path}", file=err)

    key = dispatch_key or ("nxb-" + uuid.uuid4().hex[:12])
    units = [{"instruction": directive}]
    try:
        envelope = {
            "dispatch_key": key,
            "runtime_id": runtime_id,
            "declared_count": len(units),
            "declared_digest": digest_units(units),
            "units": units,
            "dispatcher_id": os.environ.get("NXB_DISPATCHER", "nxb-cli"),
        }
    except CanonicalisationError as exc:
        print(f"directive cannot be canonicalised: {exc}", file=err)
        return EXIT["REFUSED"], None

    try:
        kwargs = adapter_kwargs(grant, runtime_id)
    except KeyError as exc:
        print(str(exc), file=err)
        return EXIT["REFUSED"], None
    if model:
        kwargs["model"] = model
    ledger = Ledger(ledger_path)
    try:
        rt = RoundTrip(ledger=ledger, registry=registry,
                       adapter=ADAPTERS[runtime_id](**kwargs),
                       run_root=run_root, work_dir=work_dir)
        # The key is printed BEFORE the work, so a caller whose call is
        # interrupted still knows what to retry with.
        print(f"dispatch_key: {key}", file=err)
        # Visible, not silent. An operator should be able to see what the
        # worker holds without reading code.
        print(f"grant: {grant} — {describe(grant)}", file=err)
        result = rt.dispatch(envelope, drain_budget=drain_budget)

        if result["state"] == "REFUSED":
            print(json.dumps(result, indent=2), file=out)
            print(f"REFUSED: {result.get('reason')}", file=err)
            if result.get("runtime_ref"):
                # RT-2. The child ran. Say so, and say where to read it, rather
                # than leaving an operator with a refusal and no thread.
                print(f"  a child DID run for this key: {result['runtime_ref']}",
                      file=err)
                if result.get("evidence_path"):
                    print(f"  its transcript: {result['evidence_path']}", file=err)
                print("  the dispatch_status field is known to understate this; "
                      "the work is unreachable, not absent.", file=err)
            return EXIT["REFUSED"], None
        if result["state"] != "OBSERVED":
            print(json.dumps(result, indent=2), file=out)
            return EXIT["UNKNOWN"], None

        collected = rt.collect(key)
        outcome = collected.get("outcome")
        if outcome is None:
            print(json.dumps(collected, indent=2), file=out)
            return EXIT["UNKNOWN"], None

        if isinstance(outcome, dict):
            outcome.setdefault("provenance", {})["grant"] = grant
        h3_validate("outcome", outcome)
        print(json.dumps(outcome, indent=2), file=out)

        if outcome["delivery"] != "REPORT_PRESENT":
            print(f"NO REPORT: {outcome['delivery']} "
                  f"{outcome.get('reason') or ''}".rstrip(), file=err)
            return EXIT["NO_REPORT"], outcome

        report = outcome["report"]
        status = report.get("status")
        # The worker's claim and the broker's delivery are different facts and
        # the exit code keeps them apart: 0 only when the WORKER says COMPLETE.
        print(f"{status}: {report.get('summary')}", file=err)
        if report.get("was_refused"):
            print("worker reports it was REFUSED something. Its effect is "
                  "unverified unless you checked it yourself.", file=err)
        return (EXIT["COMPLETE"] if status == "COMPLETE"
                else EXIT["WORKER_NOT_COMPLETE"]), outcome
    finally:
        ledger.close()
