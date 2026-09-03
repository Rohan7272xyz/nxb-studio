"""nxb-049.2: where a worker's NAME comes from, and what is not a name."""

import json
import os
import shutil
import tempfile
import unittest

from nxb.roster import (SESSION_REGISTRY, UNDECLARED_NAME_SOURCES, discover,
                        session_registry_names)


def _record(directory, pid, **fields):
    body = {"pid": pid, "messagingSocketPath": f"/tmp/cc-socks/{pid}.sock"}
    body.update(fields)
    with open(os.path.join(directory, f"{pid}.json"), "w") as handle:
        json.dump(body, handle)


class TheNameSource(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_user_declared_name_is_used(self):
        _record(self.dir, 100, name="Worker 3", nameSource="user")
        self.assertEqual(
            session_registry_names(self.dir)("/tmp/cc-socks/100.sock"),
            "Worker 3")

    def test_a_DERIVED_name_is_not_a_declaration(self):
        """The system naming itself is the opposite of a declared roster."""
        _record(self.dir, 101, name="rohan-7b", nameSource="derived")
        self.assertIsNone(
            session_registry_names(self.dir)("/tmp/cc-socks/101.sock"))

    def test_a_MISSING_nameSource_is_kept(self):
        """Measured: 'Worker 1' has no nameSource because it predates the
        field. Excluding it would refuse a worker that exists."""
        _record(self.dir, 102, name="Worker 1")
        self.assertEqual(
            session_registry_names(self.dir)("/tmp/cc-socks/102.sock"),
            "Worker 1")

    def test_the_binding_is_the_RECORDED_socket_not_the_filename(self):
        _record(self.dir, 103, name="Moved", nameSource="user",
                messagingSocketPath="/tmp/cc-socks/999.sock")
        lookup = session_registry_names(self.dir)
        self.assertEqual(lookup("/tmp/cc-socks/999.sock"), "Moved")
        self.assertIsNone(lookup("/tmp/cc-socks/103.sock"))

    def test_a_half_written_record_names_nobody_and_does_not_raise(self):
        with open(os.path.join(self.dir, "104.json"), "w") as handle:
            handle.write('{"name": "Torn"')
        _record(self.dir, 105, name="Fine", nameSource="user")
        lookup = session_registry_names(self.dir)
        self.assertEqual(lookup("/tmp/cc-socks/105.sock"), "Fine")

    def test_a_missing_registry_yields_no_names_and_does_not_raise(self):
        lookup = session_registry_names(os.path.join(self.dir, "nope"))
        self.assertIsNone(lookup("/tmp/cc-socks/1.sock"))

    def test_secret_key_files_are_NEVER_opened(self):
        """~/.claude/sessions holds <pid>.<hex>.key alongside the records.

        Structural, not a rule to remember: the glob cannot match them. This
        opens the real directory, so a regression is caught against the shape
        that actually exists rather than a fixture that models it.
        """
        opened = []
        real_open = open

        def watched(path, *a, **k):
            opened.append(str(path))
            return real_open(path, *a, **k)

        import builtins
        builtins.open = watched
        try:
            session_registry_names()
        finally:
            builtins.open = real_open
        self.assertTrue(opened, "read nothing at all; the check proves nothing")
        self.assertEqual([p for p in opened if not p.endswith(".json")], [])


class LivenessIsStillAConnect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.socks = tempfile.mkdtemp()

    def tearDown(self):
        for d in (self.dir, self.socks):
            shutil.rmtree(d, ignore_errors=True)

    def _sock(self, pid):
        path = os.path.join(self.socks, f"{pid}.sock")
        open(path, "w").close()
        return path

    def test_a_registry_entry_for_a_DEAD_socket_is_not_on_the_roster(self):
        """ROSTER-1 is unchanged. The registry's own `status` field says
        'idle' for sessions whose socket no longer answers; taking liveness
        from a record of a past state is how 14 dead sockets looked alive."""
        self._sock(200)
        _record(self.dir, 200, name="Ghost", nameSource="user", status="idle")
        roster = discover(socket_dir=self.socks,
                          name_source=session_registry_names(self.dir),
                          prober=lambda address: False)
        self.assertEqual(len(roster), 0)

    def test_a_live_but_undeclared_pane_is_listed_WITHOUT_a_name(self):
        """Never a guessed name: unnamed is honest, invented is not."""
        path = self._sock(201)
        _record(self.dir, 201, name="rohan-cb", nameSource="derived")
        roster = discover(socket_dir=self.socks,
                          name_source=session_registry_names(self.dir),
                          prober=lambda address: True)
        self.assertEqual(len(roster), 1)
        self.assertEqual(roster.names, [])
        self.assertEqual(roster.entries[0].address, path)

    def test_discover_uses_the_registry_by_default(self):
        self.assertIsNotNone(discover.__doc__)
        roster = discover()
        self.assertTrue(
            roster.names,
            "discover() named nobody; the default name source is not wired")


class TheVocabularyOfNotADeclaration(unittest.TestCase):
    def test_derived_is_excluded_and_user_is_not(self):
        self.assertIn("derived", UNDECLARED_NAME_SOURCES)
        self.assertNotIn("user", UNDECLARED_NAME_SOURCES)
        self.assertNotIn(None, UNDECLARED_NAME_SOURCES)

    def test_the_registry_location_is_named_not_inlined(self):
        self.assertIn(".claude", SESSION_REGISTRY)


if __name__ == "__main__":
    unittest.main()
