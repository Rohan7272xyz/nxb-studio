"""Check every assumption this broker makes about the runtimes it drives.

WHY THIS EXISTS. nxb reads screens, parses prose, greps binaries and passes
flags. Every one of those is a contract with a vendor's CLI that the vendor
never agreed to, and a runtime update can void any of them SILENTLY. Two
already broke in a single afternoon: a Codex release added a boot prompt
nobody had seen, so readiness degraded into a 60-second timeout with a useless
verdict; and a model list written from memory offered one the API refused
while the rig still reported READY.

The honest position is not that drift can be prevented. It cannot. It is that
drift must be CHEAP TO DETECT, so this is one command that asks every question
at once and says which answers changed.

  python3 -m nxb doctor          # fast: nothing is launched, no tokens spent
  python3 -m nxb doctor --deep   # also asks Claude for /usage: costs one turn

WHAT IT DELIBERATELY DOES NOT DO. It does not "fix" anything. A drifted
assumption needs a person to look at what the runtime does now, because the
whole failure mode here is code that guessed and was confidently wrong.
"""

import json
import os
import re
import shutil
import subprocess

VERSIONS_FILE = "contract/runtime-versions.json"

OK, DRIFT, ABSENT, WATCH = "OK", "DRIFT", "ABSENT", "WATCH"


def _run(cmd, timeout=25):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
        return (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _binary(cmd):
    """The file whose strings are worth reading.

    `which codex` is a JS launcher; the strings live in the native binary it
    shells out to. Reading the launcher made this file report DRIFT on a
    marker that was present all along, which is the "a guard that reports
    something false teaches people to ignore it" failure, committed by the
    guard written to catch that class.
    """
    import glob
    path = shutil.which(cmd)
    if not path:
        return ""
    real = os.path.realpath(path)
    if real.endswith(".js"):
        base = os.path.dirname(real)
        for pattern in (
                os.path.join(base, "..", "node_modules", "@openai",
                             f"{cmd}-*", "vendor", "*", "bin", cmd),
                os.path.join(base, "..", "**", "bin", cmd)):
            for hit in glob.glob(pattern, recursive=True):
                if os.path.isfile(hit) and os.access(hit, os.X_OK):
                    return hit
    return real


def _blob(path):
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("latin-1", "ignore")
    except OSError:
        return ""


def versions():
    out = {}
    for name, args in (("claude", ["claude", "--version"]),
                       ("codex", ["codex", "--version"]),
                       ("tmux", ["tmux", "-V"])):
        if shutil.which(name):
            out[name] = " ".join(_run(args).split())[:60]
    return out


def _flags(runtime, help_text, expected):
    """Every flag nxb passes must still be documented by the CLI itself."""
    missing = [f for f in expected if f not in help_text]
    if not help_text:
        return (ABSENT, f"{runtime} is not installed, so nothing was checked")
    if missing:
        return (DRIFT, f"{runtime} no longer documents: {', '.join(missing)}. "
                       f"nxb passes these on every launch.")
    return (OK, f"all {len(expected)} flags nxb passes are still documented")


def checks(deep=False):
    """Every question, asked. Returns a list of (area, status, detail)."""
    out = []
    claude_help = _run(["claude", "--help"]) if shutil.which("claude") else ""
    codex_help = _run(["codex", "--help"]) if shutil.which("codex") else ""

    out.append(("claude flags",) + _flags(
        "claude", claude_help,
        ["--model", "--effort", "--append-system-prompt",
         "--dangerously-skip-permissions", "-p"]))
    out.append(("codex flags",) + _flags(
        "codex", codex_help, ["--model", "--config", "--sandbox"]))

    # -- readiness markers: BOOTED, never grepped --------------------------
    #
    # The first version grepped each binary for its marker. That reported
    # DRIFT on a Codex string that was present (wrong file) and OK on a Claude
    # string that was absent (assembled at runtime, never a literal). Both
    # answers were wrong, in opposite directions.
    #
    # A READINESS CHECK MUST TEST THE THING YOU WILL ACTUALLY USE -- this
    # project's own rule, learned when a rename check passed while the thing
    # it stood for was broken. So --deep boots each runtime in a throwaway
    # tmux pane and looks at the screen. It costs a process start and NO
    # tokens, because nothing is ever sent to it.
    if deep:
        for runtime, cmd in (("claude_code", "claude"), ("codex", "codex")):
            out.append((f"{runtime} ready marker",) + _boot_marker(runtime, cmd))
    else:
        out.append(("ready markers", WATCH,
                    "not checked: the only honest test is booting the runtime "
                    "and reading its screen. Use --deep."))

    # -- model catalogs -----------------------------------------------------
    from nxb.usage import model_catalog
    catalog = model_catalog()
    for runtime, cmd in (("claude_code", "claude"), ("codex", "codex")):
        found = catalog.get(runtime) or []
        if not shutil.which(cmd):
            out.append((f"{runtime} model catalog", ABSENT, "not installed"))
        elif not found:
            out.append((f"{runtime} model catalog", DRIFT,
                        "the extractor found NO models. Its pattern is a "
                        "whitelist of today's naming, so a new family (a "
                        "'gpt-6', an 'astra') matches nothing. The picker "
                        "falls back to your configured model and the new one "
                        "is unreachable until the pattern is widened."))
        else:
            out.append((f"{runtime} model catalog", OK,
                        f"{len(found)} models: {', '.join(found[:6])}"
                        + (" …" if len(found) > 6 else "")))

    # -- names the catalog patterns CANNOT express -------------------------
    unseen = _unmatched_models(catalog)
    # A WATCH, not a failure. This is a heuristic over a binary's strings and
    # it cannot be precise -- it surfaced `claude-desktop-3p` and
    # `claude-eval-9`, neither of which is a model. A heuristic that reddens
    # the run is a run people stop reading.
    out.append(("possible new model names", WATCH if unseen else OK,
                (f"names the pattern cannot match, worth an eye when a "
                 f"release lands: {', '.join(unseen[:8])}. Some will be "
                 f"noise. If one is a real new model, widen the pattern in "
                 f"nxb/usage.py.")
                if unseen else
                "no model-shaped name in either binary is missed by the "
                "pattern"))

    # -- the JSON shapes nxb reads ------------------------------------------
    out.append(("codex rollout shape",) + _codex_shape())
    out.append(("claude transcript shape",) + _claude_shape())

    if deep:
        from nxb.usage import claude_plan_usage
        reading = claude_plan_usage()
        out.append(("claude /usage wording",
                    DRIFT if "error" in reading else OK,
                    reading.get("error") or
                    f"parsed {len(reading['windows'])} windows: "
                    f"{', '.join(reading['windows'])}"))
    return out


def _boot_marker(runtime, cmd, deadline=45.0):
    """Boot the runtime in a scratch tmux pane and look for its marker.

    No prompt is ever sent, so this costs a process start and no tokens. The
    session is killed by name, never by pattern, per the standing ban.
    """
    import time

    from nxb.rig import BLOCKING_PROMPTS, READY_MARKERS, _exact, _tmux
    if not shutil.which(cmd):
        return (ABSENT, "not installed")
    if not shutil.which("tmux"):
        return (ABSENT, "tmux is not installed, so nothing can be booted")
    session = f"nxb-doctor-{os.getpid()}"
    _tmux("kill-session", "-t", _exact(session))
    made = _tmux("new-session", "-d", "-s", session, "-c",
                 os.path.expanduser("~"), "-x", "200", "-y", "50")
    if made.returncode != 0:
        return (ABSENT, f"could not create a tmux session: {made.stderr}")
    try:
        launch = "claude --yolo" if cmd == "claude" else "codex --yolo"
        _tmux("send-keys", "-t", f"={session}:", launch)
        time.sleep(0.4)
        _tmux("send-keys", "-t", f"={session}:", "Enter")
        wanted = READY_MARKERS[runtime]
        end = time.time() + deadline
        screen = ""
        while time.time() < end:
            screen = _tmux("capture-pane", "-t", f"={session}:", "-p",
                           "-J").stdout
            if any(m in screen for m in wanted):
                return (OK, f"booted and showed: "
                            f"{[m for m in wanted if m in screen][0]!r}")
            for needle in BLOCKING_PROMPTS:
                if needle in screen:
                    return (WATCH, f"booted onto a prompt nxb already knows: "
                                   f"{needle!r}")
            time.sleep(0.6)
        tail = " ".join(screen.split())[-160:]
        return (DRIFT, f"booted and never showed any of {list(wanted)}. "
                       f"Screen ended: ...{tail}")
    finally:
        _tmux("kill-session", "-t", _exact(session))


def _unmatched_models(catalog):
    """Model-shaped names the CLIs know and our pattern does not.

    THE POINT OF THE WHOLE FILE, in one check. Everything else asks whether a
    thing nxb depends on still exists. This asks whether something NEW has
    appeared that nxb cannot see -- which is the shape a new model release
    takes, and the shape no 'does it still work' test can catch.
    """
    known = {m for models in catalog.values() for m in models}
    seen = set()
    for cmd, pattern in (
            # Anthropic ids are `claude-<family>-<n>`; the family is the part
            # a picker offers, and a new one is exactly what we would miss.
            ("claude", r"\bclaude-([a-z]{3,12})-[0-9]"),
            # OpenAI ids in the Codex binary, any family and any generation.
            ("codex", r"\b((?:gpt|o)-?[0-9]+(?:\.[0-9]+)?(?:-[a-z]{2,8})?)\b")):
        binary = _binary(cmd)
        if not binary:
            continue
        blob = _blob(binary)
        for name in set(re.findall(pattern, blob)):
            if name in known or any(name in k for k in known):
                continue
            if len(name) < 3 or name in {"code", "cli", "com"}:
                continue
            seen.add(name)
    return sorted(seen)[:12]


def _codex_shape():
    import glob
    paths = glob.glob(os.path.expanduser(
        "~/.codex/sessions/*/*/*/rollout-*.jsonl"))
    if not paths:
        return (ABSENT, "no Codex sessions on this machine to check against")
    newest = max(paths, key=lambda p: os.stat(p).st_mtime)
    want = {"token_count": False, "rate_limits": False,
            "last_token_usage": False}
    try:
        with open(newest, errors="replace") as handle:
            for line in handle:
                for key in want:
                    if f'"{key}"' in line:
                        want[key] = True
    except OSError:
        return (ABSENT, "could not read the newest rollout")
    missing = [k for k, found in want.items() if not found]
    return ((DRIFT, f"the newest rollout no longer carries: {missing}. "
                    f"Usage and rate limits are read from these.")
            if missing else
            (OK, "token_count, rate_limits and last_token_usage all present"))


def _claude_shape():
    import glob
    paths = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    if not paths:
        return (ABSENT, "no Claude transcripts on this machine")
    newest = max(paths, key=lambda p: os.stat(p).st_mtime)
    try:
        with open(newest, errors="replace") as handle:
            for line in handle:
                if '"usage"' not in line:
                    continue
                record = json.loads(line)
                usage = (record.get("message") or {}).get("usage") or {}
                missing = [k for k in ("input_tokens", "output_tokens",
                                       "cache_read_input_tokens")
                           if k not in usage]
                return ((DRIFT, f"a transcript usage record is missing "
                                f"{missing}") if missing else
                        (OK, "input, output and cache-read token fields "
                             "all present"))
    except (OSError, ValueError):
        pass
    return (ABSENT, "no usage record found in the newest transcript")


def record(root="."):
    """Write down the versions these answers were true for."""
    path = os.path.join(root, VERSIONS_FILE)
    payload = {
        "_doc": "Runtime versions the assumptions in nxb were last verified "
                "against. `python3 -m nxb doctor` re-checks them. A version "
                "here that no longer matches the machine is not itself a "
                "failure -- it is a reason to run doctor.",
        "verified": versions(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return payload


def report(deep=False, root="."):
    """Print the whole thing. Exit code is 0 only when nothing has drifted."""
    now = versions()
    try:
        with open(os.path.join(root, VERSIONS_FILE), encoding="utf-8") as fh:
            was = json.load(fh).get("verified", {})
    except (OSError, ValueError):
        was = {}

    print("runtimes")
    for name, current in now.items():
        before = was.get(name)
        moved = before and before != current
        print(f"  {name:8s} {current}"
              + (f"   (was {before} when last verified)" if moved else ""))
    for name in was:
        if name not in now:
            print(f"  {name:8s} MISSING — was {was[name]}")

    print("\nassumptions")
    results = checks(deep=deep)
    width = max(len(area) for area, _, _ in results)
    for area, status, detail in results:
        mark = {OK: "ok   ", DRIFT: "DRIFT", ABSENT: "--   ",
                WATCH: "watch"}[status]
        print(f"  {mark} {area:{width}s}  {detail}")

    drifted = [a for a, s, _ in results if s == DRIFT]
    print()
    if drifted:
        print(f"{len(drifted)} assumption(s) drifted: {', '.join(drifted)}")
        print("Nothing was changed. Look at what the runtime does now, then "
              "update the code -- guessing is the failure this catches.")
        return 1
    print("no drift. Run this after any runtime update, and after any "
          "release you hear about.")
    if not deep:
        print("(--deep also boots each runtime to verify its readiness "
              "marker, and asks Claude for /usage at the cost of one turn.)")
    return 0
