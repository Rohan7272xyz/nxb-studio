"""What the fleet has actually cost, read from each runtime's own records.

WHY THIS EXISTS: Rohan designs fleets around headroom. "if i have lower usage
on claude but high usage on codex ill design it with that in mind." A composer
that cannot show him that is asking him to choose blind.

WHAT IS REAL, AND WHAT IS NOT. Measured 2026-09-03, before any of this was
built, because a fabricated usage figure is worse than none: he would design
against it.

  * CODEX PLAN USAGE: REAL. Every rollout under ~/.codex/sessions carries a
    `rate_limits` record with `used_percent`, `window_minutes`, `resets_at`
    and `plan_type`. Read from the newest session, which is the freshest
    reading the machine holds.
  * CLAUDE PLAN USAGE: REAL, BUT IT COSTS A TURN TO ASK. Nothing on disk
    holds it -- the only `rate_limit` string in a transcript is a 429 ERROR
    record. But `claude -p "/usage"` answers headlessly with MORE than Codex
    records: session, week, and per-model. Rohan proposed a standing session
    on another machine to poll it; that is not needed, and the reason it is
    not polled at all is cost. Every call is a full runtime turn, which this
    project already measured at roughly 13k input tokens before the prompt is
    even considered. Polling quota would spend quota. So it is fetched ON
    DEMAND and the reading is CACHED WITH ITS AGE, because a percentage
    without a timestamp is a number the operator cannot weigh.
  * TOKENS, BOTH RUNTIMES: REAL, from the transcripts each runtime writes.

TOKENS ARE NOT A PERCENTAGE, and the two must not be blurred. Consumption may
be plan quota rather than per-token billing, so this counts tokens and never
converts them to money or to a fraction of a limit -- the same rule this
project already holds for canary cost.
"""

import glob
import json
import os
import re
import threading
import time

CLAUDE_GLOB = "~/.claude/projects/*/*.jsonl"
CODEX_GLOB = "~/.codex/sessions/*/*/*/rollout-*.jsonl"

#: Why Claude's percentage is missing, carried in the payload so the UI states
#: it rather than rendering an empty gauge that looks like zero.
CLAUDE_LIMIT_ABSENT = (
    "Claude writes no usage figure to disk, so this is asked for directly and "
    "cached with its age. Each refresh costs one Claude turn, which is why it "
    "is a button and not a poll."
)

_EMPTY = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

#: `Current week (all models): 74% used · resets Sep 5 at 12pm (America/...)`
_USAGE_LINE = re.compile(
    r"^Current\s+(?P<window>session|week[^:]*):\s*(?P<pct>\d+)%\s*used"
    r"(?:\s*[·-]\s*resets\s*(?P<resets>[^(\n]+))?", re.M)


def claude_plan_usage(timeout=90):
    """Ask Claude Code for its own usage. COSTS ONE TURN; never on a timer.

    Parsed from the human-readable answer, which is the only surface there is.
    That makes it a text contract with a vendor's UI, so a shape change breaks
    parsing rather than producing a wrong number: an unparsed line is dropped,
    and a reading with no windows at all is returned as an error rather than
    as zero.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["claude", "-p", "/usage", "--output-format", "text"],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"could not ask claude: {exc}"}
    text = proc.stdout or ""
    windows = {}
    for match in _USAGE_LINE.finditer(text):
        label = " ".join(match.group("window").split())
        windows[label] = {"used_percent": int(match.group("pct")),
                          "resets": (match.group("resets") or "").strip()}
    if not windows:
        return {"error": "claude answered, and no usage line could be parsed. "
                         "Its /usage wording may have changed.",
                "raw": text.strip()[:400]}
    return {"windows": windows, "read_at": time.time(),
            "note": "asked directly; each refresh costs one Claude turn"}


def _add(into, other):
    for k in _EMPTY:
        into[k] = into.get(k, 0) + other.get(k, 0)
    return into


def _claude_file(path):
    """{day: totals} for one Claude transcript."""
    days = {}
    with open(path, errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            usage = (record.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue
            day = str(record.get("timestamp") or "")[:10]
            if not day:
                continue
            _add(days.setdefault(day, dict(_EMPTY)), {
                "input": usage.get("input_tokens") or 0,
                "output": usage.get("output_tokens") or 0,
                "cache_read": usage.get("cache_read_input_tokens") or 0,
                "cache_write": usage.get("cache_creation_input_tokens") or 0})
    return days


def _codex_file(path):
    """{day: totals} for one Codex rollout, plus its newest rate_limits.

    Sums `last_token_usage`, which is the DELTA for that turn.
    `total_token_usage` is cumulative for the session, so adding those up
    would count every earlier turn again, once per turn.
    """
    days, limits, seen_at = {}, None, ""
    with open(path, errors="replace") as handle:
        for line in handle:
            if "token_count" not in line and "rate_limits" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") or {}
            stamp = str(record.get("timestamp") or "")
            if payload.get("rate_limits") and stamp >= seen_at:
                limits, seen_at = payload["rate_limits"], stamp
            info = payload.get("info") or {}
            last = info.get("last_token_usage")
            if isinstance(last, dict) and stamp[:10]:
                _add(days.setdefault(stamp[:10], dict(_EMPTY)), {
                    "input": last.get("input_tokens") or 0,
                    "output": last.get("output_tokens") or 0,
                    "cache_read": last.get("cached_input_tokens") or 0,
                    "cache_write": last.get("cache_write_input_tokens") or 0})
    return days, limits, seen_at


class Usage:
    """Incremental scanner. A file is re-read only when it changes.

    MEASURED: the corpus is 3.2 GB over ~1200 files and reads at ~800 MB/s, so
    a cold scan is about 4 seconds and a warm one touches only the sessions
    that moved. Held behind a lock and refreshed on a worker thread, because a
    4-second stall inside an HTTP handler that a page polls every 5 seconds is
    its own kind of outage.
    """

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.files = {}          # path -> {"key": (mtime,size), "days": {...}}
        self.snapshot = None
        self.claude = None       # last /usage reading, with its age
        self.busy = False
        self._load()

    # ----------------------------------------------------------- persistence
    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.files = {k: {"key": tuple(v["key"]), "days": v["days"]}
                          for k, v in saved.get("files", {}).items()}
            self.snapshot = saved.get("snapshot")
            self.claude = saved.get("claude")
        except (OSError, ValueError, KeyError, TypeError):
            self.files = {}

    def _save(self):
        tmp = self.cache_path + ".tmp"
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"files": {k: {"key": list(v["key"]), "days": v["days"]}
                                 for k, v in self.files.items()},
                       "snapshot": self.snapshot,
                       "claude": self.claude}, handle)
        os.replace(tmp, self.cache_path)

    # --------------------------------------------------------------- scanning
    def refresh(self):
        limits, newest = None, ""
        totals = {"claude_code": {}, "codex": {}}
        for runtime, pattern, reader in (
                ("claude_code", CLAUDE_GLOB, _claude_file),
                ("codex", CODEX_GLOB, _codex_file)):
            for path in glob.glob(os.path.expanduser(pattern)):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                key = (int(stat.st_mtime), stat.st_size)
                cached = self.files.get(path)
                if cached and tuple(cached["key"]) == key:
                    days = cached["days"]
                else:
                    try:
                        result = reader(path)
                    except OSError:
                        continue
                    if runtime == "codex":
                        days, found, stamp = result
                        if found and stamp >= newest:
                            limits, newest = found, stamp
                    else:
                        days = result
                    self.files[path] = {"key": key, "days": days}
                if runtime == "codex" and cached:
                    # A cached file's limits are stale by definition; only the
                    # newest session's reading is worth anything, and that file
                    # is the one that keeps changing.
                    pass
                for day, counts in days.items():
                    _add(totals[runtime].setdefault(day, dict(_EMPTY)), counts)

        # The freshest rate-limit reading lives in the most recently touched
        # rollout, cached or not, so it is read directly rather than harvested
        # during the walk above.
        limits = _newest_codex_limits() or limits
        self.snapshot = {"tokens": _windows(totals), "limits": {
            "codex": limits,
            "claude_code": self.claude,
            "claude_code_reason": CLAUDE_LIMIT_ABSENT},
            "computed_at": time.time()}
        try:
            self._save()
        except OSError:
            pass
        return self.snapshot

    def refresh_async(self):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                with self.lock:
                    self.refresh()
            finally:
                self.busy = False

        threading.Thread(target=run, daemon=True).start()

    def read(self):
        """NEVER BLOCKS. A cold scan is ~5.5 seconds and this is polled by a
        page, so a first call that waits for it is a hang the operator cannot
        distinguish from a dead server. The first call starts the scan and
        says it is computing; the next poll has the answer.

        Caught by a test that timed out rather than by anyone reasoning about
        it, which is the only reason the blocking version did not ship.
        """
        self.refresh_async()
        if self.snapshot is None:
            return {"tokens": {}, "limits": {"codex": _newest_codex_limits(),
                                             "claude_code": self.claude,
                                             "claude_code_reason":
                                                 CLAUDE_LIMIT_ABSENT},
                    "computing": True}
        snap = dict(self.snapshot, computing=self.busy)
        snap["limits"] = dict(snap["limits"], claude_code=self.claude)
        return snap

    def ask_claude(self):
        """Refresh the Claude reading. Explicit, because it costs a turn."""
        reading = claude_plan_usage()
        if "error" not in reading:
            self.claude = reading
            try:
                self._save()
            except OSError:
                pass
        return reading


def _newest_codex_limits():
    paths = glob.glob(os.path.expanduser(CODEX_GLOB))
    if not paths:
        return None
    newest = max(paths, key=lambda p: os.stat(p).st_mtime)
    try:
        _, limits, _ = _codex_file(newest)
    except OSError:
        return None
    return limits


def _windows(totals):
    """today / 7 days / all, per runtime. Days are the runtimes' own stamps."""
    import datetime
    today = datetime.datetime.now(datetime.timezone.utc).date()
    week = {str(today - datetime.timedelta(days=i)) for i in range(7)}
    out = {}
    for runtime, days in totals.items():
        buckets = {"today": dict(_EMPTY), "week": dict(_EMPTY),
                   "all": dict(_EMPTY)}
        for day, counts in days.items():
            _add(buckets["all"], counts)
            if day in week:
                _add(buckets["week"], counts)
            if day == str(today):
                _add(buckets["today"], counts)
        for bucket in buckets.values():
            bucket["total"] = sum(bucket[k] for k in _EMPTY)
        out[runtime] = buckets
    return out
