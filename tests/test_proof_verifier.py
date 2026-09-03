"""nxb-036: the evidence verifier under attacker-supplied input.

Found by a child dispatched through `nxb run`, which is the first time this
project's own product produced a finding against it. Every case here is a
MEASURED defect, not an imagined one.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from nxb.adapters.claude_code import ClaudeCodeAdapter
from nxb.adapters.codex import CodexAdapter
from nxb.proof import EVIDENCE_ROOTS, codex_evidence_verifier as verify

REF = "0031a625-ad3d-4535-8587-a13338d88d8b"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "sessions")
        os.makedirs(self.root)
        self.roots = {"codex": self.root}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, body=None):
        p = os.path.join(self.root, name)
        with open(p, "w") as h:
            h.write(body if body is not None else '{"id":"%s"}\n' % REF)
        return p

    def v(self, path, ref, runtime_id="codex"):
        return verify({"evidence_path": path, "runtime_ref": ref,
                       "runtime_id": runtime_id}, roots=self.roots)


class Proof1Unanchored(Case):
    """A one-character ref verified /etc/hosts, /etc/passwd and /etc/shells.

    Both tests were plain substring containment, so an attacker choosing the
    ref needed no write access and nothing runtime-specific.
    """

    def test_a_short_ref_is_refused_outright(self):
        p = self.write("rollout-o.jsonl", "o\n")
        self.assertFalse(self.v(p, "o"))

    def test_the_measured_system_files_no_longer_verify(self):
        for path, ref in [("/etc/hosts", "o"), ("/etc/passwd", "s"),
                          ("/etc/shells", "e")]:
            with self.subTest(path=path):
                self.assertFalse(verify({"evidence_path": path,
                                         "runtime_ref": ref,
                                         "runtime_id": "codex"}))

    def test_a_ref_that_is_a_substring_but_not_a_token_is_refused(self):
        p = self.write("rollout-%s.jsonl" % REF)
        self.assertFalse(self.v(p, REF[:12]), "matched a prefix, not a token")

    def test_a_path_outside_the_runtime_root_is_refused(self):
        outside = os.path.join(self.tmp, "rollout-%s.jsonl" % REF)
        with open(outside, "w") as h:
            h.write(REF)
        self.assertFalse(self.v(outside, REF))

    def test_an_unknown_runtime_fails_closed(self):
        p = self.write("rollout-%s.jsonl" % REF)
        self.assertFalse(self.v(p, REF, runtime_id="nope"))
        self.assertFalse(self.v(p, REF, runtime_id=None))


class Proof2Toctou(Case):
    """The stat and the open were never tied together."""

    def test_a_fifo_inside_the_root_is_refused_without_hanging(self):
        p = os.path.join(self.root, "rollout-%s.jsonl" % REF)
        os.mkfifo(p)
        code = ("import sys; sys.path.insert(0,%r);"
                "from nxb.proof import codex_evidence_verifier as v;"
                "print(v({'evidence_path':%r,'runtime_ref':%r,"
                "'runtime_id':'codex'}, roots={'codex':%r}))"
                % (os.getcwd(), p, REF, self.root))
        out = subprocess.run([sys.executable, "-c", code], timeout=10,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False")

    def test_the_regular_file_check_is_on_the_opened_descriptor(self):
        """A path check can be raced; a descriptor check cannot."""
        import inspect
        from nxb import proof
        src = inspect.getsource(proof.codex_evidence_verifier)
        self.assertIn("os.fstat(fd)", src)
        self.assertIn("O_NONBLOCK", src)


class Proof3NarrowExcept(Case):
    """os.stat raises ValueError, not OSError, on an embedded NUL."""

    def test_an_embedded_nul_is_refused_not_raised(self):
        self.assertFalse(self.v("/tmp/evidence\x00x", REF))

    def test_a_directory_is_refused(self):
        d = os.path.join(self.root, "rollout-%s.jsonl" % REF)
        os.mkdir(d)
        self.assertFalse(self.v(d, REF))


class GenuineProofsStillVerify(Case):
    def test_a_real_shaped_artefact_verifies(self):
        p = self.write("rollout-2026-08-28T12-00-00-%s.jsonl" % REF)
        self.assertTrue(self.v(p, REF), "a genuine proof stopped verifying")

    def test_the_roots_agree_with_the_adapters(self):
        """EVIDENCE_ROOTS duplicates the adapters' defaults on purpose.

        A second copy of a value is only safe if something asserts the copies
        agree, which is this project's standing rule about test fixtures.
        """
        import inspect
        self.assertIn(EVIDENCE_ROOTS["codex"],
                      inspect.getsource(CodexAdapter.evidence_for))
        self.assertIn(EVIDENCE_ROOTS["claude_code"],
                      inspect.getsource(ClaudeCodeAdapter.evidence_for))


if __name__ == "__main__":
    unittest.main()
