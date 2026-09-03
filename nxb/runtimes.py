"""Capability declarations and the registration refusals.

F-1: refuse a null ``start_signal``. F-2: refuse an omitted field.
Liveness is NOT decided here. It moved to the proof store in nxb-014, and the
`liveness()` helper that used to live in this module was deleted in nxb-020
once the never-read guard showed its only reader was its own test.
"""

from nxb.contract import validate, ContractError

NULL_STATES = ("MEASURED_ABSENT", "UNMEASURED")


class RegistrationRefused(Exception):
    def __init__(self, reason, detail):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def register(declaration, registry):
    """Register a runtime, or refuse. Returns the stored declaration."""
    try:
        validate("capability_declaration", declaration)
    except ContractError as exc:
        # F-2. An omitted field is a refusal, not a default.
        raise RegistrationRefused("registration_omitted_field", str(exc))

    # F-1. LOAD-BEARING. A runtime that cannot say it received work cannot be
    # dispatched to. Had this existed on 2026-08-27 the browser adapter could
    # not have been registered and seven dispatches would have failed loudly.
    if declaration.get("start_signal") is None:
        raise RegistrationRefused(
            "registration_null_start_signal",
            f"runtime {declaration['runtime_id']!r} declares no start_signal; "
            "it cannot tell the broker it received work",
        )

    registry[declaration["runtime_id"]] = dict(declaration)
    return registry[declaration["runtime_id"]]

