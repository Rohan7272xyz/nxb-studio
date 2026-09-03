"""H3: worker to broker report.

The broker owns the child's stdout and its `-o` file, so it has CUSTODY of the
report rather than an assertion about it. That is the strongest form of
provenance available on the measured surfaces, and it is why H3 for a spawned
worker is simple where H3 for a session someone else owns would not be.

One thing the spec asked for that CANNOT exist here: an H3 receipt addressed to
its sender. The sender is a one-shot `codex exec` child and it is gone by the
time its report is observed. The receipt is still produced, because it is what
H4 delivers and what the ledger records, but it is addressed to nobody. See the
report for why that is a property of one-shot runtimes and not a gap.
"""

import hashlib
import json
import os
import uuid

from nxb.receipt import utc_now

H3_CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "contract", "h3.json",
)

with open(H3_CONTRACT_PATH, encoding="utf-8") as _h:
    H3_CONTRACT = json.load(_h)

_TYPES = {"str": str, "int": int, "float": float, "list": list, "dict": dict,
          "bool": bool}


def h3_validate(schema_name, payload):
    schema = H3_CONTRACT["schemas"][schema_name]
    if not isinstance(payload, dict):
        raise ValueError(f"{schema_name} must be an object")
    for name in schema.get("forbidden_fields", []):
        if name in payload:
            raise ValueError(f"{schema_name} must not carry {name!r}")
    for name, rule in schema["fields"].items():
        if rule.get("required") and name not in payload:
            raise ValueError(f"{schema_name} missing required {name!r}")
        if name not in payload:
            continue
        value, expected = payload[name], rule["type"]
        if expected == "bool":
            ok = isinstance(value, bool)
        elif expected == "float":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, _TYPES[expected]) and not isinstance(value, bool)
        if not ok:
            raise ValueError(f"{schema_name}.{name} must be {expected}")
        if rule.get("enum") and value not in rule["enum"]:
            raise ValueError(f"{schema_name}.{name} not in {rule['enum']}")
    return payload


def report_json_schema(task_id):
    """Generate Codex's --output-schema FROM the published contract.

    Generation, not a second copy. nxb-006 established that generating a
    validator from a contract beats testing for drift; the same applies to a
    schema handed to a third party.
    """
    fields = H3_CONTRACT["schemas"]["worker_report"]["fields"]
    props, required = {}, []
    jtypes = {"str": "string", "bool": "boolean", "int": "integer"}
    for name, rule in fields.items():
        prop = {"type": jtypes[rule["type"]]}
        if rule.get("enum"):
            prop["enum"] = rule["enum"]
        if name == "task_id":
            prop["const"] = task_id
        props[name] = prop
        if rule.get("required"):
            required.append(name)
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def directive_for(task_id, body):
    """The worker's prompt. Self-contained; it cannot see this conversation."""
    return (
        f"{body}\n\n"
        f"--- NEXUS BRIDGE REPORT CONTRACT ---\n"
        f"When you are done, your final message MUST be a JSON object matching "
        f"the schema you were given. task_id MUST be exactly {task_id!r}.\n"
        f"status is COMPLETE, BLOCKED or FAILED, and it is YOUR claim about "
        f"YOUR work, not about whether the harness ran.\n"
        f"was_refused MUST be true if anything you attempted was blocked by "
        f"your sandbox or permissions, even if you found another way. The "
        f"broker CANNOT see a refusal in the event stream, so this field is "
        f"the only channel it has.\n"
        f"Report what you did not do. An honest BLOCKED is worth more than an "
        f"optimistic COMPLETE.\n"
    )


def collect_report(*, parent_receipt_id, runtime_ref, out_path, terminal,
                   declaration, observer="nxb-broker"):
    """Observe the worker's report. Returns (h3_receipt, outcome_parts).

    Never raises, and never merges the broker's delivery state with the
    worker's claimed status.
    """
    try:
        with open(out_path, "rb") as handle:
            raw = handle.read(1024 * 1024)
    except OSError:
        raw = b""

    receipt = {
        "receipt_id": "h3-" + uuid.uuid4().hex,
        "hop": "H3",
        "parent_receipt_id": parent_receipt_id,
        "observed_at": utc_now(),
        "observer": observer,
        "payload_digest": hashlib.sha256(raw).hexdigest(),
        "payload_bytes": len(raw),
        "runtime_ref": runtime_ref,
    }
    h3_validate("h3_receipt", receipt)

    # The runtime ANNOUNCED its own failure, so say what it said. Inferring
    # "no_output_file" from an absent file is generic and, worse, is only
    # knowable once the whole budget has elapsed; the announcement is specific
    # and arrives in about 0.6s. [M: nxb-022]
    #
    # Guarded on `not raw` deliberately: if a report arrived anyway the runtime
    # recovered from whatever it announced, and the report is the better
    # evidence. An announcement is not permitted to discard a delivered answer.
    announced = terminal.get("announced_failure")
    if announced and not raw:
        return receipt, {"delivery": "RUNTIME_FAILED", "report": None,
                         "reason": announced["reason"]}

    # F-14: the -o file's ABSENCE is a reliable failure signal. Its presence is
    # not a success signal, which is why a present-but-unparseable file is
    # NO_REPORT rather than an error about the broker.
    if not raw:
        return receipt, {"delivery": "NO_REPORT", "report": None,
                         "reason": "no_output_file"}

    if terminal.get("turn_failed") or terminal.get("error"):
        return receipt, {"delivery": "RUNTIME_FAILED", "report": None,
                         "reason": "turn_failed"}

    try:
        report = json.loads(raw.decode("utf-8", "replace"))
        h3_validate("worker_report", report)
    except (ValueError, json.JSONDecodeError) as exc:
        return receipt, {"delivery": "NO_REPORT", "report": None,
                         "reason": f"report_invalid: {exc}"}

    return receipt, {"delivery": "REPORT_PRESENT", "report": report,
                     "reason": None}


#: The closed vocabulary for what a runtime can STRUCTURALLY report about a
#: refusal. Each token was measured, and each says what it does NOT cover.
#:
#: This replaced a boolean. The boolean asked "can this runtime tell us it was
#: blocked?" and answered yes for Claude Code, which is true of its permission
#: layer and false of the case the question was written for. [M: nxb-029]
#: A single flag cannot carry "yes for one kind of refusal, no for the other",
#: and a consumer reading `True` would have believed the stronger claim.
REFUSAL_SCOPE = {
    "harness_mediated":
        "The runtime's OWN permission layer refused a tool call and emitted a "
        "structural event identifying it AS a refusal, independent of what the "
        "model then said. [M: nxb-029/033] Claude Code: system/permission_denied "
        "plus result.permission_denials, survives narration across 3 runs and 2 "
        "tools. Codex: absent.",
    "sandbox":
        "An OS or sandbox refusal of an effect INSIDE a tool the runtime already "
        "permitted is reported as a refusal. MEASURED ABSENT on both runtimes. "
        "This is the case W3-9 was written about and no runtime here covers it.",
}
#
# REMOVED, nxb-034: `opaque_tool_failure` was a third token here and it was a
# category error. The two above are POSITIVE answers about where a refusal was
# refused. That one was a NEGATIVE answer with a consolation prize: the call is
# visible as failed and is explicitly NOT identified as a refusal. Mixing a
# negative into a list of positives made the list non-monotonic and broke the
# emptiness test this function's own docstring blesses, because a runtime whose
# only token was `opaque_tool_failure` gave a truthy scope while naming no
# refusal at all.
#
# The FACT it carried is real and is not lost: Claude Code emits a tool_result
# with is_error true and a non-zero exit where Codex emits no event whatsoever.
# That is about whether a FAILURE IS OBSERVABLE, not about whether a refusal can
# be named, and it belongs on its own axis. It currently lives in prose in the
# declaration's refusal_signal, in W3-9, and in docs/REFUSAL-SIGNAL-nxb-029.md.
# It has no machine-readable home yet ON PURPOSE: see FAILURE-VISIBILITY-HOMELESS
# in FINDINGS.json. Giving it one today would birth a fifth in-code vocabulary
# under the contract embargo, which is the thing that was just ruled against.


def refusal_scope(declaration):
    """WHAT KINDS of refusal can this runtime structurally report?

    Returns a sorted list drawn from REFUSAL_SCOPE. Empty means the runtime can
    report none of them, which is Codex's measured position.

    A property of the RUNTIME, recorded once in provenance, never mixed into an
    individual outcome's `effect`. Conflating them is what built the trap that
    nxb-018 removed: a per-outcome flag that was always true for Codex, wired to
    a refusal, would have refused every Codex result forever.

    **This is RECORDED AND NEVER REFUSED ON.** Nothing in `ratifiable` reads it
    and nothing should. A scope that made an outcome unratifiable because the
    runtime cannot report sandbox refusals would refuse every outcome from every
    runtime measured so far, which is the fourth instance of the pattern this
    project has already caught three times: refuse on VERIFIED FALSE, never on
    CANNOT VERIFY.
    """
    # A scope with no signal behind it is not a scope. Enforced HERE and not
    # only in a test, because two hand-written fields describing one fact drift,
    # and the never-read guard caught that `refusal_signal` had become a field
    # the contract validated and no code consulted.
    if declaration.get("refusal_signal") is None:
        return []
    declared = declaration.get("_refusal_scope") or []
    return sorted(t for t in declared if t in REFUSAL_SCOPE)


#: Ratification, executable rather than prose.
#:
#: The asymmetry that saved F-5, applied here before it ever fired: refuse on
#: VERIFIED FALSE, never on CANNOT VERIFY. UNCHECKED is the honest default and
#: most work has no externally checkable effect, so refusing on it would refuse
#: nearly everything and be switched off.
def ratifiable(outcome):
    """Return (bool, reason). The ONLY effect-based refusal."""
    if outcome.get("delivery") != "REPORT_PRESENT":
        return False, f"delivery is {outcome.get('delivery')}"
    if outcome.get("effect") == "FALSIFIED":
        return False, "effect_falsified"
    report = outcome.get("report") or {}
    if report.get("status") != "COMPLETE":
        return False, f"worker reported {report.get('status')}"
    # UNCHECKED does not refuse. It is recorded, and a reader who needs a
    # verified effect can require effect == VERIFIED themselves.
    return True, None
