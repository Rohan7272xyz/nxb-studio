"""H4: broker to dispatcher delivery.

Two measured constraints shape this entirely.

**It cannot block.** You cannot block on a peer that is busy doing the work you
gave it; the dispatcher is mid-turn by construction. So H4 is a durable store
plus a collect call, and nothing in it waits.

**A push proves nothing.** [M: nxb-006] `SendMessage` to a peer that
`ListAgents` itself displays as offline returns `success:true` with a msg_id. A
transmission ack is uncorrelated with observation, so an outcome is DELIVERED
only when the dispatcher COLLECTS it. Pushing is a convenience that may raise
the odds of a timely collect; it is never evidence.

**And it has no timer.** The spec wanted an alarm when delivery has not happened
within a budget. No budget has been measured, and this project has now twice
found that machinery justified by an unmeasured constant gets tuned until it
stops firing. So non-delivery is surfaced by a QUERYABLE LIST THAT NEVER CLEARS
ITSELF. `Outbox.pending()` is the alarm. It is inspectable at any time, it costs
nothing when idle, and unlike a timer it cannot be silenced by widening a number.
"""

import json
import sqlite3

from nxb.h3 import h3_validate
from nxb.receipt import utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    dispatch_key      TEXT PRIMARY KEY,
    parent_receipt_id TEXT NOT NULL,
    outcome_json      TEXT NOT NULL,
    recorded_at       TEXT NOT NULL,
    delivered_at      TEXT,
    collect_count     INTEGER NOT NULL DEFAULT 0
);
"""


class Outbox:
    def __init__(self, conn):
        self._conn = conn
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def put(self, outcome):
        """Record an outcome. A DELIVERED ANSWER IS NEVER DOWNGRADED.

        Defence in depth for nxb-031: a later failure under the same key must
        not replace a report that was already produced. The same key means the
        same work, so a second write that carries no report is describing a
        retry of something already answered, not a new fact about it.
        """
        h3_validate("outcome", outcome)
        prior = self.peek(outcome["dispatch_key"])
        if (prior.get("state") != "UNKNOWN_KEY"
                and (prior.get("outcome") or {}).get("delivery") == "REPORT_PRESENT"
                and outcome.get("delivery") != "REPORT_PRESENT"):
            return outcome["dispatch_key"]
        self._conn.execute(
            "INSERT OR REPLACE INTO outbox (dispatch_key, parent_receipt_id, "
            "outcome_json, recorded_at, delivered_at, collect_count) "
            "VALUES (?,?,?,?,"
            "  COALESCE((SELECT delivered_at FROM outbox WHERE dispatch_key=?), NULL),"
            "  COALESCE((SELECT collect_count FROM outbox WHERE dispatch_key=?), 0))",
            (outcome["dispatch_key"], outcome["parent_receipt_id"],
             json.dumps(outcome), utc_now(),
             outcome["dispatch_key"], outcome["dispatch_key"]),
        )
        self._conn.commit()
        return outcome["dispatch_key"]

    def collect(self, dispatch_key):
        """THE H4 receipt. Returns the outcome and marks it delivered.

        Redelivery is on demand: collecting twice returns the same outcome and
        increments a counter, so a dispatcher that lost its context can simply
        ask again. Nothing is consumed by being read.
        """
        row = self._conn.execute(
            "SELECT * FROM outbox WHERE dispatch_key = ?", (dispatch_key,)
        ).fetchone()
        if row is None:
            return {"state": "UNKNOWN_KEY", "dispatch_key": dispatch_key,
                    "reason": "no outcome recorded for this key"}
        self._conn.execute(
            "UPDATE outbox SET delivered_at = COALESCE(delivered_at, ?), "
            "collect_count = collect_count + 1 WHERE dispatch_key = ?",
            (utc_now(), dispatch_key),
        )
        self._conn.commit()
        return {"state": "DELIVERED", "dispatch_key": dispatch_key,
                "outcome": json.loads(row["outcome_json"])}

    def pending(self):
        """Outcomes nobody has collected. This list IS the alarm."""
        return [dict(r) for r in self._conn.execute(
            "SELECT dispatch_key, parent_receipt_id, recorded_at, collect_count "
            "FROM outbox WHERE delivered_at IS NULL ORDER BY recorded_at"
        ).fetchall()]

    def peek(self, dispatch_key):
        """Read WITHOUT marking delivered. For an operator, not a dispatcher."""
        row = self._conn.execute(
            "SELECT * FROM outbox WHERE dispatch_key = ?", (dispatch_key,)
        ).fetchone()
        if row is None:
            return {"state": "UNKNOWN_KEY", "dispatch_key": dispatch_key}
        return {"state": "DELIVERED" if row["delivered_at"] else "PENDING",
                "dispatch_key": dispatch_key,
                "outcome": json.loads(row["outcome_json"])}
