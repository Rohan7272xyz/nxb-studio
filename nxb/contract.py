"""The published contract, loaded as data, with the validator generated from it.

This is the nxb-004 finding applied to ourselves: the single most reusable idea
in the old codebase was a test that runs a published contract through the
production validator. Generating the validator from the contract is strictly
stronger than testing for drift, because it makes schema drift impossible
rather than detectable.

What generation CANNOT cover is the invariant list: rules a schema cannot
express (ordering, uniqueness, "this field must never exist"). Those are
hand-enforced, and `tests/test_contract_selfvalidating.py` asserts each one is
actually enforced by code. A documented invariant with no enforcement is
exactly the failure this project exists to stop.
"""

import json
import os

CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "contract", "contract.json",
)


class ContractError(Exception):
    """A payload violated the published contract."""


def _load():
    with open(CONTRACT_PATH, encoding="utf-8") as handle:
        return json.load(handle)


CONTRACT = _load()

_TYPES = {
    "str": str,
    "int": int,
    "list": list,
    "dict": dict,
}


def validate(schema_name, payload):
    """Validate ``payload`` against a published schema. Returns it unchanged.

    The rules come from ``contract.json``, never from a second copy in code.
    """
    try:
        schema = CONTRACT["schemas"][schema_name]
    except KeyError:
        raise ContractError(f"no published schema named {schema_name!r}")

    if not isinstance(payload, dict):
        raise ContractError(f"{schema_name} must be an object")

    for name in schema.get("forbidden_fields", []):
        if name in payload:
            raise ContractError(
                f"{schema_name} must not carry {name!r}: "
                f"forbidden by the published contract"
            )

    for name, rule in schema["fields"].items():
        present = name in payload
        if rule.get("required") and not present:
            raise ContractError(f"{schema_name} is missing required field {name!r}")
        if not present:
            continue
        value = payload[name]
        expected = rule["type"]
        if expected == "nullable":
            pass  # may be None; F-2 is about PRESENCE, not about being set
        elif not isinstance(value, _TYPES[expected]) or isinstance(value, bool):
            raise ContractError(
                f"{schema_name}.{name} must be {expected}, got {type(value).__name__}"
            )
        enum = rule.get("enum")
        if enum is not None and value not in enum:
            raise ContractError(
                f"{schema_name}.{name} must be one of {enum}, got {value!r}"
            )
    return payload


#: Added by nxb-011. contract.json is under blind test by nxb-009 and was not
#: modified; this extension is merged into it when that test reports.
EXTRA_REFUSALS = ["runtime_disproven"]


def refusal_reasons():
    return list(CONTRACT["refusal_vocabulary"]) + EXTRA_REFUSALS


def invariants():
    return list(CONTRACT["invariants"]["items"])
