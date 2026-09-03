"""Durable pending record.

F-10: the primary key is ``receipt_id``, never a task id. [M: nxb-004 measured
the cost of the alternative. The old system registered a directive by task_id
BEFORE spawning, then skipped any directive whose task_id was already recorded,
so a directive that registered and failed to spawn became permanently invisible
after a restart. Vanish point 8.]

F-11: exactly one disposition per receipt, enforced by a UNIQUE constraint
rather than by discipline.

R-051: a repeated ``dispatch_key`` resolves to the ORIGINAL receipt.
"""

import json
import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id    TEXT PRIMARY KEY,
    dispatch_key  TEXT NOT NULL UNIQUE,
    runtime_id    TEXT NOT NULL,
    dispatcher_id TEXT NOT NULL,
    receipt_json  TEXT NOT NULL,
    envelope_digest TEXT,
    state         TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spawns (
    parent_receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id),
    receipt_id        TEXT UNIQUE,
    runtime_id        TEXT NOT NULL,
    runtime_ref       TEXT,
    state             TEXT NOT NULL,
    reason            TEXT,
    recorded_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispositions (
    receipt_id    TEXT PRIMARY KEY REFERENCES receipts(receipt_id),
    outcome       TEXT NOT NULL,
    reason        TEXT,
    recorded_at   TEXT NOT NULL
);
"""

#: The states H1 can reach. TERMINAL states beyond ACCEPTED belong to hops we
#: have not built; a record here never reaches them, which is why the sweep in
#: `stale()` reports rather than transitions.
STATES = ("OBSERVED", "ACCEPTED", "REFUSED")


class LedgerThreadError(RuntimeError):
    """A Ledger was used from a thread other than the one that opened it.

    THE BROKER IS SINGLE-THREADED BY CONTRACT. This is a deliberate constraint,
    not an oversight, and this error exists so a caller learns it by being told
    rather than by hitting it. [M: nxb-030, re-measured nxb-038] Four dispatchers
    sharing one Ledger across threads wrote 0 of 60 receipts and raised
    sqlite3.ProgrammingError from inside the sqlite driver, which sends the
    reader to the wrong layer entirely: the fault is the sharing, not sqlite.

    The supported way to dispatch concurrently is one Ledger per thread or per
    process, all pointing at the same absolute path. That is MEASURED to work:
    16 threads with their own Ledgers wrote 800 of 800 with no errors. It is not
    unconditionally safe at any volume; see CONC-2 in FINDINGS.json.
    """


class Ledger:
    def __init__(self, db_path):
        # F3, nxb-021. The old default was ./.nxb/ledger.db: hidden, gitignored
        # and relative to wherever you happened to be standing, so the same
        # dispatch_key was a cached receipt in one directory and a fresh
        # dispatch in another, with nothing saying so. A relative path is now
        # refused rather than silently resolved.
        if db_path != ":memory:" and not os.path.isabs(db_path):
            raise ValueError(
                f"ledger path must be absolute, got {db_path!r}. State that is "
                f"relative to the current directory means two shells disagree "
                f"about whether work already happened.")
        self.db_path = db_path
        if db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        # The thread that opened it owns it. Checked on every use, so the
        # constraint is enforced where it is violated rather than documented
        # somewhere the violator was never going to read.
        self._owner_thread = threading.get_ident()
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _guard(self):
        """Refuse cross-thread use with OUR error, naming OUR constraint."""
        if threading.get_ident() != self._owner_thread:
            raise LedgerThreadError(
                f"this Ledger was opened on thread {self._owner_thread} and is "
                f"being used from thread {threading.get_ident()}. The broker is "
                f"single-threaded by contract. Open one Ledger per thread or "
                f"per process against the same path "
                f"({self.db_path!r}); do not share one object across threads.")

    def find_by_dispatch_key(self, dispatch_key):
        """R-051. Returns the original row for a repeated key, or None."""
        self._guard()
        cur = self._conn.execute(
            "SELECT * FROM receipts WHERE dispatch_key = ?", (dispatch_key,)
        )
        return cur.fetchone()

    def record_receipt(self, receipt, *, runtime_id, dispatcher_id, now,
                       envelope_digest=None):
        self._guard()
        self._conn.execute(
            "INSERT INTO receipts (receipt_id, dispatch_key, runtime_id, "
            "dispatcher_id, receipt_json, envelope_digest, state, observed_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (receipt["receipt_id"], receipt["sender_ref"], runtime_id,
             dispatcher_id, json.dumps(receipt), envelope_digest, "OBSERVED",
             receipt["observed_at"], now),
        )
        self._conn.commit()
        return receipt["receipt_id"]

    def record_disposition(self, receipt_id, outcome, reason, *, now):
        """F-11. The UNIQUE primary key makes a second disposition an error."""
        self._guard()
        self._conn.execute(
            "INSERT INTO dispositions (receipt_id, outcome, reason, recorded_at) "
            "VALUES (?,?,?,?)",
            (receipt_id, outcome, reason, now),
        )
        self._conn.execute(
            "UPDATE receipts SET state = ?, updated_at = ? WHERE receipt_id = ?",
            ("ACCEPTED" if outcome == "ACCEPTED" else "REFUSED", now, receipt_id),
        )
        self._conn.commit()

    def disposition_for(self, receipt_id):
        self._guard()
        cur = self._conn.execute(
            "SELECT * FROM dispositions WHERE receipt_id = ?", (receipt_id,)
        )
        return cur.fetchone()

    def record_spawn(self, parent_receipt_id, *, receipt, runtime_id,
                     runtime_ref, state, reason, now):
        """One spawn per H1 receipt. A second attempt raises, it does not dedup."""
        self._guard()
        self._conn.execute(
            "INSERT INTO spawns (parent_receipt_id, receipt_id, runtime_id, "
            "runtime_ref, state, reason, recorded_at) VALUES (?,?,?,?,?,?,?)",
            (parent_receipt_id, receipt["receipt_id"] if receipt else None,
             runtime_id, runtime_ref, state, reason, now),
        )
        self._conn.commit()

    def spawn_for(self, parent_receipt_id):
        self._guard()
        cur = self._conn.execute(
            "SELECT * FROM spawns WHERE parent_receipt_id = ?", (parent_receipt_id,)
        )
        return cur.fetchone()

    def receipt_state(self, receipt_id):
        self._guard()
        cur = self._conn.execute(
            "SELECT state FROM receipts WHERE receipt_id = ?", (receipt_id,)
        )
        row = cur.fetchone()
        return row["state"] if row else None

    def close(self):
        self._guard()
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
