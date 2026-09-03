"""H2 refusals. The spawn adapter is exercised with a FAKE runtime here; the
real-Codex measurements live in docs/H2-BUILD-REPORT.md and were run by hand,
because a unit test that spends tokens on every run is a test nobody runs.
"""

import os
import shutil
import tempfile
import unittest

from nxb.contract import ContractError
from nxb.dispatch import Broker
from nxb.h2 import SpawnHop, h2_validate, H2_CONTRACT
from nxb.ledger import Ledger
from nxb.receipt import digest_units
from nxb.runtimes import register
from tests.test_dispatch import live_declaration, envelope


class FakeAdapter:
    runtime_id = "codex"
    model = "gpt-5.6-luna"

    def __init__(self, *, started=True, reason=None, elapsed=0.12):
        self._started, self._reason, self._elapsed = started, reason, elapsed
        self.calls = []

    def spawn(self, **kw):
        self.calls.append(kw)
        if not self._started:
            return {"started": False, "reason": self._reason,
                    "thread_id": None,
                    "killed": True, "exit_code": 0, "out_present": False}
        return {"started": True,
                "thread_id": "01a04919-ff28-7cf3-9d6a-025478d79bd4"}


class H2Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = Ledger(os.path.join(self.tmp, "l.db"))
        self.registry = {}
        register(live_declaration(), self.registry)
        self.broker = Broker(self.ledger, registry=self.registry)
        self.accepted = self.broker.dispatch(envelope())["pending_ref"]

    def tearDown(self):
        self.ledger.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hop(self, **kw):
        return SpawnHop(self.ledger, FakeAdapter(**kw))

    def _spawn(self, hop, parent=None):
        return hop.spawn(parent or self.accepted, work_dir=self.tmp,
                         prompt="p", run_dir=os.path.join(self.tmp, "r"),
                         start_timeout=5)


class HappyPath(H2Case):
    def test_started_carries_the_runtimes_own_ref(self):
        out = self._spawn(self.hop())
        self.assertEqual(out["state"], "STARTED")
        self.assertEqual(out["receipt"]["runtime_ref"],
                         "01a04919-ff28-7cf3-9d6a-025478d79bd4")

    def test_h2_receipt_carries_no_verdict(self):
        out = self._spawn(self.hop())
        for forbidden in H2_CONTRACT["schemas"]["h2_receipt"]["forbidden_fields"]:
            self.assertNotIn(forbidden, out["receipt"])

    def test_receipt_chains_to_its_h1_parent(self):
        out = self._spawn(self.hop())
        self.assertEqual(out["receipt"]["parent_receipt_id"], self.accepted)

    def test_pinned_model_is_recorded(self):
        out = self._spawn(self.hop())
        self.assertEqual(out["receipt"]["pinned_model"], "gpt-5.6-luna")


class RefusalsThatSurvived(H2Case):
    def test_a_refused_h1_dispatch_cannot_become_work(self):
        bad = self.broker.dispatch(envelope(dispatch_key="k-bad", declared_count=9))
        out = self._spawn(self.hop(), parent=bad["pending_ref"])
        self.assertEqual(out["state"], "REFUSED")
        self.assertTrue(out["reason"].startswith("parent_not_accepted"))

    def test_unknown_parent_is_refused(self):
        out = self._spawn(self.hop(), parent="rcpt-nope")
        self.assertEqual(out["reason"], "parent_unknown")

    def test_second_spawn_is_refused_not_deduplicated(self):
        hop = self.hop()
        self._spawn(hop)
        out = self._spawn(hop)
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["reason"], "already_spawned")

    def test_no_start_signal_refuses_and_is_recorded(self):
        out = self._spawn(self.hop(started=False,
                                   reason="no_start_signal_within_timeout"))
        self.assertEqual(out["state"], "REFUSED")
        self.assertEqual(out["spawn_status"], "DID_NOT_START")
        row = self.ledger.spawn_for(self.accepted)
        self.assertEqual(row["state"], "REFUSED")

    def test_a_killed_spawn_exiting_zero_is_still_a_failure(self):
        """F-16b. The fake returns exit_code 0, as the real one does after SIGINT."""
        out = self._spawn(self.hop(started=False,
                                   reason="no_start_signal_within_timeout"))
        self.assertEqual(out["state"], "REFUSED")


class AdapterEnforcesMeasuredRules(unittest.TestCase):
    def test_stdin_is_devnull_by_default(self):
        import inspect
        from nxb.adapters.codex import CodexAdapter
        src = inspect.getsource(CodexAdapter.spawn)
        self.assertIn("subprocess.DEVNULL", src)

    def test_the_wait_is_not_a_bare_readline(self):
        """F-15. A timeout checked only between blocking reads cannot fire."""
        import inspect
        from nxb.adapters.codex import CodexAdapter
        src = inspect.getsource(CodexAdapter.spawn)
        self.assertIn("selectors", src)

    def test_nothing_in_nxb_shells_out_to_a_pattern_kill(self):
        """F-15b, learned by doing the damage on 2026-08-28.

        Scans string LITERALS only, skipping docstrings. The first version of
        this test scanned raw text and failed on the comment that explains why
        we never pattern-kill, which is a small live demonstration of why
        grep-shaped checks produce false greens and false reds alike.
        """
        import ast, pathlib
        for path in pathlib.Path("nxb").rglob("*.py"):
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc is not None:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docstrings:
                        continue
                    for bad in ("pkill", "killall"):
                        self.assertNotIn(bad, node.value,
                                         f"{path} pattern-kills at line {node.lineno}")

    def test_model_is_pinned_on_every_command(self):
        from nxb.adapters.codex import CodexAdapter
        cmd = CodexAdapter().build_command(work_dir="/tmp", prompt="p",
                                           out_path="/tmp/o")
        self.assertIn("-m", cmd)
        self.assertIn("gpt-5.6-luna", cmd)


class MeasurementsArePublished(unittest.TestCase):
    def test_the_start_timeout_number_is_recorded_with_its_provenance(self):
        m = H2_CONTRACT["measurements"]
        self.assertIn("_source", m)
        self.assertEqual(m["time_to_thread_started_seconds"]["n"], 7)
        self.assertEqual(m["spec_assumption_A_023_was"], 30)


if __name__ == "__main__":
    unittest.main()
