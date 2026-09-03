"""nxb-045: the MCP server. Protocol and grant, no tokens spent.

The real cross-runtime dispatch through this path (a Claude orchestrator
reaching a Codex worker and getting 437 back) was run by hand and is recorded
in the task report. Tests that spend money on every commit are tests nobody
runs, so what is exercised here is the protocol, the grant plumbing and the
refusals.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from nxb import mcp
from nxb.grants import DEFAULT_GRANT, GRANTS, adapter_kwargs


def rpc(method, params=None, rid=1):
    return mcp.handle({"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}})


class Protocol(unittest.TestCase):
    def test_initialize_reports_a_tools_capability(self):
        r = rpc("initialize")["result"]
        self.assertEqual(r["serverInfo"]["name"], "nxb")
        self.assertIn("tools", r["capabilities"])

    def test_exactly_three_tools_are_offered(self):
        names = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
        self.assertEqual(sorted(names),
                         ["nxb_collect", "nxb_dispatch", "nxb_pending"])

    def test_a_notification_gets_no_response(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0",
                                      "method": "notifications/initialized"}))

    def test_an_unknown_method_is_a_protocol_error(self):
        self.assertEqual(rpc("nope")["error"]["code"], -32601)

    def test_every_tool_publishes_a_schema_with_its_required_fields(self):
        for tool in rpc("tools/list")["result"]["tools"]:
            with self.subTest(tool=tool["name"]):
                self.assertIn("inputSchema", tool)
                self.assertEqual(tool["inputSchema"]["type"], "object")


class LedgerIsRequiredAndAbsolute(unittest.TestCase):
    """F3 survives the transport: there is no shell to pass a flag through, so
    the location comes from the environment and still has NO DEFAULT."""

    def setUp(self):
        self._saved = os.environ.pop(mcp.LEDGER_ENV, None)

    def tearDown(self):
        if self._saved is not None:
            os.environ[mcp.LEDGER_ENV] = self._saved
        else:
            os.environ.pop(mcp.LEDGER_ENV, None)

    def _err(self, params):
        r = rpc("tools/call", params)["result"]
        self.assertTrue(r.get("isError"))
        return r["content"][0]["text"]

    def test_an_unset_ledger_is_a_readable_refusal_not_a_crash(self):
        msg = self._err({"name": "nxb_pending", "arguments": {}})
        self.assertIn(mcp.LEDGER_ENV, msg)

    def test_a_relative_ledger_is_refused(self):
        os.environ[mcp.LEDGER_ENV] = "rel/ledger.db"
        self.assertIn("absolute", self._err({"name": "nxb_pending",
                                             "arguments": {}}))


class Refusals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ[mcp.LEDGER_ENV] = os.path.join(self.tmp, "l.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop(mcp.LEDGER_ENV, None)

    def _call(self, name, args):
        return rpc("tools/call", {"name": name, "arguments": args})["result"]

    def test_a_tool_failure_is_content_not_a_protocol_error(self):
        """The caller is a model and needs to READ what went wrong."""
        r = self._call("nxb_dispatch", {"directive": "x", "runtime": "bogus"})
        self.assertTrue(r["isError"])
        self.assertIn("bogus", r["content"][0]["text"])

    def test_an_empty_directive_is_refused(self):
        r = self._call("nxb_dispatch", {"directive": "", "runtime": "codex"})
        self.assertTrue(r["isError"])

    def test_an_unknown_tool_is_refused_by_name(self):
        r = self._call("nxb_frobnicate", {})
        self.assertTrue(r["isError"])
        self.assertIn("nxb_frobnicate", r["content"][0]["text"])

    def test_collect_on_an_unknown_key_says_so(self):
        r = self._call("nxb_collect", {"dispatch_key": "never-dispatched"})
        self.assertEqual(json.loads(r["content"][0]["text"])["state"],
                         "UNKNOWN_KEY")

    def test_pending_reports_a_count_so_empty_and_firing_differ(self):
        r = self._call("nxb_pending", {})
        self.assertIn("uncollected", json.loads(r["content"][0]["text"]))


class TheGrant(unittest.TestCase):
    """An undecided question gets answered by whoever writes the first line of
    code that depends on it, so the narrow grant is the DEFAULT."""

    def test_the_default_grant_is_the_narrow_one(self):
        kwargs = adapter_kwargs(DEFAULT_GRANT, "claude_code")
        self.assertTrue(kwargs["restricted"])
        self.assertTrue(kwargs["strict_mcp_config"])
        self.assertEqual(adapter_kwargs(DEFAULT_GRANT, "codex")["sandbox"],
                         "read-only")

    def test_widening_is_deliberate_and_named(self):
        self.assertFalse(adapter_kwargs("shell", "claude_code")["restricted"])
        self.assertNotEqual(DEFAULT_GRANT, "shell")

    def test_an_unknown_grant_raises_rather_than_defaulting_open(self):
        with self.assertRaises(KeyError):
            adapter_kwargs("superuser", "claude_code")

    def test_the_tool_publishes_the_grant_choice_to_the_caller(self):
        tool = [t for t in rpc("tools/list")["result"]["tools"]
                if t["name"] == "nxb_dispatch"][0]
        grant = tool["inputSchema"]["properties"]["grant"]
        self.assertEqual(sorted(grant["enum"]), sorted(GRANTS))
        self.assertIn("NO SHELL", grant["description"])

    def test_every_grant_explains_itself(self):
        for name, spec in GRANTS.items():
            with self.subTest(grant=name):
                self.assertGreater(len(spec.get("_doc", "")), 40)

    def test_the_adapter_actually_passes_the_flags(self):
        from nxb.adapters.claude_code import ClaudeCodeAdapter
        cmd = ClaudeCodeAdapter(**adapter_kwargs(DEFAULT_GRANT, "claude_code")
                                ).build_command(work_dir="/tmp", prompt="p",
                                                out_path="/tmp/o")
        self.assertIn("--restricted", cmd)
        self.assertIn("--strict-mcp-config", cmd)


class ServeLoop(unittest.TestCase):
    def test_serve_reads_lines_and_writes_responses(self):
        out = io.StringIO()
        mcp.serve(stdin=io.StringIO(
            '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
            '\n'
            'not json at all\n'
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'), stdout=out)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in lines], [1, 2],
                         "a malformed line must not kill the server")


if __name__ == "__main__":
    unittest.main()


class Grant2FleetContainment(unittest.TestCase):
    """GRANT-2. A child under the narrow grant called ListAgents, enumerated
    eleven live sessions, and EXECUTED SendMessage with zero permission denials.
    Since the operator's fleet runs in bypass mode, any session so messaged acts
    without prompting: a confused-deputy path from an isolated worker into the
    whole fleet."""

    def test_the_fleet_reaching_tools_are_banned_under_every_grant(self):
        from nxb.grants import FLEET_REACHING_TOOLS, GRANTS, adapter_kwargs
        for name in GRANTS:
            with self.subTest(grant=name):
                banned = adapter_kwargs(name, "claude_code")["banned_tools"]
                for tool in ("SendMessage", "ListAgents", "Task"):
                    self.assertIn(tool, banned)
                self.assertEqual(list(banned), FLEET_REACHING_TOOLS)

    def test_toolsearch_is_banned_because_it_is_an_escalation_route(self):
        """It surfaces and makes callable tools that were deferred, which is a
        route back to everything else on the list."""
        from nxb.grants import FLEET_REACHING_TOOLS
        self.assertIn("ToolSearch", FLEET_REACHING_TOOLS)

    def test_the_ban_reaches_the_command_as_bare_names(self):
        """nxb-029: a bare name REMOVES the tool; a scoped form leaves it
        advertised and merely denies the call."""
        from nxb.adapters.claude_code import ClaudeCodeAdapter
        from nxb.grants import adapter_kwargs
        cmd = ClaudeCodeAdapter(**adapter_kwargs("default", "claude_code")
                                ).build_command(work_dir="/tmp", prompt="p",
                                                out_path="/tmp/o")
        i = cmd.index("--disallowedTools")
        self.assertIn("SendMessage", cmd[i + 1:])
        self.assertNotIn("SendMessage(*)", cmd[i + 1:])

    def test_the_read_back_refuses_a_child_that_kept_a_banned_tool(self):
        """The half that matters: a denylist rots OPEN on a future release, so
        the child's own init frame is checked and the dispatch refused."""
        from nxb.adapters.claude_code import ClaudeCodeAdapter
        from nxb.grants import adapter_kwargs
        a = ClaudeCodeAdapter(**adapter_kwargs("default", "claude_code"))
        reason = a._reject_start({"type": "system", "subtype": "init",
                                  "session_id": "s",
                                  "tools": ["Read", "SendMessage"]})
        self.assertIsNotNone(reason)
        self.assertIn("grant_violation", reason)
        self.assertIn("SendMessage", reason)

    def test_a_clean_child_is_accepted(self):
        from nxb.adapters.claude_code import ClaudeCodeAdapter
        from nxb.grants import adapter_kwargs
        a = ClaudeCodeAdapter(**adapter_kwargs("default", "claude_code"))
        self.assertIsNone(a._reject_start(
            {"type": "system", "subtype": "init", "session_id": "s",
             "tools": ["Read", "Write", "Grep"]}))

    def test_an_adapter_with_no_ban_does_not_reject(self):
        from nxb.adapters.claude_code import ClaudeCodeAdapter
        self.assertIsNone(ClaudeCodeAdapter()._reject_start(
            {"type": "system", "subtype": "init", "tools": ["SendMessage"]}))

    def test_the_base_hook_defaults_to_accepting(self):
        """Codex's start frame carries no tool list, so it cannot read back.
        The default must not refuse every runtime that lacks the frame."""
        from nxb.adapters.codex import CodexAdapter
        self.assertIsNone(CodexAdapter()._reject_start({"type": "thread.started"}))
