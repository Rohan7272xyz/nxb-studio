"""The finding ledger: a ratified finding cannot be quietly dropped.

Three parties identified the divergent-repeat defect, it was ratified twice,
and it was converted into work zero times until an operator tripped over it.
Detection was never the bottleneck; the gap between ratification and dispatch
was. This makes that gap structural.

WHAT THIS DELIBERATELY DOES NOT DO: fail because findings are open. Thirty-three
are open right now. A suite that is red for all of them is a suite nobody reads,
which is the muting failure this project has already watched happen to a timer,
an identity alarm and a liveness gate. The asymmetry that saved each of those
applies again: FAIL ON THE UNDECLARED, NOT ON THE UNFINISHED.

So an OPEN finding is a valid resting state, provided it is owned and says what
would close it. What fails the suite is a finding with no state, no owner, no
closing condition, or a record that disagrees with reality.
"""

import json
import pathlib
import unittest

from tests.finding_checks import CHECKS

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LEDGER = _ROOT / "FINDINGS.json"

_STATES = {"OPEN", "FIXED", "WONTFIX", "REVERSED"}
_SEVERITIES = {"high", "medium", "low"}


def _findings():
    return json.loads(_LEDGER.read_text(encoding="utf-8"))["findings"]


#: Values that MEAN "nobody owns this". `"unassigned"` was a sentinel the
#: backlog reporter understood and the owner guard did not, so a finding whose
#: owner field literally said it had no owner PASSED the test whose job is
#: catching findings with no owner: `assertTrue("unassigned")` is True. One
#: module, two notions of the same thing, nothing forcing them to agree, which
#: is the class HANDOFF records at 90f46d4 and which this file exists to enforce.
#:
#: Resolved toward ONE definition rather than two that agree. The sentinel is
#: refused outright: a finding with no owner expresses that by having no `owner`
#: key, which the guard already catches, so the sentinel only ever added a way
#: to defeat it. [nxb-040]
_UNOWNED = frozenset({"", "unassigned", "unowned", "nobody", "none", "tbd"})


def _owner(finding):
    """The real owner, or None. THE definition, used by the guard and the count."""
    owner = finding.get("owner")
    if not isinstance(owner, str) or owner.strip().lower() in _UNOWNED:
        return None
    return owner.strip()


class TheRecordIsComplete(unittest.TestCase):
    """Silence is not a valid state."""

    def setUp(self):
        self.findings = _findings()

    def test_the_ledger_is_not_empty(self):
        self.assertTrue(self.findings, "a ledger with no findings is not running")

    def test_ids_are_unique(self):
        ids = [f["id"] for f in self.findings]
        self.assertEqual(len(ids), len(set(ids)), "duplicate finding ids")

    def test_every_finding_has_a_state_and_a_severity(self):
        for f in self.findings:
            with self.subTest(finding=f["id"]):
                self.assertIn(f.get("state"), _STATES)
                self.assertIn(f.get("severity"), _SEVERITIES)

    def test_every_finding_says_where_it_came_from(self):
        for f in self.findings:
            with self.subTest(finding=f["id"]):
                self.assertTrue(f.get("found_in"), "no originating task")

    def test_every_finding_says_what_would_close_it(self):
        """The anti-drop clause. A finding you cannot close is a complaint."""
        for f in self.findings:
            with self.subTest(finding=f["id"]):
                self.assertGreater(
                    len(f.get("closes_when", "")), 30,
                    f"{f['id']} does not say what fixing it looks like, so it "
                    f"cannot be dispatched as work")

    def test_open_findings_name_an_owner(self):
        for f in self.findings:
            if f["state"] != "OPEN":
                continue
            with self.subTest(finding=f["id"]):
                self.assertIsNotNone(
                    _owner(f),
                    f"{f['id']} is open and belongs to nobody "
                    f"(owner={f.get('owner')!r}). A placeholder naming the "
                    f"absence of an owner is not an owner.")

    def test_fixed_findings_name_where_they_were_fixed(self):
        for f in self.findings:
            if f["state"] != "FIXED":
                continue
            with self.subTest(finding=f["id"]):
                self.assertTrue(f.get("fixed_in"))

    def test_wontfix_or_reversed_carries_a_reason(self):
        """A finding closed without a fix must say why, in both senses:
        WONTFIX means a real thing was deprioritised, REVERSED means the
        finding itself was false. Neither may be silent."""
        for f in self.findings:
            if f["state"] not in ("WONTFIX", "REVERSED"):
                continue
            with self.subTest(finding=f["id"]):
                self.assertGreater(len(f.get("reason", "")), 40)


class TheRecordAgreesWithReality(unittest.TestCase):
    """Both directions. A stale record is as bad as no record."""

    def setUp(self):
        self.findings = _findings()

    def test_every_check_function_is_registered(self):
        """A check defined after the last CHECKS declaration is silently absent.

        `finding_checks.py` re-declares CHECKS after each batch of functions,
        which works today. Worker 1 investigated the pattern and DISPROVED that
        it was currently broken, which was right. The fragility survives that:
        the next person to append a function after the last declaration gets it
        unregistered with no error, and a finding naming an unregistered check
        is a finding whose check NEVER RUNS. That is the muting failure with a
        different carrier, so it is made loud here rather than left latent.
        """
        import inspect

        from tests import finding_checks
        defined = {
            name for name, obj in vars(finding_checks).items()
            if inspect.isfunction(obj) and not name.startswith("_")
            and obj.__module__ == finding_checks.__name__
        }
        self.assertEqual(
            defined - set(CHECKS), set(),
            "these check functions are defined but NOT registered in CHECKS, "
            "so any finding naming them has a check that never runs")

    def test_every_named_check_exists(self):
        for f in self.findings:
            name = f.get("closes_when_check")
            if not name:
                continue
            with self.subTest(finding=f["id"]):
                self.assertIn(name, CHECKS, f"{f['id']} names a missing check")

    def test_no_open_finding_is_already_fixed(self):
        """OPEN + check passes: the record is lying and owes an update."""
        lying = []
        for f in self.findings:
            name = f.get("closes_when_check")
            if not name or f["state"] != "OPEN":
                continue
            if CHECKS[name]():
                lying.append(f["id"])
        self.assertEqual(
            lying, [],
            f"these are recorded OPEN but their closing condition already "
            f"holds: {lying}. Mark them FIXED and name where.")

    def test_no_fixed_finding_has_regressed(self):
        """FIXED + check fails: the fix came undone and nothing said so."""
        regressed = []
        for f in self.findings:
            name = f.get("closes_when_check")
            if not name or f["state"] != "FIXED":
                continue
            if not CHECKS[name]():
                regressed.append(f["id"])
        self.assertEqual(regressed, [],
                         f"fixed findings whose fix no longer holds: {regressed}")


class TheBacklogIsVisible(unittest.TestCase):
    """The count is the finding. Print it every run."""

    def test_report_the_backlog(self):
        findings = _findings()
        opens = [f for f in findings if f["state"] == "OPEN"]
        high = [f for f in opens if f["severity"] == "high"]
        unowned = [f["id"] for f in opens if _owner(f) is None]
        print(f"\n  BACKLOG: {len(opens)} open of {len(findings)} findings; "
              f"{len(high)} high severity; {len(unowned)} unassigned.")
        if high:
            print("  high severity open: " + ", ".join(f["id"] for f in high))
        # Deliberately not an assertion on the count. See the module docstring.
        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
