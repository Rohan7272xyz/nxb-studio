"""nxb-080: the bridge. Two MCP agents talk through nxb with no rig."""

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from nxb import bridge as bridge_module
from nxb.bridge import (BRIDGE_BAD_NAME, BRIDGE_EMPTY_MESSAGE,
                        BRIDGE_UNKNOWN_PEER, MAX_BODY_CHARS, MAX_WAIT_S,
                        Bridge)

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "ledger.db")
        self.bridge = Bridge(self.ledger)

    def tearDown(self):
        self.bridge.close()


class JoiningAndPeers(Case):
    def test_join_is_idempotent_and_lists_who_is_there(self):
        a = self.bridge.join("claude-terminal", runtime="claude_code")
        self.assertEqual(a["state"], "JOINED")
        b = self.bridge.join("codex-app", runtime="codex", note="the GUI")
        self.assertEqual([p["name"] for p in b["peers"]][:2],
                         ["codex-app", "claude-terminal"])
        again = self.bridge.join("claude-terminal")
        self.assertEqual(again["state"], "JOINED")
        self.assertEqual(self.bridge.peers()["count"], 2)

    def test_a_bad_name_is_refused(self):
        for bad in ("", "   ", "x" * 65, "a\x00b"):
            with self.subTest(name=bad):
                self.assertEqual(self.bridge.join(bad)["reason"],
                                 BRIDGE_BAD_NAME)

    def test_leaving_keeps_the_messages(self):
        self.bridge.join("a")
        self.bridge.join("b")
        self.bridge.send("a", "b", "hi")
        self.assertEqual(self.bridge.leave("b")["state"], "LEFT")
        self.assertEqual(self.bridge.history("a", "b")["count"], 1)


class SendingAndReading(Case):
    def test_a_send_to_nobody_is_REFUSED_and_names_who_is_there(self):
        self.bridge.join("codex-app")
        out = self.bridge.send("claude-terminal", "someone-else", "hello")
        self.assertEqual(out["reason"], BRIDGE_UNKNOWN_PEER)
        self.assertIn("codex-app", out["peers"])
        self.assertIn("claude-terminal", out["peers"],
                      "the sender joined by sending")

    def test_a_message_lands_unread_then_is_read_once(self):
        self.bridge.join("b")
        sent = self.bridge.send("a", "b", "how many files?")
        self.assertEqual(sent["state"], "SENT")
        self.assertEqual(sent["unread_for_recipient"], 1)
        got = self.bridge.inbox("b")
        self.assertEqual(got["state"], "MESSAGES")
        self.assertEqual(got["messages"][0]["from"], "a")
        self.assertEqual(got["messages"][0]["body"], "how many files?")
        self.assertEqual(self.bridge.inbox("b")["state"], "EMPTY")

    def test_mark_read_false_leaves_them_unread(self):
        self.bridge.join("b")
        self.bridge.send("a", "b", "x")
        self.assertEqual(self.bridge.inbox("b", mark_read=False)["count"], 1)
        self.assertEqual(self.bridge.inbox("b")["count"], 1)

    def test_a_reply_carries_the_id_it_answers(self):
        self.bridge.join("a")
        self.bridge.join("b")
        first = self.bridge.send("a", "b", "q")
        self.bridge.send("b", "a", "answer", reply_to=first["id"])
        got = self.bridge.inbox("a")
        self.assertEqual(got["messages"][0]["reply_to"], first["id"])

    def test_empty_and_oversized_messages_are_refused(self):
        self.bridge.join("b")
        self.assertEqual(self.bridge.send("a", "b", "   ")["reason"],
                         BRIDGE_EMPTY_MESSAGE)
        out = self.bridge.send("a", "b", "x" * (MAX_BODY_CHARS + 1))
        self.assertEqual(out["reason"], BRIDGE_EMPTY_MESSAGE)
        self.assertIn("file", out["detail"])

    def test_history_reads_both_directions_oldest_first_and_marks_nothing(self):
        self.bridge.join("a")
        self.bridge.join("b")
        self.bridge.send("a", "b", "1")
        self.bridge.send("b", "a", "2")
        self.bridge.send("a", "b", "3")
        h = self.bridge.history("b", "a")
        self.assertEqual([m["body"] for m in h["messages"]], ["1", "2", "3"])
        self.assertEqual([m["read"] for m in h["messages"]],
                         [False, False, False])
        self.assertEqual(self.bridge.inbox("b")["count"], 2)


class TheInboxWaitsInsideTheCall(Case):
    """nxb-079's rule, applied here: one tool round-trip per wait."""

    def _wait(self, name, wait, *, deliver_on=None):
        sleeps, clock = [], [0.0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
            if deliver_on and len(sleeps) == deliver_on:
                # A SECOND PROCESS writes to the same file: the property the
                # bridge exists for. Two MCP clients are two processes.
                other = Bridge(self.ledger)
                other.send("codex-app", name, "here you go")
                other.close()
        with mock.patch.object(bridge_module.time, "sleep", fake_sleep), \
                mock.patch.object(bridge_module.time, "monotonic",
                                  lambda: clock[0]):
            out = self.bridge.inbox(name, wait=wait)
        return out, sleeps

    def test_a_message_arriving_mid_wait_returns_early(self):
        self.bridge.join("claude-terminal")
        self.bridge.join("codex-app")
        out, sleeps = self._wait("claude-terminal", 45, deliver_on=2)
        self.assertEqual(out["state"], "MESSAGES")
        self.assertEqual(out["messages"][0]["from"], "codex-app")
        self.assertEqual(len(sleeps), 2)
        self.assertLess(out["waited_s"], 45)

    def test_an_empty_wait_says_how_long_it_waited(self):
        self.bridge.join("a")
        out, sleeps = self._wait("a", 30)
        self.assertEqual(out["state"], "EMPTY")
        self.assertEqual(out["waited_s"], 30.0)
        self.assertTrue(sleeps)
        self.assertLessEqual(max(sleeps), 5.0)
        self.assertEqual(sleeps[0], 1.0)

    def test_the_wait_is_capped_below_a_client_timeout(self):
        self.bridge.join("a")
        out, _ = self._wait("a", 10_000)
        self.assertEqual(out["state"], "EMPTY")
        self.assertEqual(out["waited_s"], float(MAX_WAIT_S))
        self.assertEqual(out["capped_at_s"], MAX_WAIT_S)

    def test_no_wait_never_sleeps(self):
        self.bridge.join("a")
        out, sleeps = self._wait("a", 0)
        self.assertEqual(out["state"], "EMPTY")
        self.assertEqual(sleeps, [])


class TwoProcessesShareOneFile(Case):
    def test_a_second_bridge_on_the_same_ledger_sees_the_first(self):
        self.bridge.join("a")
        other = Bridge(self.ledger)
        try:
            other.join("b")
            other.send("b", "a", "from the other process")
        finally:
            other.close()
        got = self.bridge.inbox("a")
        self.assertEqual(got["messages"][0]["body"], "from the other process")
        self.assertEqual({p["name"] for p in self.bridge.peers()["peers"]},
                         {"a", "b"})


class TheBridgeIsOffered(unittest.TestCase):
    def test_the_refusals_are_published(self):
        vocab = json.loads((ROOT / "contract" / "bridge.json").read_text())
        for term in (BRIDGE_BAD_NAME, BRIDGE_UNKNOWN_PEER,
                     BRIDGE_EMPTY_MESSAGE):
            self.assertIn(term, vocab["refusal_vocabulary"])

    def test_the_mcp_server_offers_every_bridge_tool(self):
        from nxb import mcp
        names = {t["name"] for t in mcp._TOOLS}
        for tool in ("nxb_bridge_join", "nxb_bridge_send", "nxb_bridge_inbox",
                     "nxb_bridge_peers", "nxb_bridge_history"):
            self.assertIn(tool, names)
        inbox = next(t for t in mcp._TOOLS if t["name"] == "nxb_bridge_inbox")
        self.assertIn("wait", inbox["inputSchema"]["properties"])
        self.assertIn("WAIT", inbox["description"].upper())

    def test_the_tools_work_end_to_end_through_call_tool(self):
        from nxb import mcp
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ,
                             {mcp.LEDGER_ENV: os.path.join(tmp, "l.db")}):
            def call(tool, **args):
                return json.loads(
                    mcp.call_tool(tool, args)["content"][0]["text"])
            self.assertEqual(call("nxb_bridge_join", name="codex-app",
                                  runtime="codex")["state"], "JOINED")
            sent = call("nxb_bridge_send", sender="claude-terminal",
                        to="codex-app", text="ping")
            self.assertEqual(sent["state"], "SENT")
            got = call("nxb_bridge_inbox", name="codex-app", wait=0)
            self.assertEqual(got["messages"][0]["body"], "ping")
            peers = call("nxb_bridge_peers")
            self.assertEqual(peers["count"], 2)
            hist = call("nxb_bridge_history", a="codex-app",
                        b="claude-terminal")
            self.assertEqual(hist["count"], 1)

    def test_the_cli_speaks_the_same_bridge(self):
        import subprocess
        import sys
        tmp = tempfile.mkdtemp()
        ledger = os.path.join(tmp, "l.db")

        def cli(*args):
            proc = subprocess.run(
                [sys.executable, "-m", "nxb", "bridge", *args,
                 "--ledger", ledger], capture_output=True, text=True,
                cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)))
            return proc.returncode, json.loads(proc.stdout or "{}")
        self.assertEqual(cli("join", "--name", "b")[1]["state"], "JOINED")
        code, out = cli("send", "--from", "a", "--to", "b", "--message", "hi")
        self.assertEqual(out["state"], "SENT")
        code, out = cli("inbox", "--name", "b")
        self.assertEqual(code, 0)
        self.assertEqual(out["messages"][0]["body"], "hi")
        code, out = cli("inbox", "--name", "b")
        self.assertEqual((code, out["state"]), (4, "EMPTY"))


if __name__ == "__main__":
    unittest.main()
