"""Prove the conformance suite FIRES.

HANDOFF: a guard that has never fired is exactly the false green this project
exists to avoid, and the replacement leak-guard was accepted only after a leak
was reintroduced, the suite was seen to fail, and the leak was removed again.

Doing that by hand proves it once, for whoever ran it. Doing it here proves it
on every run, for every property, forever. Each mutant below violates exactly one
conformance property; the test asserts the suite CATCHES it. A property that
stops catching its own mutant is a property that has quietly become decorative.
"""

import os
import unittest

import pytest

#: Every property here spawns a child and waits on a real deadline, so this
#: module is part of the deliberate slow target. See pytest.ini.
pytestmark = pytest.mark.spawns_children


from nxb.adapters.codex import CodexAdapter
from tests.adapter_conformance import AdapterConformance
from tests.test_adapter_conformance_codex import CodexFixture


def _run(fixture, methods):
    """Run conformance properties against a fixture in ONE class.

    One class means one shared hostile-spawn cache. Running each property in its
    own class re-spawned the same nine runtimes per property, which is the same
    waste the suite itself was carrying and cost 22s here alone.
    """
    case = type("Mutant", (AdapterConformance, unittest.TestCase),
                {"fixture": fixture})
    result = unittest.TextTestRunner(
        stream=open(os.devnull, "w"), verbosity=0
    ).run(unittest.TestSuite([case(m) for m in methods]))
    failed = sorted({str(t).split()[0] for t, _tb in result.failures + result.errors})
    return result.wasSuccessful(), failed


def _run_one(fixture, method):
    return _run(fixture, [method])[0]


class _Mutant(CodexFixture):
    """A fixture whose adapter is broken in exactly one way."""
    cls = None

    def adapter(self, binary=None):
        return self.cls(binary=binary) if binary else self.cls()


class RaisesOnHostileInput(CodexAdapter):
    def spawn(self, **kw):
        raise RuntimeError("this adapter raises instead of refusing")


class RefusesWithoutASayingWhy(CodexAdapter):
    def spawn(self, **kw):
        r = super().spawn(**kw)
        if not r["started"]:
            r["reason"] = ""
        return r


class ReportsEverythingAsATimeout(CodexAdapter):
    def spawn(self, **kw):
        r = super().spawn(**kw)
        if not r["started"]:
            r["reason"] = "no_start_signal_within_timeout"
        return r


class InventsItsOwnVocabulary(CodexAdapter):
    def spawn(self, **kw):
        r = super().spawn(**kw)
        if not r["started"]:
            r["reason"] = "something_went_wrong_probably"
        return r


class TreatsAnExitCodeAsAStart(CodexAdapter):
    def spawn(self, **kw):
        r = super().spawn(**kw)
        if not r["started"] and r.get("exit_code") == 0:
            r["started"], r["thread_id"] = True, "fabricated-from-exit-code"
        return r


class TheGuardFires(unittest.TestCase):
    """Each property must fail on the defect it exists to catch."""

    CASES = [
        ("C2 totality",           RaisesOnHostileInput,
         "test_C2_spawn_returns_for_every_hostile_runtime_and_never_raises"),
        ("C3 refusal carries why", RefusesWithoutASayingWhy,
         "test_C3_spawn_result_carries_what_its_callers_read"),
        ("C5 malformed != timeout", ReportsEverythingAsATimeout,
         "test_C5_a_start_signal_without_an_id_is_not_reported_as_a_timeout"),
        ("C6 exit code is not a start", TreatsAnExitCodeAsAStart,
         "test_C6_an_exit_code_is_never_a_start_signal"),
        ("C11 vocabulary drift",   InventsItsOwnVocabulary,
         "test_C11_every_reason_emitted_is_a_published_one"),
    ]

    def test_every_property_catches_its_own_defect(self):
        for label, cls, method in self.CASES:
            with self.subTest(property=label):
                fixture = _Mutant()
                fixture.cls = cls
                self.assertFalse(
                    _run_one(fixture, method),
                    "%s PASSED against an adapter that violates it: the "
                    "property is decorative" % label)

    def test_the_unmutated_adapter_still_passes_those_same_properties(self):
        """The other half of the proof. A property that fails for everything is
        as useless as one that passes for everything.

        Run as ONE class so the five properties share a single set of hostile
        spawns, which is exactly the sharing the suite itself now does.
        """
        ok, failed = _run(CodexFixture(), [m for _l, _c, m in self.CASES])
        self.assertTrue(
            ok, "these properties catch their mutant but FAIL against the real "
                "adapter, so they fail for everything: %s" % failed)


if __name__ == "__main__":
    unittest.main()
