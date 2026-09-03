"""nxb-049: issued task ids, worker-side validation, and enrolment."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from nxb.enroll import (ENROLLABLE_RUNTIMES, RUNTIME_CANNOT_ENROLL,
                        enroll_command, enrollment_rule)
from nxb.roster import Roster, RosterEntry
from nxb.tasks import (TASK_REVOKED, TASK_UNKNOWN, TASK_VALID,
                       TASK_WRONG_WORKER, TaskRegistry)

_CONTRACT = json.loads(
    (pathlib.Path(__file__).resolve().parent.parent
     / "contract" / "roster.json").read_text())


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = TaskRegistry(os.path.join(self.tmp, "l.db"))
        self.roster = Roster([RosterEntry("/s/1", name="Worker 1", alive=True),
                              RosterEntry("/s/3", name="Worker 3", alive=True)])

    def tearDown(self):
        self.reg.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class IdsAreIssuedNotInvented(Case):
    def test_a_roster_worker_gets_an_id(self):
        task_id, refusal = self.reg.mint("Worker 3", self.roster)
        self.assertIsNone(refusal)
        self.assertTrue(task_id.startswith("nxbt-"))

    def test_an_off_roster_worker_gets_a_REFUSAL_AND_NO_ID(self):
        """TASK-1. The refusal is load-bearing only if no id is issued."""
        task_id, refusal = self.reg.mint("Worker 9", self.roster)
        self.assertIsNone(task_id)
        self.assertEqual(refusal["reason"], "roster_unknown_worker")

    def test_an_empty_roster_issues_nothing(self):
        task_id, refusal = self.reg.mint("Worker 1", Roster([]))
        self.assertIsNone(task_id)

    def test_ids_are_unique(self):
        ids = {self.reg.mint("Worker 1", self.roster)[0] for _ in range(20)}
        self.assertEqual(len(ids), 20)


class TheWorkerValidatesBeforeWorking(Case):
    def test_a_valid_id_for_the_right_worker_passes(self):
        task_id, _ = self.reg.mint("Worker 3", self.roster)
        v = self.reg.validate(task_id, "Worker 3")
        self.assertTrue(v["valid"])
        self.assertEqual(v["verdict"], TASK_VALID)

    def test_an_id_issued_for_ANOTHER_worker_is_refused(self):
        """TASK-2. Minting legitimately for one worker must not authorise
        handing the directive to a different one."""
        task_id, _ = self.reg.mint("Worker 3", self.roster)
        v = self.reg.validate(task_id, "Worker 1")
        self.assertFalse(v["valid"])
        self.assertEqual(v["verdict"], TASK_WRONG_WORKER)
        self.assertIn("REFUSE", v["detail"])

    def test_a_forged_id_is_refused(self):
        v = self.reg.validate("nxbt-madeitup", "Worker 3")
        self.assertFalse(v["valid"])
        self.assertEqual(v["verdict"], TASK_UNKNOWN)

    def test_a_missing_id_is_refused_not_crashed(self):
        for bad in (None, ""):
            with self.subTest(task_id=bad):
                self.assertFalse(self.reg.validate(bad, "Worker 3")["valid"])

    def test_a_revoked_id_is_refused(self):
        task_id, _ = self.reg.mint("Worker 3", self.roster)
        self.reg.revoke(task_id)
        v = self.reg.validate(task_id, "Worker 3")
        self.assertEqual(v["verdict"], TASK_REVOKED)

    def test_every_refusal_tells_the_worker_to_REFUSE(self):
        """TASK-3. No verdict may read as a caveat the worker can continue past."""
        task_id, _ = self.reg.mint("Worker 3", self.roster)
        self.reg.revoke(task_id)
        for v in (self.reg.validate("nope", "Worker 3"),
                  self.reg.validate(task_id, "Worker 3")):
            self.assertIn("REFUSE", v["detail"])

    def test_the_published_vocabulary_covers_every_verdict(self):
        published = set(_CONTRACT["refusal_vocabulary"]) | set(
            _CONTRACT["verdict_vocabulary"])
        for term in (TASK_VALID, TASK_UNKNOWN, TASK_WRONG_WORKER, TASK_REVOKED,
                     RUNTIME_CANNOT_ENROLL):
            self.assertIn(term, published)


class ValidationWorksFromTheCommandLine(Case):
    """The worker's check is a local read, not a message and not a secret."""

    def _validate(self, task_id, worker):
        return subprocess.run(
            [sys.executable, "-m", "nxb", "validate", task_id,
             "--worker", worker, "--ledger", os.path.join(self.tmp, "l.db")],
            capture_output=True, text=True,
            env={"PYTHONPATH": os.getcwd(), "PATH": "/usr/bin:/bin",
                 "PYTHONDONTWRITEBYTECODE": "1"})

    def test_exit_zero_means_proceed_and_nonzero_means_refuse(self):
        task_id, _ = self.reg.mint("Worker 3", self.roster)
        self.assertEqual(self._validate(task_id, "Worker 3").returncode, 0)
        self.assertNotEqual(self._validate(task_id, "Worker 1").returncode, 0)
        self.assertNotEqual(self._validate("nxbt-forged", "Worker 3").returncode, 0)

    def test_one_is_never_used_so_a_shell_cannot_confuse_states(self):
        self.assertNotEqual(self._validate("nxbt-forged", "W").returncode, 1)


class Enrolment(unittest.TestCase):
    def test_the_command_is_one_line_and_pasteable(self):
        """RIG-15 gave this guard teeth it did not have before. `tmux
        send-keys` sends a newline as a KEYSTROKE -- probed: `echo AAA\necho
        BBB` ran the first and stranded the second -- so a multi-line launch
        command types a truncated `claude ... --append-system-prompt 'You are
        the worker...` fragment and then runs the remainder as shell. This
        assertion is the only thing standing between a readable rule and a
        rig that cannot stand up."""
        import tempfile
        cmd, refusal = enroll_command(
            "Worker 3", ledger=os.path.join(tempfile.mkdtemp(), "x.db"),
            repo="/r")
        self.assertIsNone(refusal)
        self.assertEqual(len(cmd.splitlines()), 1)
        self.assertNotIn("\n", cmd)
        self.assertNotIn("'\\''", cmd, "shell escaping makes it unreadable")

    def test_the_validate_command_needs_no_cd_and_no_setup(self):
        """RIG-15. The rule used to name the environment fix in a
        PARENTHESIS -- 'from <repo>, or with PYTHONPATH=<repo>' -- and a Codex
        worker handed that choice fumbled it, hit 'No module named nxb', and
        REFUSED a valid directive. A rule that requires the reader to assemble
        a working command has an assembly step, and an assembly step fails."""
        from nxb.enroll import enrollment_rule
        rule = enrollment_rule("W", ledger="/l/x.db", repo="/r")
        commands = [line.strip() for line in rule.splitlines()
                    if "python3 -m nxb" in line]
        self.assertTrue(commands, "the rule must carry a literal command")
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command.startswith("PYTHONPATH=/r "),
                                "every command must carry its own environment")
                self.assertNotIn(" cd ", command)
                self.assertFalse(command.rstrip().endswith("."),
                                 "a trailing period becomes a shell argument")

    def test_it_binds_both_the_name_and_the_rule(self):
        """The rule now lives in a FILE the command reads. The binding is the
        same; what changed is that its length can no longer break it."""
        import tempfile

        from nxb.enroll import brief_path
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "x.db")
            cmd, _ = enroll_command("Worker 3", ledger=ledger, repo="/r")
            self.assertIn("-n 'Worker 3'", cmd)
            self.assertIn("--append-system-prompt", cmd)
            written = brief_path(ledger, "nxb", "Worker 3")
            self.assertIn(written, cmd, "the command must read the brief")
            with open(written, encoding="utf-8") as handle:
                self.assertIn("You are the worker named Worker 3",
                              handle.read())

    def test_the_launch_command_SURVIVES_A_PTY(self):
        """RIG-19, and it is the reason the rule moved into a file.

        MEASURED: a pty in canonical mode drops input past roughly 1024
        bytes. Probed through send-keys -- 1000 arrived whole, 2000 never
        reached the shell. The inline worker rule was 1014 bytes: TEN of
        headroom, with nothing anywhere saying so, so the next sentence added
        to it would have silently truncated every Claude worker's rule. The
        orchestrator brief at 3891 had already crossed it and its pane
        refused. This asserts the property with room, on BOTH roles, because
        the orchestrator brief is the one that grows."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for role in ("worker", "orchestrator"):
                with self.subTest(role=role):
                    cmd, _ = enroll_command(
                        "Worker 3", ledger=os.path.join(tmp, "x.db"),
                        repo="/r", role=role)
                    self.assertLess(
                        len(cmd.encode()), 512,
                        "a launch command near the pty's ~1024-byte line "
                        "limit is one sentence away from silently truncating "
                        "the rule it exists to bind")

    def test_the_rule_forbids_warning_and_continuing(self):
        """The fail-open shape this project has removed four times."""
        rule = enrollment_rule("Worker 3", ledger="/l/x.db", repo="/r")
        self.assertIn("DO NOT warn and continue", rule)
        self.assertIn("REFUSE", rule)

    def test_the_rule_names_the_worker_and_its_check(self):
        rule = enrollment_rule("Worker 3", ledger="/l/x.db", repo="/r")
        self.assertIn("Worker 3", rule)
        self.assertIn("nxb validate", rule)

    def test_an_unenrollable_runtime_is_REFUSED_not_papered_over(self):
        """ENROL-2. Verified: codex has no --name and no
        --append-system-prompt, so it cannot hold a roster worker."""
        cmd, refusal = enroll_command("W", ledger="/l", repo="/r",
                                      runtime="codex")
        self.assertIsNone(cmd)
        self.assertEqual(refusal["reason"], RUNTIME_CANNOT_ENROLL)
        self.assertIn("codex", refusal["detail"])
        self.assertEqual(refusal["enrollable"], list(ENROLLABLE_RUNTIMES))

    def test_codex_is_not_quietly_enrollable(self):
        self.assertNotIn("codex", ENROLLABLE_RUNTIMES)


if __name__ == "__main__":
    unittest.main()


class TheLedgerIsSaidNotGuessed(unittest.TestCase):
    """NXB_LEDGER makes the command short without inventing a default."""

    def _run(self, argv, env):
        base = {"PYTHONPATH": os.getcwd(), "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1"}
        base.update(env)
        return subprocess.run([sys.executable, "-m", "nxb"] + argv,
                              capture_output=True, text=True, env=base)

    def test_the_env_var_supplies_the_ledger(self):
        r = self._run(["enroll", "Worker 3"],
                      {"NXB_LEDGER": "/tmp/nxb-test/l.db"})
        self.assertEqual(r.returncode, 0, r.stderr)
        # The ledger now reaches the worker through the brief file the
        # command reads, so the path is asserted where it actually lives.
        self.assertIn("/tmp/nxb-test/briefs", r.stdout)

    def test_with_neither_source_it_REFUSES(self):
        r = self._run(["enroll", "Worker 3"], {})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no ledger", r.stderr + r.stdout)

    def test_a_relative_env_ledger_is_still_refused(self):
        """The F3 property is 'nothing resolves against cwd', not 'no env'."""
        r = self._run(["enroll", "Worker 3"], {"NXB_LEDGER": ".nxb/l.db"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("absolute", r.stderr + r.stdout)

    def test_the_printed_rule_embeds_the_RESOLVED_path(self):
        """The worker must not depend on its own environment being set."""
        r = self._run(["enroll", "Worker 3"], {"NXB_LEDGER": "~/x/l.db"})
        self.assertNotIn("NXB_LEDGER", r.stdout)
        brief = r.stdout.split("$(cat '")[1].split("')")[0]
        self.assertTrue(brief.startswith(os.path.expanduser("~/x/")))
        with open(brief, encoding="utf-8") as handle:
            self.assertIn(os.path.expanduser("~/x/l.db"), handle.read())

    def test_dispatch_surfaces_still_REQUIRE_the_flag(self):
        """Regression: `en.add_argument` is a substring of `pen.add_argument`,
        and a blind replace made `pending` accept a missing ledger while its
        handler still dereferenced one."""
        for cmd in (["pending"], ["collect", "k"],
                    ["dispatch", "e.json"], ["run", "--runtime", "codex",
                                             "--directive", "x"]):
            with self.subTest(cmd=cmd[0]):
                r = self._run(cmd, {"NXB_LEDGER": "/tmp/nxb-test/l.db"})
                self.assertIn("--ledger", r.stderr,
                              f"{cmd[0]} stopped requiring --ledger")
