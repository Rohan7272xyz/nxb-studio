"""The context store: an Obsidian-compatible vault with a size discipline. [nxb-081]

WHAT THE MEASUREMENT SAID
-------------------------
docs/CONTEXT-BUDGET-nxb-079.md decomposed the Pact programme's 1.36 billion
Codex input tokens. After the nxb-079 fixes (no polling, fresh context per
task, ceilings) two terms remain that a store can attack:

  * ORIENTATION. A fresh worker re-orients at the start of every task by
    reading: 18M uncached tokens in the first fifteen requests of the 185
    directive turns, about 99K per task, which then ride along on every
    later request of that task (roughly 200M once re-sent).
  * REPLIES. `collect` handed the orchestrator the WHOLE answer: 250 filed
    replies, 6.3M tokens, median 16K characters, one of 3 MB, and every one
    stayed in a long-lived context until compaction.

A store helps ONLY if it changes what enters a long-lived context: a fresh
worker reads a few thousand tokens of state note instead of surveying the
docs, and an orchestrator receives a summary and a path instead of a report.
Done any other way (agents dumping everything into a database and reading it
back) it adds tokens. So the size caps below are the mechanism, not a
nicety, and every read here is bounded.

WHAT WAS EXPLORED, AND WHY THIS SHAPE
-------------------------------------
  * Obsidian itself is a markdown folder. The Local REST API plugin (5.0,
    2026-07) serves MCP at https://127.0.0.1:27124/mcp/ with a bearer token;
    other Obsidian MCP servers wrap the same plugin. For agents ON THIS
    MACHINE that is a network hop to reach files they can already open, and
    a plugin plus a listener in the operator's Obsidian. Not needed; the
    vault here is plain files Obsidian can open directly.
  * Hosted memory layers (mem0 ~6.8K tokens per retrieval call, Zep/Graphiti,
    Letta) retrieve on EVERY TURN. Under this project's cost model each
    retrieval is a tool round-trip that re-sends the whole context: the
    polling pattern nxb-079 removed. Per-task retrieval is the right
    granularity, and stdlib-only is a standing rule here.
  * Life OS ADR-0048 (2026-07-27) chose an FTS5 lexical index over the
    markdown, outside the vault, never the source of truth, fully
    rebuildable, chunked into passages, with no model-written text in the
    index. Measured there against a 9 MB vault: it fixed both scan cost and a
    live wrong answer. That design is reused here on the same reasoning.

LAYOUT (under the vault directory, `~/.nxb/vault` unless NXB_VAULT points
into an Obsidian vault of the operator's choosing)

  rigs/<session>/STATE.md        the orientation note; at most STATE_CAP_CHARS
  rigs/<session>/LOG.md          one line per collected task, appended by nxb
  rigs/<session>/tasks/<id>.md   a task card: summary, worker, path to the report
  reports/<id>.md                the full filed reply
  notes/<key>.md                 anything else, by key

The index lives beside the ledger (`vault-index.db`), not in the vault:
Obsidian reads every file in a vault, and the vault may be git-versioned.
"""

import datetime
import os
import re
import sqlite3

#: Published refusals. See contract/context.json.
CONTEXT_BAD_KEY = "context_bad_key"
CONTEXT_NOTE_TOO_BIG = "context_note_too_big"
CONTEXT_NOT_FOUND = "context_not_found"
CONTEXT_EMPTY_BODY = "context_empty_body"

VAULT_DIRNAME = "vault"
INDEX_DBNAME = "vault-index.db"
VAULT_ENV = "NXB_VAULT"

#: THE CAPS. A state note is what every fresh worker reads first, so it is
#: bounded at about 6K tokens. A get is bounded so that "read the report"
#: cannot silently put 700K tokens into a context; the caller asks for more
#: deliberately. A search returns snippets, never bodies.
STATE_CAP_CHARS = 24_000
#: A map note describes a codebase for a fresh worker: modules, entry
#: points, gotchas. MEASURED on Pact: workers read 967 markdown files
#: against 416 code files; a map is what those reads were looking for.
MAP_CAP_CHARS = 12_000
#: A checkpoint is what a pane writes before it is reset near its ceiling:
#: goal, decisions, done, next. Bounded, or it becomes the context it
#: replaced. [nxb-082]
CHECKPOINT_CAP_CHARS = 8_000
#: The vault's hard limit for a checkpoint. The request asks for about
#: CHECKPOINT_CAP_CHARS; the limit sits above it because MEASURED
#: 2026-09-12 (pact-dev) a worker asked for 8,000 wrote 8,713, was refused,
#: and spent SEVEN full-context requests shaving characters. [RIG-36]
CHECKPOINT_HARD_CAP_CHARS = 12_000
GET_CAP_CHARS = 32_000
VAULT_PATH_FILE = "vault.path"
BASE_FILENAME = "NXB.base"
SUMMARY_CAP_CHARS = 800
SNIPPET_CHARS = 300
SEARCH_LIMIT = 8
PER_KEY_HITS = 2

#: Chunking for the index: a heading section, split further at this size so
#: a hit is a passage rather than a file.
CHUNK_CHARS = 2_000

#: A key is a vault-relative path without the .md: letters, digits, space,
#: dot, dash, underscore, slash. No `..`, no leading slash, no hidden parts.
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*(?:/[A-Za-z0-9][A-Za-z0-9 ._-]*)*$")

#: The SUMMARY paragraph, found anywhere in the head of the text rather than
#: only at its very start. MEASURED on the first live run (demo-qa,
#: 2026-09-12): both workers put a title line ("# Test Report: calc.py")
#: above "## SUMMARY", so a start-anchored match fell back to the head and
#: cut the paragraph at 800 characters mid-list.
_SUMMARY_HEAD = re.compile(
    r"(?:^|\n)\s*(?:#+\s*)?(?:\*\*)?SUMMARY(?:\*\*)?\s*(?:[:\-]\s*|\n\s*)"
    r"(.+?)(?:\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL)
SUMMARY_SEARCH_CHARS = 1_500


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _refuse(reason, detail, **extra):
    out = {"state": "REFUSED", "reason": reason, "detail": detail}
    out.update(extra)
    return out


def vault_path_file(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(ledger)),
                        VAULT_PATH_FILE)


def vault_dir(ledger):
    """Where the vault is: NXB_VAULT, else the `vault.path` file beside the
    ledger, else `vault/` beside the ledger.

    Pointing the vault at a folder INSIDE an Obsidian vault (for example
    `~/Vellum/NXB`) makes every note appear in Obsidian as it is written.
    `context relocate --to <dir>` moves it and records the path in
    `vault.path`, so the Studio service, the MCP servers and the shell agree
    without an environment variable each. The operator's choice, never a
    default: it writes into a vault the operator keeps for other things.
    """
    env = os.environ.get(VAULT_ENV)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    try:
        with open(vault_path_file(ledger), encoding="utf-8") as handle:
            recorded = handle.read().strip()
        if recorded:
            return os.path.abspath(os.path.expanduser(recorded))
    except OSError:
        pass
    return os.path.join(os.path.dirname(os.path.abspath(ledger)), VAULT_DIRNAME)


def index_path(ledger):
    return os.path.join(os.path.dirname(os.path.abspath(ledger)), INDEX_DBNAME)


def state_key(session):
    return f"rigs/{session}/STATE"


def log_key(session):
    return f"rigs/{session}/LOG"


def map_key(work_dir):
    """The map note for a project, keyed by its directory's name."""
    base = os.path.basename(os.path.abspath(os.path.expanduser(
        str(work_dir or "")))) or "project"
    return f"maps/{_safe(base)}"


def checkpoint_key(session, worker):
    """One checkpoint note per pane; each checkpoint replaces the last."""
    short = str(worker or "")
    if short.startswith(f"{session} "):
        short = short[len(session) + 1:]
    return f"rigs/{session}/checkpoints/{_safe(short)}"


def report_key(task_id):
    return f"reports/{_safe(task_id)}"


def card_key(session, task_id):
    return f"rigs/{session}/tasks/{_safe(task_id)}"


def _safe(text):
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in str(text))


_CAPS = {"state": STATE_CAP_CHARS, "map": MAP_CAP_CHARS,
         "checkpoint": CHECKPOINT_HARD_CAP_CHARS}


def _kind_of(key):
    if key.endswith("/STATE"):
        return "state"
    if key.startswith("maps/"):
        return "map"
    if "/checkpoints/" in key:
        return "checkpoint"
    return "note"


def session_of(worker):
    """A worker's rig, from its rig-scoped name (`<session> <name>`). [RIG-20]"""
    name = str(worker or "")
    return name.split(" ", 1)[0] if " " in name else None


def extract_summary(text, cap=SUMMARY_CAP_CHARS):
    """(summary, source). The worker's own SUMMARY paragraph when it wrote
    one, else the head of the text. Never longer than `cap` plus an ellipsis.
    """
    text = str(text or "")
    match = _SUMMARY_HEAD.search(text[:SUMMARY_SEARCH_CHARS + cap])
    if match:
        summary = " ".join(match.group(1).split())
        source = "worker"
    else:
        summary = " ".join(text.split())
        source = "head"
    if len(summary) > cap:
        summary = summary[:cap].rstrip() + "…"
    return summary, source


# ------------------------------------------------------------- frontmatter

def _dump_frontmatter(meta):
    lines = ["---"]
    for key, value in meta.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(_yaml_scalar(v) for v in value)}]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value):
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:+-]+", text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_frontmatter(raw):
    """(meta, body). Only the scalar and bracket-list forms this module
    writes; anything else is returned as an untouched body."""
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    meta = {}
    for line in raw[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [_unquote(v.strip()) for v in value[1:-1].split(",")
                         if v.strip()]
        else:
            meta[key] = _unquote(value)
    return meta, raw[end + 5:]


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


# ------------------------------------------------------------------ vault

class Vault:
    """The store. Files are the truth; the index is a rebuildable cache."""

    def __init__(self, ledger):
        if not ledger or not os.path.isabs(os.path.expanduser(str(ledger))):
            raise ValueError("the context store needs an ABSOLUTE ledger path")
        self.ledger = os.path.expanduser(ledger)
        self.root = vault_dir(self.ledger)
        os.makedirs(self.root, exist_ok=True)
        self._conn = sqlite3.connect(index_path(self.ledger), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self.ensure_base()

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------ keys
    def clean_key(self, key):
        key = str(key or "").strip().strip("/")
        if key.endswith(".md"):
            key = key[:-3]
        if not key or not _KEY.match(key) or ".." in key.split("/"):
            return None
        return key

    def path_for(self, key):
        clean = self.clean_key(key)
        if clean is None:
            raise ValueError(f"not a vault key: {key!r}")
        return os.path.join(self.root, clean + ".md")

    def _key_of(self, path):
        rel = os.path.relpath(path, self.root)
        return rel[:-3] if rel.endswith(".md") else rel

    # ----------------------------------------------------------- writes
    def put(self, key, body, *, summary=None, tags=None, author=None,
            kind=None, cap=None):
        """Write a note whole. Refuses an empty body and a state note over
        its cap: the cap is the reason the note is worth reading."""
        clean = self.clean_key(key)
        if clean is None:
            return _refuse(CONTEXT_BAD_KEY,
                           f"{key!r} is not a vault key: letters, digits, "
                           f"space, dot, dash, underscore and slash, no '..'.")
        text = str(body or "")
        if not text.strip():
            return _refuse(CONTEXT_EMPTY_BODY, "the note body is empty.")
        kind = kind or _kind_of(clean)
        limit = cap if cap is not None else _CAPS.get(kind)
        if limit and len(text) > limit:
            return _refuse(
                CONTEXT_NOTE_TOO_BIG,
                f"{clean} is {len(text)} characters; a {kind} note is at "
                f"most {limit}. Every fresh worker reads it first, so it "
                f"must stay small.",
                remedy=["move detail into its own note (notes/<key>) and "
                        "link it from here", "keep this note to what a "
                        "worker needs to orient: what exists, what is done, "
                        "what is open, where things are"])
        if summary is None:
            summary, _ = extract_summary(text, cap=240)
        meta = {"key": clean, "kind": kind, "updated_at": _now(),
                "author": author, "tags": list(tags or []),
                "summary": summary}
        path = self.path_for(clean)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(_dump_frontmatter(meta))
            handle.write(text)
        os.replace(tmp, path)
        self._index_file(path)
        self._conn.commit()
        return {"state": "WRITTEN", "key": clean, "path": path,
                "chars": len(text), "kind": kind, "summary": summary}

    def append(self, key, line, *, kind="log"):
        """Append one line to a note, creating it. For the task log."""
        clean = self.clean_key(key)
        if clean is None:
            return _refuse(CONTEXT_BAD_KEY, f"{key!r} is not a vault key.")
        path = self.path_for(clean)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = " ".join(str(line or "").split())
        if not text:
            return _refuse(CONTEXT_EMPTY_BODY, "nothing to append.")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(_dump_frontmatter(
                    {"key": clean, "kind": kind, "updated_at": _now(),
                     "summary": "appended by nxb, one line per event"}))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
        self._index_file(path)
        self._conn.commit()
        return {"state": "APPENDED", "key": clean, "path": path}

    # ------------------------------------------------------------ reads
    def get(self, key, *, max_chars=GET_CAP_CHARS, offset=0):
        """A note's body, BOUNDED. `truncated` says there is more, and the
        path says where; `offset` reads the rest deliberately."""
        clean = self.clean_key(key)
        if clean is None:
            return _refuse(CONTEXT_BAD_KEY, f"{key!r} is not a vault key.")
        path = self.path_for(clean)
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError:
            return _refuse(CONTEXT_NOT_FOUND, f"no note at {clean}.",
                           path=path)
        meta, body = _parse_frontmatter(raw)
        total = len(body)
        offset = max(0, int(offset or 0))
        limit = max(1, int(max_chars or GET_CAP_CHARS))
        piece = body[offset:offset + limit]
        return {"state": "NOTE", "key": clean, "path": path, "meta": meta,
                "body": piece, "chars": total, "offset": offset,
                "truncated": offset + len(piece) < total,
                **({"next_offset": offset + len(piece)}
                   if offset + len(piece) < total else {})}

    def state(self, session):
        """The rig's orientation note, or an honest MISSING with how to
        create it. Read by every fresh worker before anything else."""
        out = self.get(state_key(session))
        if out["state"] == "NOTE":
            return out
        return {"state": "MISSING", "key": state_key(session),
                "path": self.path_for(state_key(session)),
                "detail": (f"rig {session!r} has no state note yet. Workers "
                           f"will orient by reading the docs until the "
                           f"orchestrator writes one."),
                "write_with": (f"python3 -m nxb context put --key "
                               f"{state_key(session)} --file <note.md>"),
                "cap_chars": STATE_CAP_CHARS}

    def list(self, prefix=""):
        self.refresh()
        prefix = str(prefix or "").strip("/")
        rows = self._conn.execute(
            "SELECT key, kind, updated_at, chars, summary FROM docs "
            "WHERE key LIKE ? ORDER BY updated_at DESC",
            (prefix + "%",)).fetchall()
        return {"state": "LIST", "prefix": prefix, "count": len(rows),
                "notes": [dict(r) for r in rows], "root": self.root}

    # ----------------------------------------------------------- search
    def search(self, query, *, limit=SEARCH_LIMIT, prefix=None,
               snippet_chars=SNIPPET_CHARS):
        """Passages that match, as SNIPPETS with keys. Never a body.

        Lexical (FTS5, porter stemming). The querier is a model: it picks
        the terms, sees labelled results and can search again, which is
        the cheap half of a hybrid (ADR-0048's argument, reused). At most
        PER_KEY_HITS hits per note so one long note cannot take every slot.
        """
        self.refresh()
        terms = [t for t in re.findall(r"[\w'.-]+", str(query or "")) if t]
        if not terms:
            return {"state": "EMPTY", "query": query, "hits": [],
                    "detail": "no searchable terms in the query"}
        limit = max(1, min(int(limit or SEARCH_LIMIT), 50))
        words = int(max(6, snippet_chars // 10))
        sql = ("SELECT key, heading, snippet(chunks, 2, '[', ']', '…', ?) "
               "AS snip, bm25(chunks, 0.0, 2.0, 1.0) AS rank FROM chunks "
               "WHERE chunks MATCH ? ORDER BY rank LIMIT ?")
        hits = []
        for expression in (" AND ".join(f'"{t}"' for t in terms),
                           " OR ".join(f'"{t}"' for t in terms)):
            try:
                # A wide candidate window, then the per-note cap in Python:
                # one long note with forty matching passages would
                # otherwise fill a narrow window before any other note
                # appeared.
                rows = self._conn.execute(sql, (words, expression,
                                                400)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            seen = {}
            hits = []
            for r in rows:
                if prefix and not r["key"].startswith(str(prefix).strip("/")):
                    continue
                if seen.get(r["key"], 0) >= PER_KEY_HITS:
                    continue
                seen[r["key"]] = seen.get(r["key"], 0) + 1
                snip = " ".join(r["snip"].split())
                hits.append({"key": r["key"], "heading": r["heading"],
                             "snippet": snip[:snippet_chars + 20],
                             "path": self.path_for(r["key"])})
                if len(hits) >= limit:
                    break
            if hits:
                break
        return {"state": "HITS" if hits else "EMPTY", "query": query,
                "count": len(hits), "hits": hits,
                "next": ("read one with get(key) (bounded) or narrow the "
                         "terms" if hits else
                         "no passage matched every term or any term; try "
                         "other words")}

    def patch(self, key, section, body, *, append=False, author=None):
        """Replace (or append to) ONE heading section of a note. [nxb-082]

        The orchestrator updates its state note after every task; rewriting
        a 24,000-character note to change its Done list costs about 6K
        output tokens a time. This changes one section for the cost of the
        section. The heading is matched by its text, any level; a missing
        section is added at the end. The note's cap still applies to the
        result, so a patch cannot grow a state note past what a fresh
        worker should read.
        """
        clean = self.clean_key(key)
        if clean is None:
            return _refuse(CONTEXT_BAD_KEY, f"{key!r} is not a vault key.")
        wanted = " ".join(str(section or "").split()).lower()
        if not wanted:
            return _refuse(CONTEXT_BAD_KEY, "a section heading is required.")
        text = str(body or "")
        if not text.strip():
            return _refuse(CONTEXT_EMPTY_BODY, "nothing to put in the section.")
        current = self.get(clean, max_chars=10 ** 9)
        if current["state"] != "NOTE":
            return current
        meta, old = current["meta"], current["body"]
        lines = old.splitlines()
        start = end = None
        for i, line in enumerate(lines):
            if not line.startswith("#"):
                continue
            level = len(line) - len(line.lstrip("#"))
            title = " ".join(line.lstrip("#").split()).lower()
            if start is None:
                if title == wanted:
                    start, start_level = i, level
                continue
            if level <= start_level:
                end = i
                break
        new_body = text.rstrip("\n") + "\n"
        if start is None:
            heading = f"## {' '.join(str(section).split())}"
            merged = old.rstrip("\n") + f"\n\n{heading}\n{new_body}"
            action = "ADDED"
        else:
            end = len(lines) if end is None else end
            kept = lines[start + 1:end]
            inner = ("\n".join(kept).rstrip("\n") + "\n" + new_body
                     if append else new_body)
            merged = "\n".join(lines[:start + 1]) + "\n" + inner
            rest = lines[end:]
            if rest:
                merged = merged.rstrip("\n") + "\n\n" + "\n".join(rest)
            action = "APPENDED" if append else "REPLACED"
        out = self.put(clean, merged, summary=meta.get("summary"),
                       tags=meta.get("tags"), author=author or meta.get("author"),
                       kind=meta.get("kind"))
        if out.get("state") == "WRITTEN":
            out.update(state="PATCHED", action=action, section=section)
        return out

    def map(self, work_dir):
        """The project's map note, or MISSING with how to write one."""
        key = map_key(work_dir)
        out = self.get(key)
        if out["state"] == "NOTE":
            return out
        return {"state": "MISSING", "key": key, "path": self.path_for(key),
                "detail": (f"no map note for {work_dir}. Workers will read "
                           f"the code and docs to orient until one exists."),
                "write_with": f"python3 -m nxb context put --key {key} "
                              f"--file <map.md>",
                "cap_chars": MAP_CAP_CHARS}

    def checkpoint(self, session, worker):
        """A pane's last checkpoint, or MISSING."""
        key = checkpoint_key(session, worker)
        out = self.get(key)
        if out["state"] == "NOTE":
            return out
        return {"state": "MISSING", "key": key, "path": self.path_for(key)}

    def ensure_base(self):
        """Write the Obsidian Base (the dashboard) once, if absent. [nxb-082]

        MEASURED on Pact: 59 operator and chairman status-style turns cost
        1,224 requests and 150M input tokens, 11 percent of the run, to ask
        orchestrators where things stood. A Base over the task cards' and
        state notes' frontmatter answers that in Obsidian for no tokens.
        Never overwritten: the operator may have edited its views.
        """
        path = os.path.join(self.root, BASE_FILENAME)
        if os.path.exists(path):
            return {"state": "PRESENT", "path": path}
        os.makedirs(self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(OBSIDIAN_BASE)
        return {"state": "WRITTEN", "path": path}

    def relocate(self, new_root):
        """Move the vault to `new_root` (for example a folder inside an
        Obsidian vault) and record it in `vault.path` beside the ledger, so
        every nxb process finds it without an environment variable."""
        import shutil
        target = os.path.abspath(os.path.expanduser(str(new_root or "")))
        if not target or target == self.root:
            return _refuse(CONTEXT_BAD_KEY, "a different directory is needed.")
        if os.path.isdir(target) and os.listdir(target):
            return _refuse(CONTEXT_BAD_KEY,
                           f"{target} exists and is not empty; nxb will not "
                           f"merge into it.", remedy=["choose an empty or "
                                                      "new folder"])
        os.makedirs(target, exist_ok=True)
        moved = 0
        for name in os.listdir(self.root):
            shutil.move(os.path.join(self.root, name),
                        os.path.join(target, name))
            moved += 1
        old_root = self.root
        with open(vault_path_file(self.ledger), "w", encoding="utf-8") as handle:
            handle.write(target + "\n")
        self.root = target
        self.reindex()
        return {"state": "RELOCATED", "from": old_root, "to": target,
                "entries_moved": moved,
                "recorded_in": vault_path_file(self.ledger),
                "obsidian": "if this folder is inside an Obsidian vault the "
                            "notes and the NXB.base dashboard are visible "
                            "there now"}

    # ------------------------------------------------------------ index
    def _ensure_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS docs (
            key        TEXT PRIMARY KEY,
            kind       TEXT,
            mtime_ns   INTEGER NOT NULL,
            size       INTEGER NOT NULL,
            chars      INTEGER NOT NULL,
            updated_at TEXT,
            summary    TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            key UNINDEXED, heading, body, tokenize = 'porter unicode61');
        """)
        self._conn.commit()

    def _index_file(self, path):
        try:
            stat = os.stat(path)
            with open(path, encoding="utf-8", errors="replace") as handle:
                raw = handle.read()
        except OSError:
            return False
        key = self._key_of(path)
        meta, body = _parse_frontmatter(raw)
        self._conn.execute("DELETE FROM chunks WHERE key = ?", (key,))
        for heading, text in _chunks(body):
            self._conn.execute(
                "INSERT INTO chunks (key, heading, body) VALUES (?,?,?)",
                (key, heading, text))
        self._conn.execute(
            "INSERT INTO docs (key, kind, mtime_ns, size, chars, updated_at, "
            "summary) VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "kind = excluded.kind, mtime_ns = excluded.mtime_ns, "
            "size = excluded.size, chars = excluded.chars, "
            "updated_at = excluded.updated_at, summary = excluded.summary",
            (key, meta.get("kind"), stat.st_mtime_ns, stat.st_size,
             len(body), meta.get("updated_at"), meta.get("summary")))
        return True

    def refresh(self, budget=200):
        """Bring the index up to date with the files, within a budget.

        ADR-0048's staleness sweep: stat the tree, compare (mtime_ns, size)
        with the manifest, reindex what changed, drop what vanished, and say
        how many files are still behind rather than making a caller wait.
        """
        known = {r["key"]: (r["mtime_ns"], r["size"]) for r in
                 self._conn.execute("SELECT key, mtime_ns, size FROM docs")}
        seen, changed, stale = set(), 0, 0
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if not name.endswith(".md") or name.startswith("."):
                    continue
                path = os.path.join(base, name)
                key = self._key_of(path)
                seen.add(key)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                if known.get(key) == (stat.st_mtime_ns, stat.st_size):
                    continue
                if changed >= budget:
                    stale += 1
                    continue
                if self._index_file(path):
                    changed += 1
        gone = [k for k in known if k not in seen]
        for key in gone:
            self._conn.execute("DELETE FROM chunks WHERE key = ?", (key,))
            self._conn.execute("DELETE FROM docs WHERE key = ?", (key,))
        self._conn.commit()
        return {"state": "FRESH" if not stale else "BEHIND",
                "reindexed": changed, "removed": len(gone), "stale": stale,
                "notes": len(seen)}

    def reindex(self):
        """Rebuild from the files. Always safe: the index is a cache."""
        self._conn.execute("DELETE FROM chunks")
        self._conn.execute("DELETE FROM docs")
        self._conn.commit()
        return self.refresh(budget=10 ** 9)


def _chunks(body):
    """(heading, text) passages: heading sections, split at CHUNK_CHARS."""
    heading, buf, out = "", [], []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            for i in range(0, len(text), CHUNK_CHARS):
                out.append((heading, text[i:i + CHUNK_CHARS]))
        buf.clear()
    for line in str(body or "").splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()[:120]
            continue
        buf.append(line)
    flush()
    return out


# ------------------------------------------------------------- reports

def task_cost(ledger, *, task_id, worker, session=None):
    """{took_min, checkpoints} for a task: minutes since it was minted and
    how many checkpoint resets its worker took while holding it. Read from
    the ledger and the rig record; the numbers the operator asks for after
    every task ("how long did that take") should be free. [RIG-38]"""
    import datetime
    import sqlite3
    out = {"took_min": None, "checkpoints": 0}
    try:
        conn = sqlite3.connect(ledger)
        try:
            row = conn.execute("SELECT issued_at FROM issued_tasks WHERE "
                               "task_id = ?", (task_id,)).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            then = datetime.datetime.fromisoformat(
                str(row[0]).replace("Z", "+00:00"))
            out["took_min"] = int((datetime.datetime.now(datetime.timezone.utc)
                                   - then).total_seconds() // 60)
    except (sqlite3.Error, ValueError, TypeError):
        pass
    if session:
        from nxb.keystroke import load_rig
        for rec in (load_rig(ledger, session) or {}).get("panes", []):
            if rec.get("name") == worker and rec.get("checkpoint_task") == task_id:
                out["checkpoints"] = int(rec.get("checkpoints") or 0)
    return out


def record_report(ledger, *, task_id, worker, answer, session=None):
    """File a collected answer as a report, a task card and a log line.

    Called by `collect` when an answer is longer than what it will put
    into the orchestrator's context inline. Idempotent: a second collect of
    the same task rewrites nothing that already matches.
    """
    session = session or session_of(worker) or "unrigged"
    summary, source = extract_summary(answer)
    cost = task_cost(ledger, task_id=task_id, worker=worker, session=session)
    vault = Vault(ledger)
    try:
        rkey = report_key(task_id)
        path = vault.path_for(rkey)
        text = str(answer or "")
        existing = None
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    existing = _parse_frontmatter(handle.read())[1]
            except OSError:
                existing = None
        if existing is None or existing.rstrip("\n") != text.rstrip("\n"):
            vault.put(rkey, text, summary=summary, kind="report",
                      author=worker,
                      tags=["report", session, task_id])
            vault.put(card_key(session, task_id),
                      f"{summary}\n\nWorker: {worker}\nTask: {task_id}\n"
                      f"Full report: [[{rkey}]] ({path})\n",
                      summary=summary, kind="card", author="nxb",
                      tags=["task", session])
            took = (f"took {cost['took_min']} min"
                    if cost.get("took_min") is not None else "took ? min")
            vault.append(log_key(session),
                         f"- {_now()} {worker} {task_id}: "
                         f"{summary[:160]} -> {rkey} ({took}, "
                         f"{cost.get('checkpoints', 0)} checkpoints)")
        return {"path": path, "key": rkey, "summary": summary,
                "summary_source": source,
                "card": card_key(session, task_id), "session": session,
                "took_min": cost.get("took_min"),
                "checkpoints": cost.get("checkpoints", 0)}
    finally:
        vault.close()


def orientation_line(ledger, session, work_dir=None):
    """The sentence a directive carries when the rig has a state note, and
    the project a map note.

    Present only when the notes EXIST, so a fresh rig's directives read as
    before and a worker is never sent to a note that is not there.
    """
    if not ledger or not session:
        return None
    vault = Vault(ledger)
    try:
        path = vault.path_for(state_key(session))
        map_path = vault.path_for(map_key(work_dir)) if work_dir else None
    finally:
        vault.close()
    if not os.path.isfile(path):
        return None
    line = (f"ORIENT FIRST: your rig's state note is at {path}. Read it "
            f"before reading anything else; it says what exists, what is "
            f"done and where things are, and it replaces a survey of the "
            f"documents.")
    if map_path and os.path.isfile(map_path):
        line += (f" The project's map is at {map_path}: modules, entry "
                 f"points and gotchas; read it instead of exploring, and "
                 f"say in your report if it is wrong.")
    return line


#: The Obsidian Base written into a new vault. Bases are YAML; this one
#: gives three views over the frontmatter nxb writes: every task card by
#: rig, every state note, every checkpoint. See ensure_base.
OBSIDIAN_BASE = """# NXB dashboard. Written once by nxb (context store, nxb-082); edit freely,
# nxb never overwrites it. Three views over the frontmatter nxb writes.
properties:
  note.summary:
    displayName: Summary
  note.author:
    displayName: Who
  note.updated_at:
    displayName: Updated
  note.kind:
    displayName: Kind
  note.key:
    displayName: Key
views:
  - type: table
    name: Tasks
    filters:
      and:
        - file.inFolder("rigs")
        - note.kind == "card"
    order:
      - file.name
      - note.author
      - note.updated_at
      - note.summary
  - type: table
    name: State notes
    filters:
      and:
        - file.inFolder("rigs")
        - note.kind == "state"
    order:
      - note.key
      - note.updated_at
      - note.summary
  - type: table
    name: Checkpoints
    filters:
      and:
        - file.inFolder("rigs")
        - note.kind == "checkpoint"
    order:
      - note.key
      - note.author
      - note.updated_at
      - note.summary
  - type: table
    name: Reports
    filters:
      and:
        - file.inFolder("reports")
    order:
      - file.name
      - note.author
      - note.updated_at
      - note.summary
"""
