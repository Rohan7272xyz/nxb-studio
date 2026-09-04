"""Durable Studio drafts shared by the page and every MCP client.

The first Studio kept drafts in browser ``localStorage``.  That made the
drawing private to one browser profile: an MCP-speaking orchestrator could
describe a useful fleet but could not put it on the canvas, and even a second
browser could not see it.  Drafts are NXB state, so they now live beside the
ledger and both surfaces use this module.

One JSON file per draft keeps independent workflows independent.  Writes are
atomic, updates are compare-and-swap by revision, and deletion moves the file
to a trash directory.  An LLM therefore cannot silently overwrite a newer
human edit or permanently erase a design merely by calling the wrong tool.
"""

import contextlib
import datetime
import fcntl
import json
import math
import os
import re
import secrets

from nxb.rig import RUNTIME_ALIASES, compose_agents


DIRNAME = "studio-drafts"
TRASH = "trash"
SCHEMA_VERSION = 1
LAYOUTS = ("main-horizontal", "main-vertical", "tiled",
           "even-horizontal", "even-vertical")
ROLES = ("worker", "orchestrator")
RUNTIMES = ("claude_code", "codex")

_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_BAD_SESSION = " \t:.$'\"\\"


class DraftError(ValueError):
    """A draft request is invalid or names no stored draft."""


class DraftConflict(DraftError):
    """The caller tried to replace a revision it did not read."""


def directory(ledger):
    return os.path.join(os.path.dirname(ledger), DIRNAME)


def _path(ledger, draft_id):
    if not _ID.fullmatch(str(draft_id or "")):
        raise DraftError("draft_id must contain only letters, numbers, _ or -")
    return os.path.join(directory(ledger), str(draft_id) + ".json")


@contextlib.contextmanager
def _locked(ledger):
    root = directory(ledger)
    os.makedirs(root, mode=0o700, exist_ok=True)
    lock_path = os.path.join(root, ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise DraftError(f"cannot read draft {os.path.basename(path)!r}: {exc}")
    if not isinstance(value, dict):
        raise DraftError(f"draft {os.path.basename(path)!r} is not an object")
    return value


def _records_unlocked(ledger):
    root = directory(ledger)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            record = _read(os.path.join(root, name))
        except DraftError:
            continue                    # one damaged draft hides only itself
        if record and record.get("draft_id"):
            out.append(record)
    out.sort(key=lambda d: (d.get("updated_at", ""), d.get("session", "")),
             reverse=True)
    return out


def list_drafts(ledger):
    """Return every readable draft, newest first."""
    with _locked(ledger):
        return _records_unlocked(ledger)


def get_draft(ledger, draft_id):
    with _locked(ledger):
        record = _read(_path(ledger, draft_id))
    if record is None:
        raise DraftError(f"no Studio draft {draft_id!r}")
    return record


def _text(value, field, *, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DraftError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise DraftError(f"{field} is required")
    return value


def _number(value, field, default):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DraftError(f"{field} must be a finite number")
    if not math.isfinite(value):
        raise DraftError(f"{field} must be a finite number")
    return round(value)


def _positions(agents):
    workers = [a for a in agents if a["role"] != "orchestrator"]
    worker_index = {id(a): i for i, a in enumerate(workers)}
    total = max(1, len(workers))
    for agent in agents:
        if agent["role"] == "orchestrator":
            default_x, default_y = round((total - 1) * 250 / 2) + 60, 60
        else:
            default_x = 60 + worker_index[id(agent)] * 250
            default_y = 300
        agent["x"] = _number(agent.get("x"),
                             f"{agent['name'] or 'agent'}.x", default_x)
        agent["y"] = _number(agent.get("y"),
                             f"{agent['name'] or 'agent'}.y", default_y)


def normalize(spec, *, strict=True):
    """Return the canonical, provider-neutral draft shape.

    ``strict`` is used by MCP: the result must be launchable in structure
    (although directories and account access are deliberately checked only at
    launch).  The browser uses non-strict writes because a half-typed name or
    an empty new tab is still a legitimate draft.
    """
    if not isinstance(spec, dict):
        raise DraftError("a Studio draft must be an object")
    session = _text(spec.get("session"), "session", required=strict)
    if strict and any(c in session for c in _BAD_SESSION):
        raise DraftError("session may not contain spaces, colons, dots, dollar "
                         "signs, quotes or backslashes")
    work_dir = _text(spec.get("working_directory", "~"),
                     "working_directory") or "~"
    layout = _text(spec.get("layout", "main-horizontal"), "layout")
    if layout not in LAYOUTS:
        raise DraftError(f"unknown layout {layout!r}; choose one of {LAYOUTS}")
    raw_agents = spec.get("agents", [])
    if not isinstance(raw_agents, list):
        raise DraftError("agents must be an array")

    agents = []
    used_ids = set()
    next_id = 1
    for i, raw in enumerate(raw_agents):
        if not isinstance(raw, dict):
            raise DraftError(f"agents[{i}] must be an object")
        name = _text(raw.get("name"), f"agents[{i}].name", required=strict)
        role = _text(raw.get("role", "worker"), f"agents[{i}].role") or "worker"
        if role not in ROLES:
            raise DraftError(f"agents[{i}].role must be worker or orchestrator")
        runtime_raw = _text(raw.get("runtime"), f"agents[{i}].runtime",
                            required=strict)
        runtime = RUNTIME_ALIASES.get(runtime_raw.lower(), runtime_raw)
        if runtime not in RUNTIMES:
            raise DraftError(f"unknown runtime {runtime_raw!r}; choose one of "
                             f"{RUNTIMES}")
        node_id = raw.get("node_id")
        if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id < 1:
            while next_id in used_ids:
                next_id += 1
            node_id = next_id
        if node_id in used_ids:
            raise DraftError(f"two agents use node_id {node_id}")
        used_ids.add(node_id)
        next_id = max(next_id, node_id + 1)
        agent = {"node_id": node_id, "name": name, "role": role,
                 "runtime": runtime}
        for public, field in (("model", "model"), ("effort", "effort"),
                              ("working_directory", "working_directory"),
                              ("instructions", "instructions"),
                              ("deployed_name", "deployed_name")):
            value = _text(raw.get(public), f"agents[{i}].{public}")
            if value:
                agent[field] = value
        if "x" in raw:
            agent["x"] = raw["x"]
        if "y" in raw:
            agent["y"] = raw["y"]
        agents.append(agent)

    _positions(agents)
    if strict:
        # This is the launcher's own validator.  Reusing it means a workflow
        # accepted through MCP cannot fail later because this module invented
        # a second definition of names, runtimes, or orchestrator count.
        launch_agents = [
            {"name": a["name"], "role": a["role"], "runtime": a["runtime"],
             "model": a.get("model"), "effort": a.get("effort"),
             "dir": a.get("working_directory"),
             "instructions": a.get("instructions")}
            for a in agents
        ]
        try:
            compose_agents(launch_agents, layout=layout)
        except ValueError as exc:
            raise DraftError(str(exc)) from exc

    view = spec.get("view") or {}
    if not isinstance(view, dict):
        raise DraftError("view must be an object")
    canonical_view = {
        "zoom": _number(view.get("zoom"), "view.zoom", 1),
        "x": _number(view.get("x"), "view.x", 0),
        "y": _number(view.get("y"), "view.y", 0),
    }
    # Zoom is fractional in the page, so restore it after finite validation.
    if view.get("zoom") is not None:
        canonical_view["zoom"] = float(view["zoom"])
    return {"schema_version": SCHEMA_VERSION, "session": session,
            "working_directory": work_dir, "layout": layout,
            "agents": agents, "view": canonical_view}


def validate(spec):
    """Validate without writing and report launch-time directory warnings."""
    draft = normalize(spec, strict=True)
    warnings = []
    root = os.path.expanduser(draft["working_directory"])
    if not os.path.isdir(root):
        warnings.append(f"rig working directory does not exist yet: {root}")
    for agent in draft["agents"]:
        if agent.get("working_directory"):
            path = os.path.expanduser(agent["working_directory"])
            if not os.path.isdir(path):
                warnings.append(f"{agent['name']} working directory does not "
                                f"exist yet: {path}")
    return {"valid": True, "warnings": warnings, "draft": draft}


def _write_atomic(path, record):
    root = os.path.dirname(path)
    tmp = os.path.join(root, f".{os.path.basename(path)}.{secrets.token_hex(6)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def save_draft(ledger, spec, *, draft_id=None, expected_revision=None,
               source="mcp", strict=True):
    """Create or compare-and-swap a complete draft."""
    canonical = normalize(spec, strict=strict)
    if (expected_revision is not None
            and (isinstance(expected_revision, bool)
                 or not isinstance(expected_revision, int)
                 or expected_revision < 0)):
        raise DraftError("expected_revision must be a non-negative integer")
    if draft_id is None:
        if expected_revision is not None:
            raise DraftError("expected_revision is only for updating a draft")
        draft_id = secrets.token_hex(16)
    path = _path(ledger, draft_id)
    with _locked(ledger):
        current = _read(path)
        if current is None:
            if expected_revision not in (None, 0):
                raise DraftConflict(f"draft {draft_id!r} does not exist; its "
                                    "expected_revision must be 0 to create it")
            revision = 1
            created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        else:
            if expected_revision is None:
                raise DraftConflict("expected_revision is required when updating "
                                    "an existing draft")
            if expected_revision != current.get("revision"):
                raise DraftConflict(
                    f"draft {draft_id!r} is revision {current.get('revision')}, "
                    f"not {expected_revision}; read it again before replacing it")
            revision = int(current.get("revision", 0)) + 1
            created_at = current.get("created_at")
            if strict:
                # Liveness stamps belong to Studio, not to an MCP author.  A
                # read/replace round trip preserves them by node id without
                # advertising a field a model could forge.
                deployed = {a.get("node_id"): a.get("deployed_name")
                            for a in current.get("agents", [])
                            if a.get("deployed_name")}
                for agent in canonical["agents"]:
                    if deployed.get(agent["node_id"]):
                        agent["deployed_name"] = deployed[agent["node_id"]]
        for other in _records_unlocked(ledger):
            if (other.get("draft_id") != draft_id
                    and other.get("session") == canonical["session"]
                    and canonical["session"]):
                raise DraftConflict(
                    f"another draft already uses session {canonical['session']!r}: "
                    f"{other.get('draft_id')}")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = dict(canonical, draft_id=draft_id, revision=revision,
                      created_at=created_at or now, updated_at=now,
                      updated_by=_text(source, "source") or "unknown")
        _write_atomic(path, record)
    return record


def delete_draft(ledger, draft_id, *, expected_revision):
    """Move a draft to trash after a revision check; never erase it."""
    if (isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1):
        raise DraftError("expected_revision must be a positive integer")
    path = _path(ledger, draft_id)
    with _locked(ledger):
        current = _read(path)
        if current is None:
            raise DraftError(f"no Studio draft {draft_id!r}")
        if expected_revision != current.get("revision"):
            raise DraftConflict(
                f"draft {draft_id!r} is revision {current.get('revision')}, not "
                f"{expected_revision}; read it again before deleting it")
        trash = os.path.join(directory(ledger), TRASH)
        os.makedirs(trash, mode=0o700, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ")
        destination = os.path.join(trash, f"{draft_id}.{stamp}.json")
        os.replace(path, destination)
    return {"state": "TRASHED", "draft_id": draft_id,
            "revision": current.get("revision"),
            "recoverable_from": destination}
