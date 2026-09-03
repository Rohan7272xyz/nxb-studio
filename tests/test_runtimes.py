"""F-1 and F-2, and the inbox precondition expressed as a registration test."""

import json
import os
import unittest

from nxb.contract import CONTRACT, CONTRACT_PATH, validate
from nxb.runtimes import register, RegistrationRefused

DECLS = json.load(open(os.path.join(os.path.dirname(CONTRACT_PATH),
                                    "runtimes", "claude_code.json"),
                       encoding="utf-8"))


class F1NullStartSignal(unittest.TestCase):
    def test_broker_without_an_inbox_cannot_register_claude_code(self):
        """The inbox is a PRECONDITION for the receipt, not a feature of it.

        Same runtime, same machine, one field different. Without a bound
        socket in the recipient's namespace the runtime cannot tell the broker
        it received anything, so F-1 refuses it. This is nxb-003's defect
        caught on the real runtime by the rule written to catch it.
        """
        with self.assertRaises(RegistrationRefused) as ctx:
            register(DECLS["without_broker_inbox"], {})
        self.assertEqual(ctx.exception.reason, "registration_null_start_signal")

    def test_broker_with_an_inbox_can_register_the_same_runtime(self):
        registry = {}
        register(DECLS["with_broker_inbox"], registry)
        self.assertIn("claude_code", registry)


class F2OmittedField(unittest.TestCase):
    def test_omitting_a_field_is_refused(self):
        decl = dict(DECLS["with_broker_inbox"])
        del decl["cancel"]
        with self.assertRaises(RegistrationRefused) as ctx:
            register(decl, {})
        self.assertEqual(ctx.exception.reason, "registration_omitted_field")

    def test_explicit_null_is_accepted_omission_is_not(self):
        decl = dict(DECLS["with_broker_inbox"])
        decl["cancel"] = None
        register(decl, {})  # explicit null is fine

    def test_null_reasons_distinguish_measured_absent_from_unmeasured(self):
        """Two different states. Collapsing them loses real information.

        This asserted literal per-field values until nxb-029 MEASURED
        `refusal_signal` for claude_code and the field stopped being null. The
        test failed, correctly, and for the wrong reason: it was a second copy
        of the declaration, so a measurement that improved the contract read as
        a regression. Same antipattern as a fixture restating a contract value.

        It now asserts the INVARIANT, which a measurement cannot falsify:
        `_null_reasons` explains exactly the fields that are null, no more and
        no fewer, and every reason names one of the two states. A field that
        goes from null to measured simply drops out of both sets together.
        """
        signals = ("start_signal", "terminal_signal", "refusal_signal")
        for name, decl in DECLS.items():
            if name.startswith("_"):
                continue
            with self.subTest(declaration=name):
                reasons = decl.get("_null_reasons") or {}
                null_fields = {f for f in signals if decl.get(f) is None}
                self.assertEqual(
                    set(reasons), null_fields,
                    f"{name}: _null_reasons must explain exactly the null "
                    f"fields. A null with no reason is the silent capability "
                    f"claim this project exists to stop; a reason for a "
                    f"non-null field is a stale claim about a measured fact.")
                for field, reason in reasons.items():
                    self.assertTrue(
                        reason.startswith(("MEASURED_ABSENT", "UNMEASURED")),
                        f"{name}.{field}: a null must say which state it is "
                        f"in. 'the runtime has none' and 'nobody has looked' "
                        f"are different facts and only one of them is final.")


class RefusalScopeCannotDriftFromTheSignal(unittest.TestCase):
    """The scope list and the prose field must agree about whether there IS one.

    Two hand-written fields describing one fact is a drift hazard, and this
    project has been bitten by a second copy of a declaration before. This binds
    them in the direction that matters: you cannot claim a scope with no signal,
    and you cannot declare a signal and leave its scope unstated.
    """

    def test_scope_and_signal_agree(self):
        from nxb.h3 import REFUSAL_SCOPE, refusal_scope
        for name, decl in DECLS.items():
            if name.startswith("_"):
                continue
            with self.subTest(declaration=name):
                declared = decl.get("_refusal_scope")
                if decl.get("refusal_signal") is None:
                    self.assertIn(
                        declared, (None, []),
                        f"{name}: claims a refusal scope with no refusal_signal")
                else:
                    self.assertTrue(
                        declared,
                        f"{name}: declares a refusal_signal but states no scope, "
                        f"which is the boolean problem returning as a blank")
                for token in declared or []:
                    self.assertIn(
                        token, REFUSAL_SCOPE,
                        f"{name}: {token!r} is not in the closed vocabulary")
                self.assertEqual(refusal_scope(decl), sorted(declared or []))

    def test_no_declaration_claims_the_sandbox_tier(self):
        """MEASURED ABSENT on both runtimes. If this ever fails, someone has
        claimed the thing W3-9 is about, and it needs evidence, not a token."""
        for name, decl in DECLS.items():
            if name.startswith("_"):
                continue
            self.assertNotIn("sandbox", decl.get("_refusal_scope") or [],
                             f"{name} claims the sandbox tier")


class FailClosed(unittest.TestCase):
    def test_no_declaration_carries_the_removed_liveness_field(self):
        """`last_proven_at` was REMOVED in nxb-042, closing C-6.

        This test used to assert the field was present and None on every
        declaration, which made it a reader of a field no production code read:
        the never-read class wearing a test as a disguise. It now asserts the
        opposite, so a declaration that reintroduces the field fails rather than
        quietly reviving an inert one. Liveness is established by a proof over an
        artefact the runtime itself wrote, never by a field in its own
        declaration.
        """
        for name, decl in DECLS.items():
            if name.startswith("_"):
                continue
            with self.subTest(declaration=name):
                self.assertNotIn("last_proven_at", decl)


if __name__ == "__main__":
    unittest.main()
