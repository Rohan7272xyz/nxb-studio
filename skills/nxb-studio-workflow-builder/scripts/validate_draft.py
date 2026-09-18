#!/usr/bin/env python3
"""Validate an NXB Studio draft without saving or launching anything.

The script first checks the public model-facing schema.  When the local NXB
repository is available it then delegates structural normalization to
``nxb.studio_drafts.validate``.  Otherwise it uses the conservative portable
validator here.  It prints a normalized draft and launch-payload preview.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any


LAYOUTS = {
    "main-horizontal",
    "main-vertical",
    "tiled",
    "even-horizontal",
    "even-vertical",
}
ROLES = {"worker", "orchestrator"}
RUNTIMES = {"claude_code", "codex"}
TOP_KEYS = {"session", "working_directory", "layout", "agents", "view"}
AGENT_KEYS = {
    "name",
    "role",
    "runtime",
    "model",
    "effort",
    "working_directory",
    "instructions",
    "node_id",
    "x",
    "y",
}
BAD_SESSION_PUNCTUATION = set(":.$'\"\\")
BAD_NAME = set("'\"\\")
ASTRA = re.compile(r"^gpt-6-astra(?:$|-)")


class DraftError(ValueError):
    pass


def string(value: Any, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise DraftError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise DraftError(f"{field} is required")
    return value


def finite(value: Any, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DraftError(f"{field} must be a finite number")
    if not math.isfinite(value):
        raise DraftError(f"{field} must be a finite number")
    return value


def public_schema(value: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    if not isinstance(value, dict):
        raise DraftError("draft must be a JSON object")
    extra = set(value) - TOP_KEYS
    if extra:
        raise DraftError(f"unknown top-level field(s): {', '.join(sorted(extra))}")

    session = string(value.get("session"), "session", required=True)
    if any(char.isspace() or char in BAD_SESSION_PUNCTUATION for char in session):
        raise DraftError(
            "session may not contain whitespace, colons, dots, dollar signs, "
            "quotes, or backslashes"
        )
    work_dir = string(
        value.get("working_directory"), "working_directory", required=True
    )
    layout = string(value.get("layout", "main-horizontal"), "layout", required=True)
    if layout not in LAYOUTS:
        raise DraftError(
            f"unknown layout {layout!r}; choose one of {', '.join(sorted(LAYOUTS))}"
        )

    raw_agents = value.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        raise DraftError("agents must be a nonempty array")

    agents: list[dict[str, Any]] = []
    names: set[str] = set()
    node_ids: set[int] = set()
    orchestrators = 0
    warnings: list[str] = []
    compatibility_issues: list[str] = []
    for index, raw in enumerate(raw_agents):
        prefix = f"agents[{index}]"
        if not isinstance(raw, dict):
            raise DraftError(f"{prefix} must be an object")
        extra = set(raw) - AGENT_KEYS
        if extra:
            raise DraftError(
                f"{prefix} has unknown field(s): {', '.join(sorted(extra))}"
            )

        name = " ".join(string(raw.get("name"), f"{prefix}.name", required=True).split())
        if any(char in BAD_NAME for char in name):
            raise DraftError(f"{prefix}.name may not contain quotes or backslashes")
        if name in names:
            raise DraftError(f"two agents are named {name!r}")
        names.add(name)

        role = string(raw.get("role"), f"{prefix}.role", required=True)
        if role not in ROLES:
            raise DraftError(f"{prefix}.role must be worker or orchestrator")
        orchestrators += role == "orchestrator"
        if orchestrators > 1:
            raise DraftError("a rig may contain at most one orchestrator")

        runtime = string(raw.get("runtime"), f"{prefix}.runtime", required=True)
        if runtime not in RUNTIMES:
            raise DraftError(f"{prefix}.runtime must be claude_code or codex")

        agent: dict[str, Any] = {"name": name, "role": role, "runtime": runtime}
        if "node_id" in raw:
            node_id = raw["node_id"]
            if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id < 1:
                raise DraftError(f"{prefix}.node_id must be a positive integer")
            if node_id in node_ids:
                raise DraftError(f"two agents use node_id {node_id}")
            node_ids.add(node_id)
            agent["node_id"] = node_id
        for key in ("model", "effort", "working_directory", "instructions"):
            if key in raw:
                val = string(raw[key], f"{prefix}.{key}")
                if val:
                    agent[key] = val
        for key in ("x", "y"):
            if key in raw:
                agent[key] = finite(raw[key], f"{prefix}.{key}")

        model = agent.get("model", "")
        effort = agent.get("effort", "")
        if runtime == "claude_code":
            if model == "haiku" or model.startswith("claude-haiku-4-5"):
                if effort:
                    compatibility_issues.append(
                        f"{name}: current Haiku 4.5 has no effort control; omit effort"
                    )
            elif effort and effort not in {
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                "ultracode",
            }:
                compatibility_issues.append(
                    f"{name}: unknown Claude effort/mode {effort!r}; verify the installed client"
                )
            if effort == "ultracode":
                warnings.append(
                    f"{name}: ultracode creates nested dynamic workflows at xhigh; "
                    "confirm that hidden subagents are intentional"
                )
        else:
            if effort and effort not in {
                "none",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                "ultra",
            }:
                compatibility_issues.append(
                    f"{name}: unknown Codex effort/mode {effort!r}; verify the installed client"
                )
            if ASTRA.match(model) and effort == "none":
                compatibility_issues.append(
                    f"{name}: the current Astra API contract does not support none"
                )
            if effort == "ultra":
                warnings.append(
                    f"{name}: Codex Ultra creates nested subagents; capability-check the "
                    "client/model and confirm nesting is intentional"
                )

        agents.append(agent)

    if orchestrators and not any(a["role"] == "worker" for a in agents):
        compatibility_issues.append(
            "orchestrator-only fleet has nobody to dispatch work to"
        )

    root = Path(os.path.expanduser(work_dir))
    if not root.is_dir():
        warnings.append(f"rig working directory does not exist yet: {root}")
    for agent in agents:
        if "working_directory" in agent:
            path = Path(os.path.expanduser(agent["working_directory"]))
            if not path.is_dir():
                warnings.append(
                    f"{agent['name']} working directory does not exist yet: {path}"
                )

    view = value.get("view")
    normalized_view = None
    if view is not None:
        if not isinstance(view, dict):
            raise DraftError("view must be an object")
        extra = set(view) - {"zoom", "x", "y"}
        if extra:
            raise DraftError(f"view has unknown field(s): {', '.join(sorted(extra))}")
        normalized_view = {}
        for key in ("zoom", "x", "y"):
            if key in view:
                normalized_view[key] = finite(view[key], f"view.{key}")

    draft = {
        "session": session,
        "working_directory": work_dir,
        "layout": layout,
        "agents": agents,
    }
    if normalized_view is not None:
        draft["view"] = normalized_view
    return draft, warnings, compatibility_issues


def nxb_repository(explicit: str | None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("NXB_REPO"):
        candidates.append(Path(os.environ["NXB_REPO"]).expanduser())
    candidates.append(Path("/Users/rohan/dev/nexus-bridge"))
    here = Path.cwd().resolve()
    candidates.extend([here, *here.parents])
    for candidate in candidates:
        if (candidate / "nxb" / "rig.py").is_file():
            return candidate.resolve()
    return None


def nxb_validate(
    draft: dict[str, Any], repo: Path | None
) -> tuple[dict[str, Any], list[str], str]:
    if repo is None or not (repo / "nxb" / "studio_drafts.py").is_file():
        return draft, [], "portable-fallback"
    sys.path.insert(0, str(repo))
    try:
        from nxb.studio_drafts import validate  # type: ignore

        result = validate(draft)
    except ImportError:
        return draft, [], "portable-fallback"
    except Exception as exc:  # Report the real local contract failure.
        raise DraftError(f"local NXB validator rejected the draft: {exc}") from exc
    finally:
        try:
            sys.path.remove(str(repo))
        except ValueError:
            pass
    if not isinstance(result, dict) or not result.get("valid"):
        raise DraftError("local NXB validator returned an invalid result")
    normalized = result.get("draft")
    if not isinstance(normalized, dict):
        raise DraftError("local NXB validator did not return a normalized draft")
    return normalized, list(result.get("warnings") or []), "nxb.studio_drafts"


def launch_payload(draft: dict[str, Any]) -> dict[str, Any]:
    launch_agents = []
    for agent in draft["agents"]:
        item = {
            "name": agent["name"],
            "role": agent["role"],
            "runtime": agent["runtime"],
        }
        for key in ("model", "effort", "instructions"):
            if agent.get(key):
                item[key] = agent[key]
        if agent.get("working_directory"):
            item["dir"] = agent["working_directory"]
        launch_agents.append(item)
    return {
        "session": draft["session"],
        "dir": draft["working_directory"],
        "layout": draft.get("layout", "main-horizontal"),
        "agents": launch_agents,
    }


def round_trip_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Strip storage-only fields while preserving update-safe canvas identity."""
    agents = []
    for raw in draft["agents"]:
        agent = {}
        for key in (
            "name",
            "role",
            "runtime",
            "model",
            "effort",
            "working_directory",
            "instructions",
            "node_id",
            "x",
            "y",
        ):
            if key in raw:
                agent[key] = raw[key]
        agents.append(agent)
    return {
        "session": draft["session"],
        "working_directory": draft["working_directory"],
        "layout": draft.get("layout", "main-horizontal"),
        "agents": agents,
        **({"view": draft["view"]} if "view" in draft else {}),
    }


def read_input(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an NXB Studio draft without saving or launching it"
    )
    parser.add_argument("draft", help="draft JSON path, or - for stdin")
    parser.add_argument(
        "--nxb-repo",
        help="optional NXB repository for its authoritative durable-draft validator",
    )
    args = parser.parse_args()

    try:
        raw = read_input(args.draft)
        public, warnings, compatibility_issues = public_schema(raw)
        normalized, local_warnings, validator = nxb_validate(
            public, nxb_repository(args.nxb_repo)
        )
        for warning in local_warnings:
            if warning not in warnings:
                warnings.append(warning)
        reusable = round_trip_draft(normalized)
        result = {
            "valid": True,
            "structurally_valid": True,
            "launched": False,
            "model_and_account_access_live_verified": False,
            "compatibility_review_required": bool(compatibility_issues),
            "compatibility_issues": compatibility_issues,
            "validator": validator,
            "warnings": warnings,
            "draft": reusable,
            "launch_payload_preview": launch_payload(reusable),
        }
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    except (DraftError, OSError, json.JSONDecodeError) as exc:
        json.dump(
            {"valid": False, "launched": False, "error": str(exc)},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
