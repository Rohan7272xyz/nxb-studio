"""The self-validating contract test (nxb-004's finding, applied to us).

Three assertions, from spec R-041. Assertion 2 turned out to be UNNECESSARY in
the form the spec demanded, and the reason is a result in its own right: the
validator is GENERATED from contract.json, so schema drift between code and
document is impossible rather than detectable. Generation beats testing.

What generation cannot cover is the invariant list, so assertion 2 was
repointed at it: every invariant the contract CLAIMS must name code that
enforces it, and the ones that name nothing must say so out loud.
"""

import json
import pathlib
import re
import os
import unittest

from nxb.contract import CONTRACT, CONTRACT_PATH, validate, ContractError
from nxb.receipt import digest_units


_CONTRACT_PATH = pathlib.Path(__file__).resolve().parents[1] / "contract" / "contract.json"


def _enforcement_map():
    path = pathlib.Path(__file__).resolve().parent / "enforcement_map.json"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Assertion1ExamplesValidate(unittest.TestCase):
    """Every published example passes the production validator."""

    def test_every_example_validates(self):
        examples = CONTRACT["examples"]
        self.assertEqual(
            set(examples), set(CONTRACT["schemas"]),
            "every published schema must carry a published example",
        )
        for name, example in examples.items():
            with self.subTest(schema=name):
                payload = dict(example)
                if name == "envelope":
                    payload["declared_digest"] = digest_units(payload["units"])
                validate(name, payload)

    def test_runtime_declarations_validate(self):
        path = os.path.join(os.path.dirname(CONTRACT_PATH),
                            "runtimes", "claude_code.json")
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
        for name, decl in doc.items():
            if name.startswith("_"):
                continue
            with self.subTest(declaration=name):
                validate("capability_declaration", decl)


class Assertion2InvariantsAreEnforced(unittest.TestCase):
    """Every claimed invariant names its enforcement, or admits it has none."""

    def test_each_invariant_names_enforcement(self):
        for item in CONTRACT["invariants"]["items"]:
            with self.subTest(invariant=item["id"]):
                self.assertTrue(item.get("enforced_by"),
                                f"{item['id']} claims a rule with no enforcement named")

    def test_unenforced_invariants_say_so_explicitly(self):
        """A rule with no enforcement must be declared open, not implied."""
        for item in CONTRACT["invariants"]["items"]:
            enforcer = item["enforced_by"]
            if enforcer.startswith("NOTHING"):
                self.assertIn("open", enforcer.lower(),
                              f"{item['id']} is unenforced and must say so")

    def test_named_enforcers_exist(self):
        """The symbol each invariant is bound to must actually import.

        The binding lives in tests/enforcement_map.json, NOT in the contract.
        It used to live in `invariants[].enforced_by`, which meant the published
        contract printed this repository's module and function names. nxb-009
        measured the cost: Codex, asked to implement the contract blind, proposed
        a package named `nxb` with a SQLite ledger keyed on receipt_id before it
        wrote a line, because the contract told it. Every structural convergence
        in that experiment was therefore worthless as evidence. The property is
        worth keeping; publishing it to implementers is not.
        """
        import importlib
        bindings = _enforcement_map()["bindings"]
        for item in CONTRACT["invariants"]["items"]:
            enforcer = bindings.get(item["id"])
            with self.subTest(invariant=item["id"]):
                self.assertIsNotNone(
                    enforcer, f"{item['id']} has no entry in tests/enforcement_map.json")
                if not enforcer.startswith("nxb."):
                    continue
                parts = enforcer.split()[0].split(".")
                for depth in range(len(parts), 1, -1):
                    try:
                        importlib.import_module(".".join(parts[:depth]))
                        break
                    except ModuleNotFoundError:
                        continue
                else:
                    self.fail(f"{item['id']} names {parts}, which does not exist")

    def test_every_invariant_is_bound(self):
        """The map may not silently fall behind the contract."""
        self.assertEqual(
            sorted(_enforcement_map()["bindings"]),
            sorted(i["id"] for i in CONTRACT["invariants"]["items"]),
            "tests/enforcement_map.json and the contract's invariants disagree")


class Assertion2bContractLeaksNoImplementation(unittest.TestCase):
    """The contract must stay implementable by someone who has never seen nxb/.

    A blind-implementation experiment is only evidence if the contract does not
    describe the reference. This test makes that structural instead of a habit.
    """

    #: Tells that name HOW rather than WHAT. Storage engines, language
    #: constructs, module paths, and file extensions.
    _FORBIDDEN = [
        r"\bnxb\.",
        r"\bsqlite\b",
        r"\bPRIMARY KEY\b",
        r"\bUNIQUE constraint\b",
        r"\.py\b",
        r"\bimport time\b",
        r"\bself-validating test\b",
    ]

    def test_contract_names_no_implementation_symbol(self):
        """Sweeps EVERY published contract file, not just contract.json.

        h2.json shipped with the same leak that contract.json did, so scoping
        this to one filename would have caught the leak once and missed its
        successor. Anything a blind implementer would be handed is in scope.
        """
        published = sorted(_CONTRACT_PATH.parent.rglob("*.json"))
        self.assertTrue(published, "no contract files found to sweep")
        for path in published:
            raw = path.read_text(encoding="utf-8")
            for pattern in self._FORBIDDEN:
                with self.subTest(file=path.name, pattern=pattern):
                    hit = re.search(pattern, raw, re.IGNORECASE)
                    self.assertIsNone(
                        hit,
                        f"{path.name} leaks an implementation detail matching "
                        f"{pattern!r}: "
                        f"{raw[max(0, (hit.start() if hit else 0) - 60):(hit.end() + 60) if hit else 0]!r}. "
                        f"State the property that must hold, not where it lives. "
                        f"Symbol bindings belong in tests/enforcement_map.json.")


class Assertion3ForbiddenFieldsAreRefused(unittest.TestCase):
    """F-7 is data in the contract, so the validator must actually refuse it."""

    def test_receipt_refuses_every_forbidden_field(self):
        base = dict(CONTRACT["examples"]["receipt"])
        for name in CONTRACT["schemas"]["receipt"]["forbidden_fields"]:
            with self.subTest(field=name):
                bad = dict(base)
                bad[name] = True
                with self.assertRaises(ContractError):
                    validate("receipt", bad)

    def test_receipt_carries_no_verdict_by_construction(self):
        self.assertIn("ok", CONTRACT["schemas"]["receipt"]["forbidden_fields"])
        self.assertIn("verdict", CONTRACT["schemas"]["receipt"]["forbidden_fields"])




class ExamplesAreStrict(unittest.TestCase):
    """An example may carry ONLY fields its schema defines.

    C6-RESIDUE. Instances are OPEN, by the decision recorded in
    contract.json `_unknown_fields`, and that openness is why removing
    `last_proven_at` from the schema left it sitting in the example with nothing
    to notice: `validate()` accepted the stale field, and would equally have
    accepted one called `totally_invented_field`.

    Examples are the exception. An example is a SPECIMEN of its schema, so a
    field the schema does not define is either a stale leftover or a
    documentation lie, and a reader trusts examples more than prose. The
    contract's example block is also a repeat offender: both blind arms
    independently found it setting bare nulls its own doc forbids, and it then
    outlived a field by one task.

    Sweeps every contract file that carries examples, so an example added to
    h2.json or h3.json is covered without anyone remembering to extend this.
    """

    def _examples(self):
        for path in sorted(_CONTRACT_PATH.parent.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for name, example in (doc.get("examples") or {}).items():
                schema = (doc.get("schemas") or {}).get(name)
                if schema is not None and isinstance(example, dict):
                    yield path.name, name, example, schema

    def test_no_example_carries_a_field_its_schema_does_not_define(self):
        checked = 0
        for filename, name, example, schema in self._examples():
            checked += 1
            undefined = sorted(set(example) - set(schema["fields"]))
            with self.subTest(contract=filename, example=name):
                self.assertFalse(
                    undefined,
                    "%s example %r carries field(s) its schema does not define: "
                    "%s. Either define them or delete them; an example is a "
                    "specimen, not a scratchpad." % (filename, name, undefined))
        self.assertTrue(checked, "found no examples to check, which is itself wrong")

    def test_no_example_carries_a_forbidden_field(self):
        for filename, name, example, schema in self._examples():
            present = sorted(set(example) & set(schema.get("forbidden_fields", [])))
            with self.subTest(contract=filename, example=name):
                self.assertFalse(
                    present,
                    "%s example %r carries forbidden field(s) %s"
                    % (filename, name, present))


class TheRefusalOrderIsTheOrderTheCodeUSES(unittest.TestCase):
    """F-17 publishes an ordering. Nothing checked it against the code.

    Raised as a risk when F-17 was published in nxb-042: an unwritten order is
    what produced C-7 and what both blind arms tripped over, so publishing it was
    the right trade, but it converted silence into a CLAIM and left two things
    that must agree with nothing forcing them to. That is the class nxb-042 spent
    itself eliminating, reintroduced by the same task.

    Behavioural rather than a source scan: each case triggers TWO refusals at
    once and asserts the earlier one wins. A scan would test the file's shape.
    """

    #: DERIVED from F-17's own rule text, never restated. An earlier draft of
    #: this test hardcoded the list, which made it a THIRD copy of the ordering
    #: alongside the contract and the code: exactly the two-sets-must-agree class
    #: nxb-042 spent itself eliminating, reintroduced by the test written to
    #: check it. Reordering F-17 now changes what this expects, so the contract
    #: and the code are bound rather than merely adjacent.
    @property
    def ORDER(self):
        return next(i["order"] for i in CONTRACT["invariants"]["items"]
                    if i["id"] == "F-17")

    def setUp(self):
        from nxb.dispatch import Broker
        from nxb.ledger import Ledger
        from nxb.runtimes import register
        decl = dict(CONTRACT["examples"]["capability_declaration"])
        decl["start_signal"] = "peer_message_status correlated by msg_id"
        registry = {}
        register(decl, registry)
        self.runtime = decl["runtime_id"]
        self.broker = Broker(Ledger(":memory:"), registry=registry)

    def _envelope(self, **over):
        from nxb.receipt import digest_units
        units = over.pop("units", [{"summary": "one unit"}])
        # The digest is taken from `over` if given, and only COMPUTED otherwise.
        # An earlier draft computed it unconditionally and then let the override
        # replace it, so a NaN payload raised inside the fixture before dispatch
        # was ever called, and the failure looked like the code refusing to
        # honour its own published order. It was the test.
        digest = over.pop("declared_digest", None)
        if digest is None:
            digest = digest_units(units)
        env = {"dispatch_key": "order-001", "runtime_id": self.runtime,
               "declared_count": len(units), "declared_digest": digest,
               "units": units, "dispatcher_id": "nxb-044"}
        env.update(over)
        return env

    def test_the_published_order_is_the_order_observed(self):
        """Each case triggers TWO refusals; the winner is DERIVED from F-17.

        The first draft named the expected winner per case, which made the cases
        a FOURTH copy of the ordering after the contract prose, the contract
        array and the code. Proved decorative the same way the REFUSAL_SCOPE
        check was: swapping two entries in the published order left the suite
        green, because nothing in the test consulted it. Now each case declares
        only the PAIR it triggers and the expectation comes from the published
        order, so reordering F-17 changes what this demands of the code.
        """
        order = self.ORDER
        cases = [
            ("NaN payload, and declared_count omitted",
             ("uncanonicalisable_payload", "malformed_envelope"),
             lambda: {k: v for k, v in self._envelope(
                 units=[{"n": float("nan")}], declared_digest="0" * 64,
                 dispatch_key="o-1").items() if k != "declared_count"}),
            ("declared_count omitted, and the runtime is not registered",
             ("malformed_envelope", "runtime_unregistered"),
             lambda: {k: v for k, v in self._envelope(
                 runtime_id="no-such-runtime", dispatch_key="o-2").items()
                 if k != "declared_count"}),
            ("runtime not registered, and the digest is wrong",
             ("runtime_unregistered", "digest_divergence"),
             lambda: self._envelope(runtime_id="no-such-runtime",
                                    declared_digest="0" * 64, dispatch_key="o-3")),
            ("digest wrong, and the count is wrong",
             ("digest_divergence", "count_divergence"),
             lambda: self._envelope(declared_digest="0" * 64, declared_count=99,
                                    dispatch_key="o-4")),
        ]
        for label, pair, build in cases:
            with self.subTest(case=label):
                for reason in pair:
                    self.assertIn(reason, order,
                                  "%r is not in F-17's published order" % reason)
                expected = min(pair, key=order.index)
                out = self.broker.dispatch(build())
                got = str(out.get("reason", "")).split(":", 1)[0].strip()
                self.assertEqual(
                    got, expected,
                    "%s: F-17 publishes %r before %r, so %r should win; the code "
                    "returned %r" % (label, expected,
                                     [r for r in pair if r != expected][0],
                                     expected, got))

    def test_every_reason_in_the_published_order_is_published_vocabulary(self):
        order = self.ORDER
        self.assertEqual(len(order), 7, "F-17's rule text no longer parses into "
                         "seven ordered reasons: %s" % order)
        vocab = set(CONTRACT["refusal_vocabulary"])
        missing = sorted(set(order) - vocab)
        self.assertFalse(
            missing, "F-17 orders reason(s) the vocabulary does not publish: %s"
            % missing)


if __name__ == "__main__":
    unittest.main()
