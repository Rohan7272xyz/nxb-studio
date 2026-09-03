"""nxb-048: the roster and its refusal.

The refusal is the product, so most of this file is about whether it says
something a human can act on, not merely whether it fires.
"""

import json
import os
import pathlib
import shutil
import socket
import tempfile
import unittest

from nxb.roster import (CREATE_COMMAND, ROSTER_INSUFFICIENT, ROSTER_UNKNOWN_WORKER,
                        ROSTER_UNNAMED, Roster, RosterEntry, discover, probe_alive)

_CONTRACT = json.loads(
    (pathlib.Path(__file__).resolve().parent.parent
     / "contract" / "roster.json").read_text())


def named(*names):
    return Roster([RosterEntry(f"/s/{n}", name=n, alive=True) for n in names])


class LivenessIsAConnect(unittest.TestCase):
    """26 socket files existed and 12 answered. Existence is not liveness."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_listening_socket_is_alive(self):
        path = os.path.join(self.tmp, "live.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)
        try:
            self.assertTrue(probe_alive(path))
        finally:
            srv.close()

    def test_a_socket_file_with_nobody_listening_is_NOT_alive(self):
        """The exact stale case: the file outlives the process."""
        path = os.path.join(self.tmp, "stale.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.close()                      # file remains, listener gone
        self.assertTrue(os.path.exists(path))
        self.assertFalse(probe_alive(path))

    def test_a_missing_path_is_not_alive(self):
        self.assertFalse(probe_alive(os.path.join(self.tmp, "nope.sock")))

    def test_discovery_drops_stale_entries_rather_than_listing_them(self):
        for name in ("a.sock", "b.sock"):
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(os.path.join(self.tmp, name))
            srv.close()
        open(os.path.join(self.tmp, "not-a-socket.txt"), "w").close()
        self.assertEqual(len(discover(socket_dir=self.tmp)), 0)

    def test_discovery_survives_a_missing_directory(self):
        self.assertEqual(len(discover(socket_dir="/nope/nothing/here")), 0)


class TheRefusalIsTheProduct(unittest.TestCase):
    def test_it_names_what_is_missing_and_what_would_fix_it(self):
        r = named("Worker 1", "Worker 2").require(3)
        self.assertEqual(r["reason"], ROSTER_INSUFFICIENT)
        self.assertIn("Worker 1, Worker 2", r["detail"])
        self.assertIn("Missing: 1", r["detail"])
        self.assertEqual(r["remedy"], ["claude --yolo -n 'Worker 3'"])

    def test_it_does_not_fire_when_the_roster_suffices(self):
        self.assertIsNone(named("Worker 1", "Worker 2").require(2))
        self.assertIsNone(named("Worker 1", "Worker 2").require(1))

    def test_asking_for_several_more_yields_a_command_for_each(self):
        r = named("Worker 1").require(3)
        self.assertEqual(len(r["remedy"]), 2)
        self.assertIn("Worker 3", r["remedy"][1])

    def test_an_empty_roster_says_none_rather_than_nothing(self):
        r = Roster([]).require(1)
        self.assertIn("none", r["detail"])
        self.assertEqual(r["available"], 0)

    def test_an_unnamed_roster_says_so_instead_of_listing_addresses(self):
        """ROSTER-3. A socket path is useless to the person who must act."""
        r = Roster([RosterEntry("/tmp/cc-socks/7018.sock", alive=True)]).require(2)
        self.assertIn("UNNAMED", r["detail"])
        self.assertNotIn("/tmp/cc-socks", r["detail"])

    def test_an_absent_named_worker_is_refused_by_name(self):
        r = named("Worker 1", "Worker 2").require_names(["Worker 1", "Worker 5"])
        self.assertEqual(r["reason"], ROSTER_UNKNOWN_WORKER)
        self.assertIn("Worker 5", r["detail"])
        self.assertNotIn("Worker 1:", r["detail"])
        self.assertEqual(r["remedy"], ["claude --yolo -n 'Worker 5'"])

    def test_present_named_workers_are_not_refused(self):
        self.assertIsNone(named("Worker 1", "Worker 2")
                          .require_names(["Worker 2"]))

    def test_naming_a_worker_on_an_unnamed_roster_is_its_own_refusal(self):
        r = Roster([RosterEntry("/s/1", alive=True)]).require_names(["Worker 1"])
        self.assertEqual(r["reason"], ROSTER_UNNAMED)
        self.assertIn("NONE can be named", r["detail"])
        self.assertIn("Worker 1", r["detail"],
                      "must say WHICH request it could not resolve")

    def test_every_refusal_conforms_to_the_published_schema(self):
        schema = _CONTRACT["schemas"]["roster_refusal"]
        cases = [named("Worker 1").require(2),
                 named("Worker 1").require_names(["Worker 9"]),
                 Roster([RosterEntry("/s/1", alive=True)]).require_names(["W"])]
        for r in cases:
            with self.subTest(reason=r["reason"]):
                for field, rule in schema["fields"].items():
                    if rule.get("required"):
                        self.assertIn(field, r)
                for forbidden in schema["forbidden_fields"]:
                    self.assertNotIn(forbidden, r)
                self.assertIn(r["reason"], _CONTRACT["refusal_vocabulary"])


class NoSilentSpawnFallback(unittest.TestCase):
    """ROSTER-2. The convenience is the danger."""

    def test_the_module_offers_no_way_to_create_a_worker(self):
        import inspect

        from nxb import roster
        src = inspect.getsource(roster)
        for banned in ("subprocess", "Popen", "spawn("):
            self.assertNotIn(banned, src,
                             "the roster must refuse, never create")

    def test_the_remedy_is_a_command_for_a_HUMAN_not_an_action(self):
        r = named("Worker 1").require(2)
        self.assertTrue(all(c.startswith("claude ") for c in r["remedy"]))
        self.assertIn("--yolo", CREATE_COMMAND.format(name="x"))


class NamingIsPluggableAndAbsenceIsHonest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(os.path.join(self.tmp, "w.sock"))
        self.srv.listen(1)

    def tearDown(self):
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_name_source_supplies_names(self):
        r = discover(socket_dir=self.tmp, name_source=lambda a: "Worker 1")
        self.assertEqual(r.names, ["Worker 1"])

    def test_without_a_source_the_roster_is_live_and_unnamed(self):
        r = discover(socket_dir=self.tmp)
        self.assertEqual(len(r), 1)
        self.assertEqual(r.named, [])

    def test_a_raising_name_source_leaves_the_entry_unnamed(self):
        def bad(_):
            raise RuntimeError("boom")
        r = discover(socket_dir=self.tmp, name_source=bad)
        self.assertEqual(len(r), 1)
        self.assertIsNone(r.entries[0].name)


if __name__ == "__main__":
    unittest.main()
