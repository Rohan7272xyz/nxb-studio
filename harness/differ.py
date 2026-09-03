"""Differential harness for NEXUS Bridge implementations.

WHY A PROCESS BOUNDARY, NOT A VENDORED RENAME. Every implementation is a package
named `nxb` and two cannot co-import. The alternative to a subprocess is
rewriting one arm's imports, which edits the artefact under test: the thing being
measured stops being the thing that was built. A subprocess also gets exit codes,
which are per-process by definition and which the contract does not specify, and
it is the only approach that survives an arm written in another language. A third
arm lands shortly and there will be three.

WHY ISOLATED WORKSPACES. Each arm is copied FILE BY FILE into its own directory
outside this repository, together with an identical copy of the redacted
contract. Copying the tree would carry .git, and git history still holds the
pre-redaction contract in full, so a "bare" directory made by cloning is not
bare. Isolation is proven by a recursive listing including dotfiles, not asserted.

WHY THE WIRE IS ASCII. Jobs and results cross the boundary as JSON with
ensure_ascii=True. If the harness's own transport re-encoded the payload it would
mask or manufacture exactly the encoding divergence being hunted.
"""

import json, os, shutil, subprocess, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
EQUIV = json.loads((HERE / "equivalence.json").read_text(encoding="utf-8"))
ARMS = json.loads((HERE / "arms.json").read_text(encoding="utf-8"))["arms"]
WS = pathlib.Path(os.environ.get("NXB_WS", "/private/tmp/nxb-differential"))


# ----------------------------------------------------------------- workspaces

def build_workspaces(contract_src=None):
    """Copy each arm's files into a bare directory. Files, never trees."""
    contract_src = pathlib.Path(contract_src or REPO / "contract" / "contract.json")
    contract = contract_src.read_text(encoding="utf-8")
    if shutil.os.path.exists(WS):
        shutil.rmtree(WS)
    built = {}
    for arm in ARMS:
        root = WS / arm["name"]
        (root / "nxb").mkdir(parents=True)
        (root / "contract").mkdir()
        for src in sorted(pathlib.Path(arm["impl"]).glob("*.py")):
            shutil.copyfile(src, root / "nxb" / src.name)
        # Both layouts, one file: this arm reads contract/contract.json, that arm
        # reads ./contract.json, and both get byte-identical bytes.
        (root / "contract" / "contract.json").write_text(contract, encoding="utf-8")
        (root / "contract.json").write_text(contract, encoding="utf-8")
        built[arm["name"]] = root
    return built


def prove_isolation():
    """Recursive listing INCLUDING dotfiles. Asserting isolation is not proving it."""
    findings, listing = [], []
    for path in sorted(WS.rglob("*")):
        rel = path.relative_to(WS)
        listing.append(str(rel))
        if path.name in (".git", ".hg") or path.name.startswith(".git"):
            findings.append("VCS METADATA PRESENT: %s" % rel)
    for arm in ARMS:
        raw = (WS / arm["name"] / "contract" / "contract.json").read_text(encoding="utf-8")
        for tell in ("nxb.dispatch", "nxb.ledger", "PRIMARY KEY", "UNIQUE constraint"):
            if tell in raw:
                findings.append("LEAK in %s contract: %s" % (arm["name"], tell))
    return listing, findings


# ------------------------------------------------------------------- running

def run_job(arm_name, job, workspaces):
    arm = next(a for a in ARMS if a["name"] == arm_name)
    wire = json.dumps(job, ensure_ascii=True, allow_nan=True)
    proc = subprocess.run(
        [sys.executable, str(HERE / "adapters" / arm["adapter"])],
        input=wire, capture_output=True, text=True, timeout=120,
        env={**os.environ, "NXB_IMPL": str(workspaces[arm_name])},
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"ok": False, "adapter_failed": True,
                "exit_code": proc.returncode, "stderr": proc.stderr[-800:]}
    out = json.loads(proc.stdout)
    out["exit_code"] = proc.returncode
    return out


# ----------------------------------------------------------------- comparing

def verdict_for(section, field):
    entry = EQUIV.get(section, {}).get(field)
    return (entry or {}).get("verdict", "UNWRITTEN"), (entry or {})


def presence_verdict(entry, verdict):
    """A field may be FREE in value and still bound in presence. See pending_ref."""
    return entry.get("presence", verdict)


def _reason_matches(a, b):
    head = lambda s: s.split(": ", 1)[0] if isinstance(s, str) else s
    return a == b or head(a) == head(b)


def compare_receipts(ra, rb):
    """Diff two receipts modulo the declared equivalence relation."""
    out = []
    for field in sorted(set(ra) | set(rb)):
        verdict, entry = verdict_for("receipt", field)
        in_a, in_b = field in ra, field in rb
        if in_a != in_b:
            out.append((field, "PRESENCE", ra.get(field), rb.get(field),
                        presence_verdict(entry, verdict), entry))
        elif verdict != "FREE" and ra[field] != rb[field]:
            out.append((field, "VALUE", ra[field], rb[field], verdict, entry))
    return out


def compare_returns(a, b):
    out = []
    for field in sorted(set(a) | set(b)):
        verdict, entry = verdict_for("dispatch_return", field)
        in_a, in_b = field in a, field in b
        if in_a != in_b:
            out.append((field, "PRESENCE", a.get(field), b.get(field),
                        presence_verdict(entry, verdict), entry))
            continue
        if field == "receipt":
            for sub in compare_receipts(a[field], b[field]):
                out.append(("receipt." + sub[0],) + sub[1:])
            continue
        if field == "reason":
            if not _reason_matches(a[field], b[field]):
                out.append((field, "VALUE", a[field], b[field], verdict, entry))
            continue
        if verdict != "FREE" and a[field] != b[field]:
            out.append((field, "VALUE", a[field], b[field], verdict, entry))
    return out
