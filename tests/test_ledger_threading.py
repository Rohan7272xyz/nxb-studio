"""The broker is single-threaded BY CONTRACT, and says so in its own words.

[M: nxb-030, re-measured nxb-038] Four dispatchers sharing one Ledger across
threads wrote 0 of 60 receipts and raised sqlite3.ProgrammingError from inside
the driver. The fault is the sharing; the error named sqlite, which sends the
reader to the wrong layer. These tests pin the constraint and the diagnosis.
"""

import os
import sqlite3
import tempfile
import threading
import unittest

from nxb.ledger import Ledger, LedgerThreadError


def _db():
    return os.path.join(tempfile.mkdtemp(), "l.db")


def _in_thread(fn):
    """Run fn on another thread; return ('ok', value) or ('raised', exc)."""
    box = []
    def run():
        try:
            box.append(("ok", fn()))
        except Exception as exc:                               # noqa: BLE001
            box.append(("raised", exc))
    t = threading.Thread(target=run)
    t.start()
    t.join()
    return box[0]


class CrossThreadUseIsRefusedInOurOwnWords(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(_db())

    def test_it_raises_our_error_and_not_a_sqlite_internal(self):
        kind, exc = _in_thread(lambda: self.led.find_by_dispatch_key("k"))
        self.assertEqual(kind, "raised")
        self.assertIsInstance(exc, LedgerThreadError)
        self.assertNotIsInstance(exc, sqlite3.ProgrammingError)

    def test_the_message_names_the_constraint_and_the_remedy(self):
        """An error that says what is wrong and not what to do sends the reader
        looking in the wrong place, which is what the sqlite one did."""
        _, exc = _in_thread(lambda: self.led.find_by_dispatch_key("k"))
        msg = str(exc)
        self.assertIn("single-threaded by contract", msg)
        self.assertIn("per thread", msg)
        self.assertIn(self.led.db_path, msg)

    def test_every_public_method_is_guarded_not_just_the_first_one(self):
        calls = {
            "find_by_dispatch_key": lambda: self.led.find_by_dispatch_key("k"),
            "receipt_state": lambda: self.led.receipt_state("r"),
            "spawn_for": lambda: self.led.spawn_for("r"),
            "disposition_for": lambda: self.led.disposition_for("r"),
            "record_receipt": lambda: self.led.record_receipt(
                {"receipt_id": "r", "sender_ref": "k", "observed_at": "t"},
                runtime_id="x", dispatcher_id="d", now="t"),
            "record_disposition": lambda: self.led.record_disposition(
                "r", "ACCEPTED", None, now="t"),
            "record_spawn": lambda: self.led.record_spawn(
                "r", receipt=None, runtime_id="x", runtime_ref=None,
                state="STARTED", reason=None, now="t"),
        }
        for name, fn in calls.items():
            with self.subTest(method=name):
                kind, exc = _in_thread(fn)
                self.assertEqual(kind, "raised", f"{name} was not guarded")
                self.assertIsInstance(exc, LedgerThreadError)

    def test_the_owning_thread_is_unaffected(self):
        self.assertIsNone(self.led.find_by_dispatch_key("k"))


class OneLedgerPerThreadIsTheSupportedPattern(unittest.TestCase):
    """The constraint has to leave the documented usage working, or it is not a
    constraint, it is a breakage. Two shells sharing a path is the whole reason
    the ledger refuses relative paths."""

    def test_separate_ledgers_on_one_file_still_write(self):
        db = _db()
        Ledger(db).close()                       # create the schema once
        errs, wrote = [], []

        def worker(n):
            try:
                led = Ledger(db)
                for i in range(10):
                    led.record_receipt(
                        {"receipt_id": f"r-{n}-{i}", "sender_ref": f"k-{n}-{i}",
                         "observed_at": "t"},
                        runtime_id="x", dispatcher_id="d", now="t")
                    wrote.append(1)
                led.close()
            except Exception as exc:                           # noqa: BLE001
                errs.append(f"{type(exc).__name__}: {exc}")

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [], "the supported pattern must keep working")
        self.assertEqual(len(wrote), 40)


if __name__ == "__main__":
    unittest.main()
