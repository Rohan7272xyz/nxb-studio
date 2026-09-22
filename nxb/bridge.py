"""The bridge: two MCP-speaking agents talk through nxb, with no rig. [nxb-080]

WHAT THIS IS FOR
----------------
A rig is the right shape for a programme: named panes, minted ids, a worker
rule, a collector. It is the wrong shape for "ask the other agent a question".
Rohan runs a Claude Code session in a terminal and Codex in its desktop app,
both of which already speak MCP to the same nxb server (`~/.claude.json` and
`~/.codex/config.toml` both point `nxb` at `python3 -m nxb.mcp` with the same
ledger). So the server is the meeting point: an agent JOINS under a name, SENDS
to a name, and reads its INBOX, and the inbox WAITS inside the tool call so
neither agent has to poll.

WHY A TABLE IN THE LEDGER AND NOT A SOCKET
------------------------------------------
Each MCP client spawns its OWN server process over stdio, so two agents are two
processes that share nothing but the disk. The ledger is already the one file
every nxb process agrees on (F3: absolute, no default), so the mailbox lives in
it. sqlite serialises the writers, the reader polls a table on a short
backoff, and nothing needs a daemon.

THE SAME HONESTY RULES AS THE REST OF NXB
-----------------------------------------
- A name is self-declared. The bridge is on one machine and anything that can
  write the ledger is the operator; this is addressing, not authentication.
- A send to a name nobody joined under is REFUSED, and the refusal names who
  is on the bridge. A message that vanishes into a mailbox nobody reads is the
  founding defect of this project wearing a new hat.
- An empty inbox and a failed read never look alike: EMPTY says how long it
  waited; a refusal says why.
- The inbox waits INSIDE the call (nxb-079's rule for `collect`): one tool
  round-trip per wait, not one per poll. Every tool call re-sends the agent's
  whole context.
"""

import datetime
import os
import re
import sqlite3
import time

#: Published refusals. See contract/bridge.json.
BRIDGE_BAD_NAME = "bridge_bad_name"
BRIDGE_UNKNOWN_PEER = "bridge_unknown_peer"
BRIDGE_EMPTY_MESSAGE = "bridge_empty_message"

#: A peer name: printable, no control characters, short enough to type.
_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")

#: How long one inbox call may wait. The cap is below the timeouts MCP
#: clients apply to a tool call (Codex: `tool_timeout_sec` per server, Claude
#: Code: MCP_TOOL_TIMEOUT), so a wait returns EMPTY rather than the client
#: reporting a failed tool. Raise the client's timeout to wait longer.
DEFAULT_WAIT_S = 45
MAX_WAIT_S = 240
_POLL_MIN_S = 1.0
_POLL_MAX_S = 5.0

#: Message size. Not a limit on what agents may say to each other, a limit on
#: what one tool result may put into a context in one go: a 200 KB message is
#: better sent as a file path.
MAX_BODY_CHARS = 64_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bridge_peers (
    name       TEXT PRIMARY KEY,
    runtime    TEXT,
    note       TEXT,
    joined_at  TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bridge_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sender     TEXT NOT NULL,
    recipient  TEXT NOT NULL,
    body       TEXT NOT NULL,
    reply_to   INTEGER,
    sent_at    TEXT NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS bridge_unread
    ON bridge_messages (recipient, read_at);
"""


def _now():
    # Microseconds, so two joins in the same second still order by time.
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="microseconds")


def _age_s(stamp):
    try:
        then = datetime.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return int((datetime.datetime.now(datetime.timezone.utc) - then)
               .total_seconds())


def _refuse(reason, detail, **extra):
    out = {"state": "REFUSED", "reason": reason, "detail": detail}
    out.update(extra)
    return out


class Bridge:
    """The mailbox. One instance per process; the file is the shared state."""

    def __init__(self, ledger):
        if not ledger or not os.path.isabs(os.path.expanduser(str(ledger))):
            raise ValueError("the bridge needs an ABSOLUTE ledger path")
        self.ledger = os.path.expanduser(ledger)
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        self._conn = sqlite3.connect(self.ledger, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------- peers
    def _valid_name(self, name):
        name = " ".join(str(name or "").split())
        return name if _NAME.match(name) else None

    def join(self, name, *, runtime=None, note=None):
        """Announce `name` on the bridge. Idempotent; refreshes last_seen."""
        clean = self._valid_name(name)
        if clean is None:
            return _refuse(BRIDGE_BAD_NAME,
                           "a bridge name is 1 to 64 printable characters.")
        now = _now()
        self._conn.execute(
            "INSERT INTO bridge_peers (name, runtime, note, joined_at, "
            "last_seen) VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "runtime = COALESCE(excluded.runtime, bridge_peers.runtime), "
            "note = COALESCE(excluded.note, bridge_peers.note), "
            "last_seen = excluded.last_seen",
            (clean, runtime, note, now, now))
        self._conn.commit()
        unread = self._unread_count(clean)
        return {"state": "JOINED", "name": clean, "runtime": runtime,
                "unread": unread, "peers": self.peers()["peers"],
                "next": (f"read with inbox(name={clean!r}, wait=...)"
                         if unread else
                         "others address you by this exact name; send to "
                         "one of the peers listed, or wait in your inbox")}

    def leave(self, name):
        clean = self._valid_name(name)
        gone = self._conn.execute(
            "DELETE FROM bridge_peers WHERE name = ?", (clean,)).rowcount
        self._conn.commit()
        return {"state": "LEFT" if gone else "ABSENT", "name": clean,
                "detail": "messages already on the bridge are kept"}

    def peers(self):
        rows = self._conn.execute(
            "SELECT name, runtime, note, joined_at, last_seen "
            "FROM bridge_peers ORDER BY last_seen DESC, name").fetchall()
        return {"state": "PEERS", "count": len(rows), "peers": [
            {"name": r["name"], "runtime": r["runtime"], "note": r["note"],
             "joined_at": r["joined_at"], "last_seen": r["last_seen"],
             "last_seen_age_s": _age_s(r["last_seen"]),
             "unread": self._unread_count(r["name"])}
            for r in rows]}

    def _touch(self, name):
        self._conn.execute(
            "UPDATE bridge_peers SET last_seen = ? WHERE name = ?",
            (_now(), name))

    def _known(self, name):
        return self._conn.execute(
            "SELECT 1 FROM bridge_peers WHERE name = ?", (name,)).fetchone()

    def _unread_count(self, name):
        return self._conn.execute(
            "SELECT COUNT(*) FROM bridge_messages WHERE recipient = ? "
            "AND read_at IS NULL", (name,)).fetchone()[0]

    # ---------------------------------------------------------- messages
    def send(self, sender, recipient, body, *, reply_to=None):
        """Deliver `body` from `sender` to `recipient`. Refuses an unknown
        recipient rather than filing into a mailbox nobody reads."""
        me = self._valid_name(sender)
        to = self._valid_name(recipient)
        if me is None or to is None:
            return _refuse(BRIDGE_BAD_NAME,
                           "sender and recipient are bridge names: 1 to 64 "
                           "printable characters.")
        text = str(body or "")
        if not text.strip():
            return _refuse(BRIDGE_EMPTY_MESSAGE, "the message is empty.")
        if len(text) > MAX_BODY_CHARS:
            return _refuse(BRIDGE_EMPTY_MESSAGE,
                           f"the message is {len(text)} characters; the "
                           f"bridge carries up to {MAX_BODY_CHARS}. Write it "
                           f"to a file and send the path.")
        if not self._known(me):
            # A sender joins by sending: the act names it. Recipients do not
            # get that courtesy, because a message needs a reader.
            self.join(me)
        if not self._known(to):
            names = [p["name"] for p in self.peers()["peers"]]
            return _refuse(BRIDGE_UNKNOWN_PEER,
                           f"nobody has joined the bridge as {to!r}, so this "
                           f"message would have no reader.",
                           peers=names,
                           remedy=["send to one of the names in `peers`",
                                   "or have the other agent call join first"])
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO bridge_messages (sender, recipient, body, reply_to, "
            "sent_at) VALUES (?,?,?,?,?)", (me, to, text, reply_to, now))
        self._touch(me)
        self._conn.commit()
        return {"state": "SENT", "id": cur.lastrowid, "from": me, "to": to,
                "sent_at": now, "chars": len(text),
                "unread_for_recipient": self._unread_count(to),
                "next": (f"wait for the reply with inbox(name={me!r}, "
                         f"wait=...)")}

    def _unread(self, name, limit):
        return self._conn.execute(
            "SELECT id, sender, body, reply_to, sent_at FROM bridge_messages "
            "WHERE recipient = ? AND read_at IS NULL ORDER BY id LIMIT ?",
            (name, int(limit))).fetchall()

    def inbox(self, name, *, wait=0, mark_read=True, limit=50):
        """Unread messages for `name`, WAITING inside the call for the first.

        Returns MESSAGES with the batch, or EMPTY with how long it waited.
        The loop is a table read on a 1 to 5 second backoff: no agent, no
        token, no daemon. `wait` is capped at MAX_WAIT_S so the call returns
        inside an MCP client's tool timeout; call again to keep waiting.
        """
        me = self._valid_name(name)
        if me is None:
            return _refuse(BRIDGE_BAD_NAME,
                           "a bridge name is 1 to 64 printable characters.")
        if not self._known(me):
            self.join(me)
        budget = min(max(0.0, float(wait or 0)), float(MAX_WAIT_S))
        started = time.monotonic()
        deadline = started + budget
        delay = _POLL_MIN_S
        while True:
            rows = self._unread(me, limit)
            if rows:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.6, _POLL_MAX_S)
        waited = round(time.monotonic() - started, 1)
        self._touch(me)
        if not rows:
            self._conn.commit()
            return {"state": "EMPTY", "name": me, "waited_s": waited,
                    "capped_at_s": MAX_WAIT_S if budget >= MAX_WAIT_S else None,
                    "next": "call inbox again to keep waiting; nothing is "
                            "lost by returning"}
        messages = [{"id": r["id"], "from": r["sender"], "body": r["body"],
                     "reply_to": r["reply_to"], "sent_at": r["sent_at"]}
                    for r in rows]
        if mark_read:
            self._conn.execute(
                "UPDATE bridge_messages SET read_at = ? WHERE id IN (%s)"
                % ",".join("?" * len(rows)),
                [_now(), *[r["id"] for r in rows]])
        self._conn.commit()
        return {"state": "MESSAGES", "name": me, "count": len(messages),
                "messages": messages, "waited_s": waited,
                "marked_read": bool(mark_read),
                "next": "reply with send(from=<your name>, to=<from>, "
                        "text=..., reply_to=<id>)"}

    def history(self, a, b, *, limit=50):
        """The conversation between two names, both directions, oldest first.
        Read-only: marks nothing."""
        x, y = self._valid_name(a), self._valid_name(b)
        if x is None or y is None:
            return _refuse(BRIDGE_BAD_NAME,
                           "both names must be bridge names.")
        rows = self._conn.execute(
            "SELECT id, sender, recipient, body, reply_to, sent_at, read_at "
            "FROM bridge_messages WHERE (sender = ? AND recipient = ?) OR "
            "(sender = ? AND recipient = ?) ORDER BY id DESC LIMIT ?",
            (x, y, y, x, int(limit))).fetchall()
        return {"state": "HISTORY", "between": [x, y], "count": len(rows),
                "messages": [
                    {"id": r["id"], "from": r["sender"], "to": r["recipient"],
                     "body": r["body"], "reply_to": r["reply_to"],
                     "sent_at": r["sent_at"], "read": r["read_at"] is not None}
                    for r in reversed(rows)]}
