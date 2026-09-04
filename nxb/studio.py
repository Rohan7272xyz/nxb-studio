"""The studio: compose a fleet visually, then bring it to life in tmux.

WHY A LOCAL SERVER AND NOT A HOSTED PAGE
----------------------------------------
A page served from anywhere else cannot reach this machine: browsers block
cross-origin requests to localhost, and a hosted artifact runs under a content
policy that forbids them outright. So the page is served BY nxb, from
127.0.0.1, and talks to its own origin. Nothing leaves the machine.

THIS ENDPOINT SPAWNS AGENTS, SO IT IS TREATED AS A WEAPON
---------------------------------------------------------
`rig up` launches runtimes in `--yolo`. An HTTP endpoint that does that is a
serious surface, and "it is only on localhost" is NOT a boundary: every page
in the operator's browser can issue requests to 127.0.0.1, and a malicious one
would love to stand up an unsandboxed agent fleet. Four measures, none of them
optional:

  1. Bound to 127.0.0.1 only, never 0.0.0.0.
  2. A token minted per run, required on EVERY request including the page
     load. Printed once, in the URL, on the operator's own terminal.
  3. The Host header must be a loopback name, which is what stops DNS
     rebinding from turning a stranger's domain into this origin.
  4. Compared with `secrets.compare_digest`, so the token cannot be guessed a
     character at a time.

That is defence for a tool on one person's laptop, stated plainly rather than
implied. It is not a reason to bind this to a network interface.

WHAT THE DIAGRAM ACTUALLY CONTROLS, STATED HONESTLY
---------------------------------------------------
Node POSITIONS are for the operator's head, not for tmux: the pane arrangement
comes from the chosen tmux layout, which is a separate control on the page. The
composition -- how many workers, of which runtime, under which orchestrator --
is what becomes a rig. Saying so in the UI matters, because a diagram that
looks like it is wiring things up while the wiring is decided elsewhere is the
kind of "presents as configuration, functions as a comment" gap this project
was started to close.
"""

import errno
import json
import os
import secrets
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "studio.html")

#: Loopback names only. A Host header naming anything else is a rebinding
#: attempt, or a misconfiguration that would become one.
LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}

#: Chromium-family browsers take `--app=<url>`, which opens a window with no
#: tab strip and no address bar. That is the cheapest honest route to "it is
#: an app": a real window in the Dock and the app switcher, with none of an
#: Electron bundle's weight or update surface. Ordered by what Rohan is most
#: likely to have.
APP_BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Arc.app/Contents/MacOS/Arc",
]

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="13" fill="#1c1118"/>
<circle cx="32" cy="17" r="6" fill="#c792ea"/>
<circle cx="16" cy="45" r="5" fill="#e0a267"/>
<circle cx="32" cy="45" r="5" fill="#7fd6bd"/>
<circle cx="48" cy="45" r="5" fill="#e0a267"/>
<g stroke="#5a4657" stroke-width="2" fill="none">
<path d="M32 23 V33 M32 33 H16 V40 M32 33 V40 M32 33 H48 V40"/></g></svg>"""


def manifest(token):
    """Enough for Safari's Add to Dock and Chrome's Install to make a real app.

    The token rides in the icon and start URLs because a browser fetches a
    manifest WITHOUT custom headers, so the header form is unavailable here.
    Same guard, different carrier.
    """
    return {
        "name": "nxb studio", "short_name": "nxb",
        "start_url": f"/?t={token}", "scope": "/",
        "display": "standalone", "background_color": "#1c1118",
        "theme_color": "#1c1118",
        "icons": [{"src": f"/icon.svg?t={token}", "sizes": "any",
                   "type": "image/svg+xml", "purpose": "any"}],
    }


def stored_token(ledger, *, fresh=False):
    """A token that SURVIVES RESTARTS, so the app can be pinned to a URL.

    A per-run token is the safer default and it makes the studio unpinnable:
    macOS "Add to Dock" and Chrome "Install" both freeze a start URL, so a
    token that rotates turns yesterday's app icon into a 403. Persisting it is
    what makes this an app rather than a link you re-copy every morning.

    Stored 0600 in the ledger's own directory, which is the same trust
    boundary the ledger already has -- anything that can read this file can
    already read the ledger and run nxb directly. `--fresh-token` rotates it,
    which is the answer if it is ever pasted somewhere it should not be.
    """
    path = os.path.join(os.path.dirname(ledger), "studio.token")
    if not fresh:
        try:
            with open(path, encoding="utf-8") as handle:
                existing = handle.read().strip()
            if existing:
                return existing
        except OSError:
            pass
    token = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    return token


def _ordered(models, configured):
    """Catalog with the CONFIGURED model first, and never missing it.

    Being in a CLI's catalog means the binary knows the name, not that this
    account can call it -- a `gpt-5.6` from the catalog was refused by the API
    with "model is not supported". The configured default is the one model
    proven to work here, so it leads and is never dropped even if the catalog
    scrape missed it.
    """
    out = [m for m in models if m != configured]
    return ([configured] + out) if configured else out


class Studio:
    """Server state: the token, and the ledger every action is scoped to."""

    def __init__(self, ledger, *, token=None, repo=None):
        self.ledger = ledger
        self.token = token or secrets.token_urlsafe(24)
        self.repo = repo or os.path.dirname(HERE)
        self.lock = threading.Lock()
        self.managed = os.environ.get("NXB_STUDIO_MANAGED") == "1"
        self._usage = None
        # WHEN THIS PROCESS STARTED, against when its code was last written.
        # Four times in one day a server running older code looked like a
        # broken feature -- a 404 on a route, a button that did nothing, a
        # figure that never arrived. The operator cannot see the difference
        # from the page, so the page is told.
        self.started_at = time.time()
        self.code_mtime = max(
            (os.path.getmtime(os.path.join(HERE, f))
             for f in os.listdir(HERE) if f.endswith((".py", ".html"))),
            default=0)

    # ------------------------------------------------------------- actions

    def usage(self):
        """Consumption, from each runtime's own records. See nxb/usage.py."""
        if self._usage is None:
            from nxb.usage import Usage
            self._usage = Usage(os.path.join(os.path.dirname(self.ledger),
                                             "usage-cache.json"))
        return self._usage.read()

    def personas(self):
        from nxb.personas import load_all
        return {"personas": load_all(self.ledger)}

    def drafts(self):
        """Durable designs shared with MCP clients, newest first."""
        from nxb.studio_drafts import list_drafts
        return {"drafts": list_drafts(self.ledger)}

    def save_draft(self, body):
        """Persist a browser tab without pretending a half-edit is launchable."""
        from nxb.studio_drafts import (DraftConflict, DraftError,
                                       save_draft)
        try:
            record = save_draft(
                self.ledger, body.get("draft"),
                draft_id=body.get("draft_id"),
                expected_revision=body.get("expected_revision"),
                source="studio", strict=False)
        except DraftConflict as exc:
            return 409, {"error": str(exc), "state": "CONFLICT"}
        except DraftError as exc:
            return 400, {"error": str(exc)}
        return 200, {"state": "SAVED", "draft": record}

    def delete_draft(self, body):
        """Closing a tab remains recoverable now that its state is on disk."""
        from nxb.studio_drafts import (DraftConflict, DraftError,
                                       delete_draft)
        try:
            return 200, delete_draft(
                self.ledger, body.get("draft_id"),
                expected_revision=body.get("expected_revision"))
        except DraftConflict as exc:
            return 409, {"error": str(exc), "state": "CONFLICT"}
        except DraftError as exc:
            return 404, {"error": str(exc)}

    def save_persona(self, body):
        from nxb.personas import save
        try:
            return 200, save(self.ledger, body.get("name"), body.get("body"))
        except ValueError as exc:
            return 400, {"error": str(exc)}

    def delete_persona(self, body):
        from nxb.personas import delete
        if delete(self.ledger, body.get("name") or ""):
            return 200, {"state": "DELETED", "name": body.get("name")}
        return 404, {"error": "no such persona"}

    def ask_claude_usage(self, body):
        """Explicit refresh. It costs a Claude turn, so it is never automatic."""
        if self._usage is None:
            self.usage()
        reading = self._usage.ask_claude()
        return (400 if "error" in reading else 200), reading

    def models(self):
        """What each runtime will actually accept, DISCOVERED not guessed.

        The first version shipped a closed dropdown of model names I made up.
        Claude's aliases happened to be right because its --help documents
        them; the Codex list did not, and `gpt-5.6` came back from the API as
        "model is not supported" in a live pane. A picker whose options the
        runtime rejects is worse than a text box: it looks authoritative.

        So the Codex default is read from the operator's own config.toml,
        which is the file that runtime already obeys, and both fields stay
        FREE TEXT with these as suggestions. A suggestion I get wrong costs a
        retype; a closed list I get wrong blocks a value that would work.
        """
        # What each runtime is CONFIGURED to use when handed no flag. Shown
        # as the placeholder, so "default" names a model instead of being a
        # word: an operator cannot decide whether to override a default he
        # cannot see.
        cfg = {"claude_code": {}, "codex": {}}
        try:
            import json as _json
            with open(os.path.expanduser("~/.claude/settings.json"),
                      encoding="utf-8") as handle:
                claude_settings = _json.load(handle)
            cfg["claude_code"] = {
                "model": claude_settings.get("model"),
                "effort": claude_settings.get("effortLevel"),
            }
        except (OSError, ValueError):
            pass
        codex = []
        try:
            with open(os.path.expanduser("~/.codex/config.toml"),
                      encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip().strip('"\'')
                    if key == "model" and not cfg["codex"].get("model"):
                        cfg["codex"]["model"] = value
                        codex.append(value)
                    elif key == "model_reasoning_effort":
                        cfg["codex"]["effort"] = value
        except OSError:
            pass
        from nxb.usage import model_catalog
        catalog = model_catalog()
        return {
            "_configured": cfg,
            # Documented in `claude --help` as the alias form.
            "claude_code": {
                "models": _ordered(catalog["claude_code"],
                                   cfg["claude_code"].get("model")),
                # From `claude --help`, which documents these five.
                "efforts": ["low", "medium", "high", "xhigh", "max"]},
            # Read from config.toml; empty if it says nothing, and the field
            # is free text either way.
            "codex": {
                "models": _ordered(catalog["codex"] or codex,
                                   cfg["codex"].get("model")),
                "efforts": ["low", "medium", "high", "xhigh"]},
        }

    def state(self):
        """Every standing rig and its workers. The page's whole world."""
        from nxb.keystroke import load_rig, rig_sessions
        from nxb.rig import (RIG_HOOKS_REVIEW, RIG_TRUST_PROMPT,
                             RIG_UPDATE_PROMPT,
                             RigTmuxError, capture, live_rig_sessions,
                             pane_state, rig_roster, trust_scope)

        live = set(live_rig_sessions(self.ledger))
        rigs = []
        for session in rig_sessions(self.ledger):
            record = load_rig(self.ledger, session) or {}
            standing = session in live
            names = set()
            if standing:
                try:
                    names = {e.name for e in rig_roster(self.ledger,
                                                        session).named}
                except RigTmuxError:
                    standing = False        # unaskable is not "no workers"
            panes = []
            for p in record.get("panes", []):
                item = {"name": p.get("name"), "runtime": p.get("runtime"),
                        "role": p.get("role", "worker"),
                        "pane": p.get("pane"),
                        "enrolled": bool(p.get("enrolment")),
                        "alive": p.get("name") in names}
                if p.get("reason") not in (None, RIG_TRUST_PROMPT,
                                            RIG_HOOKS_REVIEW,
                                            RIG_UPDATE_PROMPT):
                    # Naming/enrolment/time-out failures remain actionable
                    # even when the runtime screen itself later looks ready.
                    item["reason"] = p["reason"]
                if standing and p.get("pane") and p.get("runtime"):
                    current = pane_state(p["pane"], p["runtime"])
                    if current in (RIG_TRUST_PROMPT, RIG_HOOKS_REVIEW,
                                   RIG_UPDATE_PROMPT):
                        item["reason"] = current
                    if current == RIG_TRUST_PROMPT:
                        scope = trust_scope(capture(p["pane"]))
                        if scope:
                            item["trust_scope"] = scope
                panes.append(item)
            rigs.append({"session": session, "standing": standing,
                         "panes": panes})
        return {"rigs": rigs, "ledger": self.ledger,
                "managed": self.managed,
                "stale_code": self.code_mtime > self.started_at,
                "started_at": self.started_at}

    def _launch_args(self, body):
        """Validate one browser composition and return its rig arguments."""
        from nxb.rig import compose, compose_agents
        session = str(body.get("session") or "").strip()
        if not session or any(c in session for c in " \t:.$'\"\\"):
            raise ValueError("a session name is required, with no spaces, "
                             "colons, dots or quotes: tmux and the worker "
                             "names both have to carry it")
        work_dir = os.path.expanduser(str(body.get("dir") or "~"))
        if not os.path.isdir(work_dir):
            raise ValueError(f"no such directory: {work_dir}")
        layout = body.get("layout") or "main-horizontal"
        if body.get("agents"):
            # The composed form: every node is an individual the operator
            # named and configured. The count form below stays for the CLI
            # and for anything that only cares how many.
            plan = compose_agents(body["agents"], layout=layout)
        else:
            workers = [(w["runtime"], int(w["count"]))
                       for w in body.get("workers", [])
                       if int(w.get("count", 0))]
            if not workers:
                raise ValueError("a fleet with no workers is not a fleet")
            plan = compose(workers,
                           orchestrator=body.get("orchestrator") or None,
                           layout=layout)
        return session, work_dir, plan

    def up(self, body):
        """Stand a composed fleet up. Serialised: two at once would race tmux."""
        from nxb.rig import stand_up

        try:
            session, work_dir, plan = self._launch_args(body)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        with self.lock:
            report = stand_up(plan, session=session, work_dir=work_dir,
                              ledger=self.ledger)
        return (200 if report.get("state") == "READY" else 409), report

    def trust_and_retry(self, body):
        """Accept verified trust prompts, then restart only that partial rig."""
        from nxb.rig import (accept_trust_prompts, stand_up, tear_down)

        try:
            session, work_dir, plan = self._launch_args(body)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        with self.lock:
            accepted = accept_trust_prompts(session, ledger=self.ledger)
            if accepted.get("state") != "TRUST_ACCEPTED":
                return 409, accepted
            gone = tear_down(session)
            if gone.get("state") != "GONE":
                return 409, {"state": "REFUSED",
                             "reason": "rig_pane_not_ready",
                             "detail": f"Trust was accepted, but {session!r} "
                                       "could not be restarted safely.",
                             "trust": accepted, "teardown": gone}
            report = stand_up(plan, session=session, work_dir=work_dir,
                              ledger=self.ledger)
        report["trust_recovery"] = accepted
        return (200 if report.get("state") == "READY" else 409), report

    def hooks_and_retry(self, body):
        """Approve verified hook screens, then restart only that partial rig."""
        from nxb.rig import (accept_hook_prompts, stand_up, tear_down)

        try:
            session, work_dir, plan = self._launch_args(body)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        with self.lock:
            approved = accept_hook_prompts(session, ledger=self.ledger)
            if approved.get("state") != "HOOKS_APPROVED":
                return 409, approved
            gone = tear_down(session)
            if gone.get("state") != "GONE":
                return 409, {"state": "REFUSED",
                             "reason": "rig_pane_not_ready",
                             "detail": f"Hooks were approved, but {session!r} "
                                       "could not be restarted safely.",
                             "hooks": approved, "teardown": gone}
            report = stand_up(plan, session=session, work_dir=work_dir,
                              ledger=self.ledger)
        report["hook_recovery"] = approved
        return (200 if report.get("state") == "READY" else 409), report

    def forget(self, body):
        """Delete a rig's RECORD. Refuses while its session is standing.

        `rig down` deliberately leaves the state file: it is how a torn-down
        rig stays visible and re-openable. Nothing ever removed one, so the
        panel accumulated every rig ever built and listed five when none
        existed. A record with no way to delete it is a list that only grows.

        Refusing while the session stands is the point: forgetting a live rig
        would orphan a running fleet from the only file that names its panes.
        """
        from nxb.rig import live_rig_sessions
        session = str(body.get("session") or "").strip()
        if not session:
            return 400, {"error": "which rig?"}
        if session in live_rig_sessions(self.ledger):
            return 409, {"error": f"{session} is standing. Tear it down "
                                  f"first: forgetting a live rig would leave "
                                  f"a running fleet with no record naming its "
                                  f"panes."}
        from nxb.keystroke import state_path
        path = state_path(self.ledger, session)
        try:
            os.remove(path)
        except OSError:
            return 404, {"error": f"no record for {session}"}
        return 200, {"state": "FORGOTTEN", "session": session}

    def down(self, body):
        from nxb.rig import tear_down
        session = str(body.get("session") or "").strip()
        if not session:
            return 400, {"error": "which rig?"}
        with self.lock:
            return 200, tear_down(session)


def handler_for(studio):
    class Handler(BaseHTTPRequestHandler):
        server_version = "nxb-studio"

        def log_message(self, *args):            # quiet; the terminal is his
            pass

        # ------------------------------------------------------ the guards
        def _authorised(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in LOOPBACK:
                return False, "this server answers only to loopback"
            sent = (self.headers.get("X-NXB-Token")
                    or self._query().get("t", [""])[0])
            if not secrets.compare_digest(str(sent), studio.token):
                return False, "bad or missing token"
            return True, None

        def _query(self):
            from urllib.parse import parse_qs, urlparse
            return parse_qs(urlparse(self.path).query)

        def _path(self):
            from urllib.parse import urlparse
            return urlparse(self.path).path

        def _send(self, code, payload, ctype="application/json"):
            body = (payload if isinstance(payload, bytes)
                    else json.dumps(payload).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # The page never embeds anything and is never embedded.
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' "
                             "'unsafe-inline'; script-src 'self' "
                             "'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        # ------------------------------------------------------- the routes
        def do_GET(self):
            ok, why = self._authorised()
            if not ok:
                return self._send(403, {"error": why})
            path = self._path()
            if path in ("/", "/index.html"):
                with open(PAGE, "rb") as handle:
                    page = handle.read()
                page = page.replace(b"__NXB_TOKEN__", studio.token.encode())
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, studio.state())
            if path == "/api/personas":
                return self._send(200, studio.personas())
            if path == "/api/drafts":
                return self._send(200, studio.drafts())
            if path == "/api/usage":
                return self._send(200, studio.usage())
            if path == "/api/models":
                return self._send(200, studio.models())
            if path == "/manifest.webmanifest":
                return self._send(200, manifest(studio.token),
                                  "application/manifest+json")
            if path == "/icon.svg":
                return self._send(200, ICON.encode(), "image/svg+xml")
            return self._send(404, {"error": "no such route"})

        def do_POST(self):
            ok, why = self._authorised()
            if not ok:
                return self._send(403, {"error": why})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, {"error": "malformed JSON"})
            routes = {"/api/rig/up": studio.up,
                      "/api/rig/trust-and-retry": studio.trust_and_retry,
                      "/api/rig/hooks-and-retry": studio.hooks_and_retry,
                      "/api/rig/down": studio.down,
                      "/api/rig/forget": studio.forget,
                      "/api/drafts/save": studio.save_draft,
                      "/api/drafts/delete": studio.delete_draft,
                      "/api/personas/save": studio.save_persona,
                      "/api/personas/delete": studio.delete_persona,
                      "/api/usage/claude": studio.ask_claude_usage}
            action = routes.get(self._path())
            if action is None:
                return self._send(404, {"error": "no such route"})
            try:
                code, payload = action(body)
            except Exception as exc:                           # noqa: BLE001
                # A dropped connection tells the page nothing and looks like
                # the server dying. Every failure leaves by the same door.
                return self._send(500, {"error": f"{type(exc).__name__}: "
                                                 f"{exc}"})
            return self._send(code, payload)

    return Handler


def _open_as_app(url, profile):
    """A chromeless window, or None if no Chromium-family browser is here."""
    import subprocess
    for path in APP_BROWSERS:
        if os.path.exists(path):
            subprocess.Popen(
                [path, f"--app={url}", f"--user-data-dir={profile}",
                 "--window-size=1500,950"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return os.path.basename(os.path.dirname(os.path.dirname(
                os.path.dirname(path))))
    return None


def serve(ledger, *, port=8787, host="127.0.0.1", open_browser=True,
          app=False, fresh_token=False):
    # The foreground command doubles as "open Studio" once the LaunchAgent is
    # installed. It must not punish the operator with EADDRINUSE for having
    # successfully made Studio always-on.
    if os.environ.get("NXB_STUDIO_MANAGED") != "1":
        try:
            from nxb.studio_service import status as service_status
            running = service_status(port=port)
        except Exception:                                      # noqa: BLE001
            running = {}
        if running.get("state") == "RUNNING":
            token = stored_token(ledger, fresh=False)
            url = f"http://{host}:{int(port)}/?t={token}"
            opened = None
            if app:
                profile = os.path.join(os.path.dirname(ledger), "studio-app")
                opened = _open_as_app(url, profile)
            if open_browser and not opened:
                import webbrowser
                webbrowser.open(url)
            print(f"nxb studio is already running as an always-on service: "
                  f"http://{host}:{int(port)}")
            print("  opened the existing service; no second server was "
                  "started.")
            return 0

    studio = Studio(ledger, token=stored_token(ledger, fresh=fresh_token))
    try:
        server = ThreadingHTTPServer((host, port), handler_for(studio))
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.EADDRINUSE:
            print(f"nxb studio could not start: {host}:{port} is already in "
                  "use. Run `python3 -m nxb studio status` to check the "
                  "always-on service.")
            return 3
        raise
    url = f"http://{host}:{server.server_port}/?t={studio.token}"
    if studio.managed:
        # The launchd log is not where a long-lived bearer token belongs.
        print(f"nxb studio service: http://{host}:{server.server_port}")
        print("  token omitted from the service log; it remains in the "
              "0600 studio.token file.")
    else:
        print(f"nxb studio: {url}")
        print("  the token is required on every request and persists across "
              "restarts.")
        print("  ctrl-c to stop.")
    # ONE READING PER STUDIO LAUNCH, on a worker thread. Claude will not write
    # its usage to disk, so the only way to have a number on screen when the
    # page opens is to ask -- and asking costs a full turn, so it happens once
    # per server start rather than once per page load or on a timer. Anything
    # else either shows the operator "unread" forever or spends quota to
    # measure quota.
    def _prime():
        # A FAILURE HERE IS RECORDED, NOT SWALLOWED. The first version caught
        # everything and passed, so a priming thread that died left the page
        # saying "reading…" with nothing anywhere saying why. It must not be
        # fatal to the server, and it must not be silent either.
        try:
            studio.usage()               # warms the token cache
            studio._usage.ask_claude()   # one Claude turn
        except Exception as exc:                               # noqa: BLE001
            if studio._usage is not None:
                studio._usage.claude_error = f"{type(exc).__name__}: {exc}"
            print(f"  usage priming failed: {exc}")

    threading.Thread(target=_prime, daemon=True).start()

    if studio.managed:
        # launchd KeepAlive is the reloader: exit this old process when Python
        # or HTML changes and launchd immediately starts the new code. A
        # foreground server does not do this because exiting there would make
        # the page go offline instead of refreshing it.
        def _reload_on_change():
            while True:
                time.sleep(2)
                current = max(
                    (os.path.getmtime(os.path.join(HERE, name))
                     for name in os.listdir(HERE)
                     if name.endswith((".py", ".html"))), default=0)
                if current > studio.code_mtime:
                    print("  Studio code changed; handing restart to launchd.")
                    server.shutdown()
                    return

        threading.Thread(target=_reload_on_change, daemon=True).start()

    if app:
        # A DEDICATED PROFILE, deliberately. Sharing the operator's normal
        # browser profile would put his logged-in sessions in the same window
        # as a page that can spawn agents, and would make the app window
        # inherit whatever extensions are installed there.
        profile = os.path.join(os.path.dirname(ledger), "studio-app")
        which = _open_as_app(url, profile)
        if which:
            print(f"  opened as an app window via {which}.")
        else:
            print("  no Chromium-family browser here, so --app cannot open a "
                  "chromeless window.")
            print("  On this Mac the equivalent is Safari's own web apps:")
            print("    open the URL in Safari, then File > Add to Dock.")
            print("  It becomes a real app with a Dock icon and its own "
                  "window, and the URL above keeps working because the token "
                  "is now persistent.")
            open_browser = True
        open_browser = open_browser and not which
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstudio stopped. Your rigs keep running.")
    finally:
        server.server_close()
    return 0
