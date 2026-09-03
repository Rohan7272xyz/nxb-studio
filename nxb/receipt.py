"""Receipt construction. No verdict, ever (F-7).

`digest_units` is deliberately exported: the sender MUST use the same
canonicalisation the broker uses, or F-8 fires on every dispatch for reasons
that have nothing to do with truncation. That shared function is itself a
contract, and it is one the spec did not notice.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CanonicalisationError(ValueError):
    """The payload cannot be put into the published canonical form."""


def _assert_canonicalisable(value, path="units"):
    """Refuse what cannot be canonicalised, rather than encoding it anyway.

    Two things were being digested that should never have been [M: nxb-012].

    N-1: a non-finite float. `json.dumps` leaves `allow_nan=True` by default and
    emits the bare tokens NaN and Infinity, which are NOT JSON. Python reads
    them back because Python is lenient; a conforming parser in any other
    language refuses. The reference was minting receipts over bytes no other
    runtime can parse, in a project whose entire purpose is dispatching to
    runtimes that are not Python.

    N-2: a string that is not valid Unicode. An unpaired surrogate is a legal
    Python str, escapes to valid-looking ASCII, and can never be put on a UTF-8
    wire. The reference digested text it could not transmit.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalisationError(
                f"{path} contains a non-finite number ({value!r}); NaN and "
                f"Infinity are not JSON and no conforming parser will read "
                f"them back")
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CanonicalisationError(
                f"{path} contains text that is not valid Unicode and cannot "
                f"be transmitted ({exc.reason})") from exc
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_canonicalisable(key, f"{path}.{key}")
            _assert_canonicalisable(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_canonicalisable(item, f"{path}[{i}]")


def canonical_bytes(units):
    """The one serialisation both sides must agree on. Published in the contract.

    Exactly: refuse anything non-canonicalisable, then JSON with keys sorted,
    no whitespace, non-ASCII escaped, non-finite numbers refused, and the
    result encoded as ASCII. ASCII rather than UTF-8 on purpose: escaping
    leaves no encoding ambiguity for another runtime to get wrong, so the bytes
    are reproducible by anything that can sort keys and escape a string.
    """
    _assert_canonicalisable(units)
    return json.dumps(
        units, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def digest_units(units):
    return hashlib.sha256(canonical_bytes(units)).hexdigest()


def digest_envelope(envelope):
    """Digest of the WHOLE envelope, for repeat-key divergence detection.

    Keyed on everything the dispatcher submitted, not only `units`: a repeat
    that changes `declared_digest` is a different submission and must not be
    answered with the original receipt.
    """
    return hashlib.sha256(canonical_bytes(envelope)).hexdigest()


def render_directive(units):
    """Turn the units into the instruction a runtime actually receives.

    This is the nxb-021 fix for the defect the never-read guard was built for:
    before it, `units` was hashed, counted and refused on, and never reached a
    worker, so F-8 and F-9 guarded a decoy. Now the guarded field IS the
    payload.
    """
    lines = []
    for i, unit in enumerate(units, 1):
        instruction = unit.get("instruction") if isinstance(unit, dict) else None
        if instruction is None:
            instruction = json.dumps(unit, sort_keys=True)
        lines.append(f"{i}. {instruction}" if len(units) > 1 else str(instruction))
    return "\n".join(lines)


def make_receipt(envelope, *, observer):
    """Build a receipt from the envelope WITHOUT interpreting its units.

    Counting the units is a structural operation on the payload's shape.
    Interpreting them is semantic. The receipt does the first and refuses the
    second, which is what makes F-6 satisfiable at all.
    """
    raw = canonical_bytes(envelope["units"])
    return {
        "receipt_id": "rcpt-" + uuid.uuid4().hex,
        "hop": "H1",
        "observed_at": utc_now(),
        "observer": observer,
        "sender_ref": envelope["dispatch_key"],
        "payload_digest": hashlib.sha256(raw).hexdigest(),
        "payload_bytes": len(raw),
        "observed_count": len(envelope["units"]),
        "declared_count": envelope.get("declared_count"),
    }
