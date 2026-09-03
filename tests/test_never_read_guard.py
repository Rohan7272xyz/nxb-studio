"""The never-read guard.

A field that is carried, validated and guarded but never READ is a guard that
guards nothing. `units` was exactly that, and no test, audit, hostile input,
differential run or property sweep in this project found it.

The guard reads every published contract, extracts every field name, and finds
where that name is READ in `nxb/`. A read is a subscript with a string literal
or a `.get("name")` call, in load context. Writes are not reads: a field
constructed into a dict and never consumed is the whole defect class.

Three things make it an instrument rather than a grep:

1. **Guard-only reads do not count.** A field read solely by receipt
   construction, digest computation or a schema validator is being hashed and
   checked, not used. That distinction is what catches `units`, whose only
   reader is `make_receipt`.
2. **Wholesale delivery counts as a read.** A schema whose instances are
   returned to a caller as a whole dict does not need a literal read per field.
   Those schemas are declared in the waiver file, and declaring one is a claim
   that its instances really do reach a caller.
3. **Waivers expire.** A waiver for a field that IS read is stale and fails, so
   the file cannot silently accumulate exemptions for problems already fixed.
"""

import ast
import json
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_NXB = _ROOT / "nxb"
_CONTRACTS = sorted((_ROOT / "contract").glob("*.json"))

#: Functions whose reads are machinery, not use. A field read only here is
#: being hashed, counted or type-checked, which is not the same as consumed.
_GUARD_FUNCS = {
    "validate", "h2_validate", "h3_validate",
    "make_receipt", "digest_units", "canonical_bytes",
    "report_json_schema",
}


def _waivers():
    with open(_ROOT / "tests" / "never_read_waivers.json", encoding="utf-8") as h:
        return json.load(h)


class _ReadFinder(ast.NodeVisitor):
    """Collect (field_name -> {enclosing function}) for LOAD-context reads."""

    def __init__(self):
        self.reads = {}
        self._fn = ["<module>"]

    def visit_FunctionDef(self, node):
        self._fn.append(node.name)
        self.generic_visit(node)
        self._fn.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _record(self, name):
        self.reads.setdefault(name, set()).add(self._fn[-1])

    def visit_Subscript(self, node):
        if (isinstance(node.ctx, ast.Load)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            self._record(node.slice.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            self._record(node.args[0].value)
        self.generic_visit(node)


def _reads_in_nxb():
    found = {}
    for path in sorted(_NXB.rglob("*.py")):
        finder = _ReadFinder()
        finder.visit(ast.parse(path.read_text(encoding="utf-8")))
        for name, fns in finder.reads.items():
            found.setdefault(name, set()).update(fns)
    return found


def _contract_fields():
    out = []
    for path in _CONTRACTS:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for schema, body in doc.get("schemas", {}).items():
            for field in body.get("fields", {}):
                out.append((schema, field))
    return out


def _classify():
    """Return {(schema, field): verdict} for every published contract field."""
    reads = _reads_in_nxb()
    verdicts = {}
    for schema, field in _contract_fields():
        sites = reads.get(field, set())
        work = sites - _GUARD_FUNCS
        if not sites:
            verdicts[(schema, field)] = "NEVER_READ"
        elif not work:
            verdicts[(schema, field)] = "GUARD_ONLY"
        else:
            verdicts[(schema, field)] = "READ"
    return verdicts


class TheGuard(unittest.TestCase):
    def setUp(self):
        self.verdicts = _classify()
        self.w = _waivers()
        self.wholesale = {k for k in self.w["delivered_wholesale"]
                          if not k.startswith("_")}
        self.field_waivers = {k for k in self.w["field_waivers"]
                              if not k.startswith("_")}
        self.pending = {k for k in self.w["pending_fix"] if not k.startswith("_")}

    def _unexplained(self):
        bad = []
        for (schema, field), verdict in sorted(self.verdicts.items()):
            if verdict == "READ" or schema in self.wholesale:
                continue
            key = f"{schema}.{field}"
            if key in self.field_waivers or key in self.pending:
                continue
            bad.append((key, verdict))
        return bad

    def test_the_guard_finds_something(self):
        """A guard that flags nothing is not running."""
        flagged = [k for k, v in self.verdicts.items() if v != "READ"]
        self.assertTrue(flagged, "no field was flagged; the analysis is broken")

    def test_units_now_reaches_the_worker(self):
        """Was the acceptance test; is now the regression test.

        `units` was GUARD_ONLY: hashed, counted, refused on, never delivered.
        nxb-021 made it the payload. If it ever goes back to GUARD_ONLY the
        digest and count guards are protecting a decoy again.
        """
        self.assertEqual(self.verdicts[("envelope", "units")], "READ")

    def test_no_unwaived_never_read_fields(self):
        bad = self._unexplained()
        self.assertEqual(
            bad, [],
            "fields carried and validated but never read on a path that does "
            f"work: {bad}. Either read them, delete them from the contract, or "
            "waive them in tests/never_read_waivers.json with a reason.")

    def test_waivers_do_not_go_stale(self):
        """A waiver for a field that IS read is a lie the file must not keep."""
        stale = []
        for key in self.field_waivers | self.pending:
            schema, _, field = key.partition(".")
            verdict = self.verdicts.get((schema, field))
            if verdict is None:
                stale.append((key, "no such contract field"))
            elif verdict == "READ":
                stale.append((key, "is read; delete this waiver"))
        self.assertEqual(stale, [], f"stale waivers: {stale}")

    def test_every_waiver_carries_a_reason(self):
        for group in ("field_waivers", "pending_fix"):
            for key, reason in self.w[group].items():
                if key.startswith("_"):
                    continue
                with self.subTest(waiver=key):
                    self.assertGreater(
                        len(reason), 40,
                        f"{key} is waived without a usable reason")

    def test_a_wholesale_schema_claim_is_not_free(self):
        """Marking a schema wholesale claims its instances reach a caller."""
        for schema in self.wholesale:
            with self.subTest(schema=schema):
                self.assertTrue(
                    any(s == schema for s, _ in self.verdicts),
                    f"{schema} is marked delivered_wholesale but is not a "
                    f"published schema")


class TheSecondCatch(unittest.TestCase):
    """What the guard found that it was not written for.

    `capability_declaration` is ten fields of which three are read. One of the
    unread seven is a real defect rather than documentation.
    """

    def setUp(self):
        self.verdicts = _classify()

    def test_start_timeout_is_now_honoured(self):
        """The guard's second catch, now fixed and held fixed.

        nxb-010 measured it and put it in the declaration; the dispatch path
        then ignored it in favour of a default argument, so a runtime declaring
        30 silently got 5. The declaration is the source of truth again.
        """
        self.assertEqual(
            self.verdicts[("capability_declaration", "start_timeout")], "READ")

    def test_most_of_the_capability_declaration_is_unread(self):
        decl = {f: v for (s, f), v in self.verdicts.items()
                if s == "capability_declaration"}
        read = {f for f, v in decl.items() if v == "READ"}
        self.assertLessEqual(
            len(read), 4,
            f"only {sorted(read)} of the declaration is read; if more becomes "
            f"readable, tighten this bound rather than relaxing it")
        self.assertIn("start_signal", read)
        self.assertIn("refusal_signal", read)


# The expectedFailure that tracked `units` lived here. It flipped to an
# unexpected success the moment nxb-021 landed the fix, turning the suite red
# until this class and its waiver were deleted. That is the whole point of
# recording a debt as an expected failure: it cannot be paid quietly, and it
# cannot be left recorded once paid.


if __name__ == "__main__":
    unittest.main()
