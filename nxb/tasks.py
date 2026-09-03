"""Task ids are ISSUED, not invented, and the worker checks before working.

Measured constraint that produced this shape [nxb-047, re-verified twice]: a
plain process CANNOT send into a live pane. A bare script writing to a session's
socket is HELD for the recipient user's approval, the claimed `from_mode` is
ignored, and the recipient's own mode does not matter. So the broker is not in
the dispatch path and cannot be. The ORCHESTRATOR PANE sends; the broker can
only issue ids, record, and refuse to bless.

Which means the broker cannot PREVENT a dispatch to a worker outside the
roster. Rohan ruled that enforcement moves to the worker: a worker rejects any
task that does not carry a valid broker-issued id.

**Say plainly what that is and is not.** It is cooperation, by a party with
nothing to gain from cheating, which is materially better than an orchestrator
policing itself. It is NOT a security boundary: an orchestrator pane can always
message a worker pane directly, and a worker that ignores its own system prompt
will act on anything. What this removes is DRIFT, not attack. The real boundary
is the transport's own refusal to accept a non-session sender, which is
measured and is not ours.

TWO PROPERTIES THE ID CARRIES:

  1. It exists only if the roster allowed it. Minting runs the roster check, so
     an id is evidence that a human-declared worker was asked for.
  2. It names WHO it is for. Otherwise an orchestrator could mint legitimately
     for Worker 1 and hand the directive to Worker 3.

VALIDATION IS A LOCAL READ, NOT A MESSAGE AND NOT A SECRET. The broker's state
is a file on the same machine, and an enrolled pane is one of the operator's own
full sessions, so it can read it directly. That removes an entire messaging
layer, needs no key to manage, and cannot be spoofed by anything that could not
already write the ledger.
"""

import os
import sqlite3
import uuid

from nxb.receipt import utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issued_tasks (
    task_id     TEXT PRIMARY KEY,
    worker_name TEXT NOT NULL,
    issued_at   TEXT NOT NULL,
    roster_size INTEGER NOT NULL,
    revoked_at  TEXT
);
"""

#: Published verdicts. See contract/roster.json.
TASK_VALID = "task_valid"
TASK_UNKNOWN = "task_unknown_id"
TASK_WRONG_WORKER = "task_wrong_worker"
TASK_REVOKED = "task_revoked"


class TaskRegistry:
    def __init__(self, conn_or_path):
        if isinstance(conn_or_path, str):
            if not os.path.isabs(conn_or_path):
                raise ValueError(
                    f"ledger path must be absolute, got {conn_or_path!r}")
            os.makedirs(os.path.dirname(os.path.abspath(conn_or_path)),
                        exist_ok=True)
            self._conn = sqlite3.connect(conn_or_path)
            self._owns = True
        else:
            self._conn = conn_or_path
            self._owns = False
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------- issuing

    def mint(self, worker_name, roster):
        """Issue a task id for `worker_name`, or return the roster's refusal.

        The refusal is the one already published in nxb-048, now load-bearing:
        no id is issued, so nothing downstream can proceed on it.
        """
        refusal = roster.require_names([worker_name])
        if refusal is not None:
            return None, refusal
        task_id = "nxbt-" + uuid.uuid4().hex[:16]
        self._conn.execute(
            "INSERT INTO issued_tasks (task_id, worker_name, issued_at, "
            "roster_size) VALUES (?,?,?,?)",
            (task_id, worker_name, utc_now(), len(roster)))
        self._conn.commit()
        return task_id, None

    def revoke_many(self, *, task_id=None, worker=None, every=False):
        """Revoke one id, every id for a worker, or all of them.

        THERE WAS NO OPERATOR-FACING WAY TO INVALIDATE A SLIP. `revoke` existed
        in this class and on no command line, so "I am done" left every id ever
        minted permanently valid: 19 of them on 2026-09-03, including ids for
        workers that no longer existed and rigs that had been torn down. A
        permission that outlives its worker, its task and its fleet is a loose
        end with no broom. [RIG-11]

        Returns the ids actually revoked, so revoking nothing is visible rather
        than reported as success.
        """
        if sum(bool(x) for x in (task_id, worker, every)) != 1:
            raise ValueError(
                "revoke exactly one of: a task id, --worker <name>, or --all")
        if task_id:
            rows = self._conn.execute(
                "SELECT task_id FROM issued_tasks WHERE task_id = ? "
                "AND revoked_at IS NULL", (task_id,)).fetchall()
        elif worker:
            rows = self._conn.execute(
                "SELECT task_id FROM issued_tasks WHERE worker_name = ? "
                "AND revoked_at IS NULL", (worker,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT task_id FROM issued_tasks "
                "WHERE revoked_at IS NULL").fetchall()
        ids = [r["task_id"] for r in rows]
        for one in ids:
            self.revoke(one)
        return ids

    def revoke(self, task_id):
        self._conn.execute(
            "UPDATE issued_tasks SET revoked_at = ? WHERE task_id = ? "
            "AND revoked_at IS NULL", (utc_now(), task_id))
        self._conn.commit()

    # ---------------------------------------------------------- validating

    def validate(self, task_id, worker_name):
        """Is this id real, unrevoked, and addressed to THIS worker?

        Returns a verdict dict. Never raises, and never returns a maybe: a
        worker that warns and continues is the fail-open shape this project has
        removed four times.
        """
        row = self._conn.execute(
            "SELECT * FROM issued_tasks WHERE task_id = ?", (task_id,)
        ).fetchone() if task_id else None

        if row is None:
            return {"valid": False, "verdict": TASK_UNKNOWN,
                    "detail": (f"No such task id: {task_id!r}. It was not "
                               f"issued by this broker. REFUSE the directive.")}
        if row["revoked_at"]:
            return {"valid": False, "verdict": TASK_REVOKED,
                    "detail": (f"Task {task_id} was revoked at "
                               f"{row['revoked_at']}. REFUSE the directive.")}
        if row["worker_name"] != worker_name:
            return {"valid": False, "verdict": TASK_WRONG_WORKER,
                    "detail": (f"Task {task_id} was issued for "
                               f"{row['worker_name']!r}, not for "
                               f"{worker_name!r}. REFUSE the directive: an id "
                               f"minted for one worker does not authorise "
                               f"another.")}
        return {"valid": True, "verdict": TASK_VALID, "task_id": task_id,
                "worker_name": worker_name, "issued_at": row["issued_at"],
                "detail": f"Task {task_id} is valid for {worker_name!r}."}

    def close(self):
        if self._owns:
            self._conn.close()
