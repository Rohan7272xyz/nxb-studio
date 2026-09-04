"""The drift detector, and the guards on the guard.

This file exists because `nxb doctor` is itself a thing that can be wrong, and
it was: its first run reported DRIFT on a marker that was present (it read a
launcher script instead of the native binary) and OK on one that was absent
(assembled at runtime, never a literal). Both answers were wrong, in opposite
directions, from the tool written to catch exactly that.
"""

import os
import tempfile
import unittest

from nxb import doctor


class TheDoctorRuns(unittest.TestCase):
    def test_every_check_returns_a_known_status(self):
        for area, status, detail in doctor.checks():
            with self.subTest(area=area):
                self.assertIn(status, (doctor.OK, doctor.DRIFT,
                                       doctor.ABSENT, doctor.WATCH))
                self.assertTrue(detail, f"{area} said nothing")

    def test_a_heuristic_never_fails_the_run(self):
        """A check that cannot be precise must not redden the report. The
        model-name sweep surfaced `claude-desktop-3p` and `claude-eval-9`,
        neither of which is a model, and a run people stop reading is worth
        nothing."""
        for area, status, _ in doctor.checks():
            if "possible new model" in area:
                self.assertNotEqual(status, doctor.DRIFT)

    def test_it_reads_the_NATIVE_binary_not_a_launcher(self):
        """`which codex` is a JS launcher and the strings live in the native
        binary it shells out to. Reading the launcher is what made this file
        report a false DRIFT."""
        found = doctor._binary("codex")
        if not found:
            self.skipTest("codex is not installed")
        self.assertFalse(found.endswith(".js"),
                         f"still resolving to a launcher: {found}")

    def test_readiness_is_not_claimed_without_booting(self):
        """The only honest test of a screen marker is to boot the thing and
        read the screen. Without --deep it must say so rather than guess."""
        shallow = {area: status for area, status, _ in doctor.checks()}
        self.assertEqual(shallow.get("ready markers"), doctor.WATCH)

    def test_versions_are_recorded_where_a_later_run_can_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "contract"))
            payload = doctor.record(tmp)
            self.assertTrue(os.path.exists(
                os.path.join(tmp, doctor.VERSIONS_FILE)))
            self.assertIn("verified", payload)

    def test_the_flag_check_covers_every_flag_nxb_actually_passes(self):
        """A flag silently dropped by a runtime update is the quietest way
        this breaks, so the list checked must be the list used."""
        import pathlib
        src = (pathlib.Path("nxb/enroll.py").read_text()
               + pathlib.Path("nxb/rig.py").read_text())
        checked = dict(((a, d) for a, _, d in doctor.checks()
                        if a.endswith("flags")))
        blob = " ".join(checked.values())
        for flag in ("--model", "--effort", "--append-system-prompt"):
            with self.subTest(flag=flag):
                if flag in src:
                    self.assertTrue(
                        "still documented" in blob or "no longer" in blob,
                        f"{flag} is passed by nxb and the doctor said nothing")


if __name__ == "__main__":
    unittest.main()
