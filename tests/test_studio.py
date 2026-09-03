"""The studio's HTTP surface. Guards first: this endpoint spawns --yolo agents.

"It is only on localhost" is NOT a boundary. Every page in the operator's
browser can issue requests to 127.0.0.1, so an unguarded endpoint here lets any
website he visits stand up an unsandboxed agent fleet on his machine. These
tests exist to keep that impossible, and they are the reason the token is
mandatory on the PAGE LOAD too rather than only on the API.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from nxb.studio import LOOPBACK, Studio, handler_for


class StudioServed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.studio = Studio(os.path.join(cls.tmp, "l.db"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                         handler_for(cls.studio))
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path, *, token=True, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            req.add_header("X-NXB-Token", self.studio.token)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _post(self, path, payload, *, token=True):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        if token:
            req.add_header("X-NXB-Token", self.studio.token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    # ------------------------------------------------------------- guards
    def test_no_token_is_REFUSED_on_every_route(self):
        for path in ("/", "/api/state"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, token=False)[0], 403)
        self.assertEqual(
            self._post("/api/rig/up", {"session": "x"}, token=False)[0], 403)

    def test_the_PAGE_needs_the_token_too(self):
        """The page carries the token to the browser, so serving it to an
        unauthenticated caller hands over the key."""
        self.assertEqual(self._get("/", token=False)[0], 403)

    def test_a_non_loopback_Host_is_REFUSED(self):
        """DNS rebinding: a stranger's domain resolving to 127.0.0.1 arrives
        with its own Host header, and would otherwise be same-origin."""
        code, _ = self._get("/api/state", host="evil.example.com")
        self.assertEqual(code, 403)

    def test_the_token_is_compared_in_constant_time(self):
        import inspect

        import nxb.studio as studio
        self.assertIn("compare_digest", inspect.getsource(studio.handler_for),
                      "a token compared with == leaks itself one character "
                      "at a time")

    def test_serve_binds_loopback_only(self):
        import inspect

        import nxb.studio as studio
        sig = inspect.signature(studio.serve)
        self.assertEqual(sig.parameters["host"].default, "127.0.0.1",
                         "binding anything wider exposes agent spawning to "
                         "the network")
        self.assertIn("127.0.0.1", LOOPBACK)

    # ------------------------------------------------------------- routes
    def test_the_page_is_served_with_the_token_substituted(self):
        code, body = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn(self.studio.token.encode(), body)
        self.assertNotIn(b"__NXB_TOKEN__", body,
                         "an unsubstituted placeholder means every request "
                         "the page makes is refused")

    def test_state_reports_rigs(self):
        code, body = self._get("/api/state")
        self.assertEqual(code, 200)
        self.assertIn("rigs", json.loads(body))

    def test_the_page_scripts_parse(self):
        """A page that fails to parse renders a dead canvas and says nothing.
        The first version did exactly that -- an empty board with no error --
        and there was no way to tell a bug from an empty design. The page now
        reports its own errors, and this catches the class that would stop it
        getting far enough to report anything."""
        import re
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        code, body = self._get("/")
        script = re.search(rb"<script>(.*)</script>", body, re.S)
        self.assertIsNotNone(script, "the page must carry its script")
        with tempfile.NamedTemporaryFile("wb", suffix=".js",
                                         delete=False) as fh:
            fh.write(script.group(1))
            path = fh.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True,
                               text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(path)

    def test_the_page_reports_its_own_errors(self):
        """A silent page is the defect this project exists to remove."""
        _, body = self._get("/")
        self.assertIn(b"window.onerror", body)
        self.assertIn(b"onunhandledrejection", body)

    def test_the_manifest_and_icon_carry_the_token_in_the_URL(self):
        """A browser fetches a manifest and its icons WITHOUT custom headers,
        so the header form of the token is unavailable to them. If those two
        routes were header-only, Add to Dock would install an app with no
        name and no icon and nobody would know why."""
        code, body = self._get("/manifest.webmanifest")
        self.assertEqual(code, 200)
        m = json.loads(body)
        self.assertEqual(m["display"], "standalone")
        self.assertIn(self.studio.token, m["start_url"])
        self.assertIn(self.studio.token, m["icons"][0]["src"])
        self.assertEqual(self._get("/icon.svg")[0], 200)

    def test_a_pinned_app_survives_a_restart(self):
        """THE PROPERTY THAT MAKES IT AN APP. Add to Dock freezes a start URL,
        so a token that rotated per run would turn yesterday's icon into a
        403. Persisted 0600, and rotatable on demand."""
        from nxb.studio import stored_token
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "l.db")
            first = stored_token(ledger)
            self.assertEqual(first, stored_token(ledger),
                             "a token that changes cannot be pinned")
            self.assertNotEqual(first, stored_token(ledger, fresh=True),
                                "--fresh-token must actually rotate it")
            mode = os.stat(os.path.join(tmp, "studio.token")).st_mode
            self.assertEqual(oct(mode)[-3:], "600",
                             "a long-lived token readable by anything is a "
                             "worse trade than a rotating one")

    def test_the_model_catalog_is_READ_not_invented(self):
        """STUDIO-3. A hardcoded picker shipped `gpt-5.6`, which a live pane
        rejected with "model is not supported". Codex's suggestions now come
        from the operator's own config.toml -- the file that runtime already
        obeys -- and both fields are free text, so a suggestion I get wrong
        costs a retype instead of blocking a value that works."""
        code, body = self._get("/api/models")
        self.assertEqual(code, 200)
        cat = json.loads(body)
        self.assertEqual({k for k in cat if not k.startswith("_")},
                         {"claude_code", "codex"})
        # The CONFIGURED default is reported too, so the UI can name it
        # instead of saying the word "default" at the operator.
        self.assertIn("_configured", cat)
        # Documented in `claude --help`, so these are quotable rather than
        # remembered.
        self.assertIn("opus", cat["claude_code"]["models"])
        for rt in (k for k in cat if not k.startswith("_")):
            with self.subTest(rt=rt):
                self.assertTrue(cat[rt]["efforts"])

    def test_the_model_fields_are_free_text_not_a_closed_picker(self):
        _, body = self._get("/")
        self.assertIn(b'id="fModel" list="dlM"', body)
        self.assertIn(b'id="fEffort" list="dlE"', body)

    def test_composed_agents_reach_the_runtime_flags(self):
        """Every control in the inspector must land on a real flag, or it is
        configuration that functions as a comment."""
        from nxb.rig import launch_command
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "l.db")
            cc, _, _ = launch_command(
                {"name": "W", "runtime": "claude_code", "role": "worker",
                 "model": "opus", "effort": "xhigh"},
                ledger=ledger, repo="/r")
            self.assertIn("--model opus", cc)
            self.assertIn("--effort xhigh", cc)
            cx, _, _ = launch_command(
                {"name": "W", "runtime": "codex", "role": "worker",
                 "model": "gpt-5.6-sol", "effort": "high"},
                ledger=ledger, repo="/r")
            self.assertIn("-m gpt-5.6-sol", cx)
            self.assertIn('model_reasoning_effort="high"', cx)

    def test_agents_with_duplicate_names_are_REFUSED(self):
        """Two panes with one name means a minted id addresses both and the
        worker-side check cannot tell them apart."""
        code, body = self._post("/api/rig/up", {
            "session": "t", "dir": "~", "agents": [
                {"name": "A", "runtime": "codex"},
                {"name": "A", "runtime": "codex"}]})
        self.assertEqual(code, 400)
        self.assertIn("both called", body["error"])

    def test_two_orchestrators_are_REFUSED(self):
        code, body = self._post("/api/rig/up", {
            "session": "t", "dir": "~", "agents": [
                {"name": "A", "runtime": "codex", "role": "orchestrator"},
                {"name": "B", "runtime": "codex", "role": "orchestrator"}]})
        self.assertEqual(code, 400)
        self.assertIn("at most one orchestrator", body["error"])

    def test_hidden_actually_hides(self):
        """STUDIO-4. `#empty` set display:grid, and an ID selector outranks
        the user agent's [hidden]{display:none}, so `el.hidden = true` was a
        no-op and the placeholder text sat underneath every node the operator
        added. The page carries a global rule now, because the next element
        given a display would have inherited the same trap."""
        _, body = self._get("/")
        self.assertIn(b"[hidden]{display:none !important}", body,
                      "an element with an id and a display needs hidden to "
                      "outrank it, or hiding it silently does nothing")

    def test_tearing_down_a_live_fleet_asks_first(self):
        """It is irreversible, the panes may be mid-task, and everything they
        hold goes with the session."""
        _, body = self._get("/")
        self.assertIn(b"Tear down", body)
        self.assertIn(b"confirm(", body)

    def test_liveness_is_keyed_on_what_was_DEPLOYED(self):
        """STUDIO-5. The chip matched the node's CURRENT label against the
        running panes, so renaming a drawn node flipped it to "draft" while
        its pane carried on working -- a diagram lying about the machine. It
        keys on the deployed name now, and a node whose label has moved on
        says "edited" rather than claiming either state."""
        _, body = self._get("/")
        self.assertIn(b"n.deployed && liveNames.has(n.deployed)", body)
        self.assertIn(b"drifted", body)

    def test_a_standing_rig_can_be_opened_into_a_tab(self):
        """STUDIO-6. A tab was a drawing with no way back from the machine:
        a rig stood up from the CLI could not be edited here at all, and one
        torn down from this panel left its tab claiming panes that were
        gone."""
        _, body = self._get("/")
        self.assertIn(b'title="open this rig in a tab"', body)
        self.assertIn(b"delete n.deployed", body)

    def test_undo_is_bound_and_snapshots_before_the_act(self):
        """STUDIO-7. Backspace deleted a node with no way back."""
        _, body = self._get("/")
        self.assertIn(b'if(k === "z")', body)
        self.assertIn(b"e.shiftKey ? redo() : undo()", body)
        self.assertIn(b"el.onfocus = mark", body,
                      "text fields must snapshot on focus; an undo that walks "
                      "back one character is a typing history, not an undo")

    def test_a_rebuild_asks_before_destroying_a_standing_rig(self):
        _, body = self._get("/")
        self.assertIn(b"Rebuild tears it down first", body)

    def test_typing_in_a_text_field_does_not_rebuild_the_panel(self):
        """STUDIO-10, and it made Model and Reasoning UNUSABLE. Their oninput
        handler called paint(), which rebuilds the inspector with innerHTML --
        destroying the very input being typed into, so focus died and the
        suggestion list closed after one character. The backend had honoured
        model and effort since the morning; the UI was eating the keystrokes.

        Text fields repaint the CANVAS only. Selects still do a full paint,
        because changing the provider must re-render the panel to swap which
        model suggestions are offered."""
        _, body = self._get("/")
        self.assertIn(b"function paintCanvas()", body)
        self.assertIn(b"n[key] = el.value; save(); paintCanvas();", body)
        self.assertNotIn(b'text("fModel","model", paint)', body)

    def test_the_placeholder_names_the_real_default(self):
        """'(runtime default)' is a word, not an answer: an operator cannot
        decide whether to override a default he cannot see."""
        _, body = self._get("/")
        self.assertIn(b"const dflt = (rt, key)", body)
        cat = json.loads(self._get("/api/models")[1])
        self.assertIn("claude_code", cat["_configured"])

    def test_usage_reports_what_is_REAL_and_names_what_is_not(self):
        """STUDIO-12/17. Rohan designs fleets around headroom, so a made-up
        figure is worse than none: he would design against it. Codex records
        rate_limits in every rollout. Claude writes NOTHING to disk -- the
        only rate_limit string in its transcripts is a 429 ERROR record -- but
        answers `claude -p /usage` directly, so it is asked on demand and
        CACHED WITH ITS AGE. Never polled: each call is a full runtime turn,
        and polling quota to measure quota is a cost this project has already
        measured and refused."""
        code, body = self._get("/api/usage")
        self.assertEqual(code, 200)
        u = json.loads(body)
        self.assertIn("tokens", u)
        claude = u["limits"]["claude_code"]
        # Absent until asked, and never a fabricated zero.
        self.assertTrue(claude is None or "windows" in claude)
        if claude:
            self.assertIn("read_at", claude,
                          "a percentage without a timestamp is a number the "
                          "operator cannot weigh")
        self.assertIn("costs one Claude turn",
                      u["limits"]["claude_code_reason"])

    def test_the_claude_reading_is_a_BUTTON_not_a_poll(self):
        _, body = self._get("/")
        self.assertIn(b"/api/usage/claude", body)
        self.assertIn(b"cost: one Claude turn", body)
        self.assertNotIn(b"setInterval(askClaude", body)

    def test_an_unparsable_usage_answer_is_an_ERROR_not_a_zero(self):
        """It parses a vendor's human-readable text, so a wording change must
        break loudly rather than quietly reporting 0% used."""
        import nxb.usage as usage
        real = usage.subprocess if hasattr(usage, "subprocess") else None
        out = usage._USAGE_LINE.findall("something else entirely")
        self.assertEqual(out, [])

    def test_tokens_keep_cache_reads_APART_from_input(self):
        """97.7% of the all-time Claude total is cache reads, which do not
        cost what input costs. One combined number would be an alarming
        figure that means almost nothing."""
        u = json.loads(self._get("/api/usage")[1])
        for rt, buckets in u["tokens"].items():
            with self.subTest(rt=rt):
                self.assertEqual(
                    {"input", "output", "cache_read", "cache_write", "total"},
                    set(buckets["all"]))

    def test_a_persona_is_a_markdown_file_on_disk(self):
        """STUDIO-13. They are prose the operator writes for a model to read,
        so they belong in files he can open, edit, grep and carry to another
        machine -- not in a JSON blob or this page's storage."""
        from nxb.personas import load_all, matches, save
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "l.db")
            rec = save(ledger, "Adversarial Auditor", "Challenge every claim.")
            self.assertTrue(rec["file"].endswith(".md"))
            with open(rec["file"], encoding="utf-8") as fh:
                self.assertTrue(fh.read().startswith("# Adversarial Auditor"))
            self.assertEqual([p["name"] for p in load_all(ledger)],
                             ["Adversarial Auditor"])
            # Offering to save something already saved is noise, and noise is
            # how a prompt gets dismissed without being read.
            self.assertIsNotNone(matches(ledger, "Challenge every claim."))
            self.assertIsNone(matches(ledger, "something else"))
            for bad in (("", "text"), ("name", "")):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        save(ledger, *bad)

    def test_a_role_is_LAUNCH_BOUND_where_the_runtime_allows_it(self):
        """STUDIO-11. 'Be an adversarial auditor' is a standing role, not an
        opening remark. This file already distinguishes launch-bound from
        typed, and a role typed as a first message decays the way RIG-3
        describes. Claude carries it in the system prompt; Codex cannot, and
        the asymmetry is recorded rather than papered over."""
        from nxb.enroll import enroll_command
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _ = enroll_command(
                "W", ledger=os.path.join(tmp, "l.db"), repo="/r",
                instructions="Act as an adversarial auditor.")
            brief = cmd.split("$(cat '")[1].split("')")[0]
            with open(brief, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("adversarial auditor", text)
            self.assertIn("YOUR STANDING ROLE", text)

    def test_the_canvas_can_be_PANNED(self):
        """STUDIO-15. A node dragged past the right edge was unreachable:
        there was no pan, and zoom was anchored at the origin so zooming out
        did not reliably bring it back. Drag empty canvas, scroll, space-drag,
        and a fit that PANS as well as scales -- scaling alone left off-screen
        nodes off screen, which is the whole complaint."""
        _, body = self._get("/")
        self.assertIn(b"translate(${panX}px,${panY}px) scale(${zoom})", body)
        self.assertIn(b"spaceDown", body)
        self.assertIn(b'stage.addEventListener("wheel"', body)
        self.assertIn(b"panX = pad - minX*zoom", body)

    def test_zoom_is_anchored_at_the_cursor_not_the_origin(self):
        """Origin-anchored zoom throws away whatever you were looking at."""
        _, body = self._get("/")
        self.assertIn(b"panX = cx - (cx-panX) * (next/zoom)", body)

    def test_the_columns_are_resizable_and_the_header_wraps(self):
        """STUDIO-16. Three hardcoded widths meant the canvas was crushed on a
        narrower display, and the header ran off the edge taking a control
        with it -- one the operator could see half of and could not press."""
        _, body = self._get("/")
        self.assertIn(b'class="split" data-for="rail"', body)
        self.assertIn(b'class="split" data-for="inspector"', body)
        self.assertIn(b"nxb.studio.widths", body)
        self.assertIn(b"#top{display:flex;align-items:stretch;"
                      b"background:var(--panel);flex-wrap:wrap;", body)

    def test_the_body_is_a_FLEX_ROW_not_a_three_column_grid(self):
        """STUDIO-18. The splitters made #body five children while its CSS was
        still a three-column grid, so they wrapped onto a second row and the
        inspector landed UNDERNEATH the canvas. The CSS edit that should have
        prevented it was a str.replace whose anchor no longer matched, and
        str.replace does not raise -- it returns the string unchanged. The
        page was checked for JS syntax and shipped without anyone looking at
        it. This asserts the layout mode itself, because that is the fact that
        was silently wrong."""
        _, body = self._get("/")
        self.assertIn(b"#body{display:flex", body)
        self.assertNotIn(b"#body{display:grid", body,
                         "five flex children in a three-column grid wrap")
        # The order decides the layout as much as the mode does.
        page = body.decode()
        cut = page.split('<div id="body">')[1]
        for earlier, later in (("id=\"rail\"", "id=\"stage\""),
                               ("id=\"stage\"", "<aside")):
            with self.subTest(pair=(earlier, later)):
                self.assertLess(cut.index(earlier), cut.index(later))

    def test_a_dead_rig_record_can_be_FORGOTTEN(self):
        """STUDIO-9. `rig down` deliberately keeps the state file so a rig
        stays visible and re-openable, and nothing ever removed one, so the
        panel accumulated every rig ever built -- it listed five when none
        existed. A record with no delete is a list that only grows."""
        from nxb.keystroke import state_path
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "l.db")
            path = state_path(ledger, "ghost")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"session": "ghost", "panes": []}, fh)
            from nxb.studio import Studio
            code, body = Studio(ledger).forget({"session": "ghost"})
            self.assertEqual(code, 200)
            self.assertFalse(os.path.exists(path))
            self.assertEqual(Studio(ledger).forget({"session": "ghost"})[0],
                             404, "forgetting nothing must not report success")

    def test_forgetting_a_STANDING_rig_is_refused(self):
        """It would leave a running fleet with no record naming its panes."""
        import nxb.rig as rig
        from nxb.studio import Studio
        with tempfile.TemporaryDirectory() as tmp:
            s = Studio(os.path.join(tmp, "l.db"))
            real = rig.live_rig_sessions
            rig.live_rig_sessions = lambda ledger: ["alive"]
            try:
                code, body = s.forget({"session": "alive"})
            finally:
                rig.live_rig_sessions = real
            self.assertEqual(code, 409)
            self.assertIn("Tear it down first", body["error"])

    def test_an_unknown_route_is_404_not_a_traceback(self):
        self.assertEqual(self._get("/api/nope")[0], 404)

    # -------------------------------------------------- refusals that bite
    def test_a_fleet_with_no_workers_is_REFUSED(self):
        code, body = self._post("/api/rig/up",
                                {"session": "t", "dir": "~", "workers": []})
        self.assertEqual(code, 400)
        self.assertIn("not a fleet", body["error"])

    def test_a_session_name_that_would_break_tmux_is_REFUSED(self):
        """The name goes into a tmux target AND into every worker's name, so
        a space or a colon breaks addressing in two places at once."""
        for bad in ("", "two words", "has:colon", "dot.ted", "quo'te"):
            with self.subTest(session=bad):
                code, _ = self._post("/api/rig/up",
                                     {"session": bad, "dir": "~",
                                      "workers": [{"runtime": "codex",
                                                   "count": 1}]})
                self.assertEqual(code, 400)

    def test_a_missing_directory_is_REFUSED_before_anything_spawns(self):
        code, body = self._post("/api/rig/up",
                                {"session": "t", "dir": "/no/such/dir",
                                 "workers": [{"runtime": "codex", "count": 1}]})
        self.assertEqual(code, 400)
        self.assertIn("no such directory", body["error"])

    def test_an_unknown_runtime_is_REFUSED(self):
        code, body = self._post("/api/rig/up",
                                {"session": "t", "dir": "~",
                                 "workers": [{"runtime": "gpt9", "count": 1}]})
        self.assertEqual(code, 400)
        self.assertIn("gpt9", body["error"])

    def test_malformed_json_is_a_400_not_a_500(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rig/up", data=b"{not json",
            headers={"X-NXB-Token": self.studio.token})
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("should have refused")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)


if __name__ == "__main__":
    unittest.main()
