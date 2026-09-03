"""Make a moving tree visible in the verdict.

A red suite here has had THREE indistinguishable meanings: a defect, a busy
machine, or another agent committing into the tree mid-run. Three agents write to
this repo. The third was observed three times in one day, twice by me with a
different test failing each time and once by Worker 2, and every observation cost
someone the work of deciding whether to file a finding on a failure nobody could
reproduce.

Splitting the slow target addressed the busy machine. Sequencing discipline
addresses the moving tree, but a discipline that binds only an orchestrator's
memory is one nobody follows in three weeks, and this project's record says so.

So this records what the tree was doing and reports it NEXT TO the verdict:

  * a red run on a tree that moved is labelled UNATTRIBUTABLE
  * a run against uncommitted changes is labelled as such, because a verdict on
    a working copy is a verdict on code that exists nowhere else, and it expires
    the moment that copy is reshaped

DELIBERATELY NOT A FAILURE. Failing on a moved tree would add a FOURTH meaning to
red, which is the opposite of the point. It annotates and never blocks.

It also cannot break a run: every git call is guarded, and if git is unavailable
or slow it says nothing at all. A diagnostic that reddens a suite would be worse
than the ambiguity it exists to remove.
"""

import subprocess

_STATE = {}


def _git(*args):
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _snapshot():
    head = _git("rev-parse", "HEAD")
    if head is None:
        return None
    porcelain = _git("status", "--porcelain")
    if porcelain is None:
        return None
    # Porcelain v1 is `XY PATH` with XY exactly two status characters, but the
    # pair varies (" M", "M ", "MM", "R "), so slice past the status and strip
    # rather than assume a fixed offset. A fixed [3:] silently ate the first
    # character of a filename under one of those combinations.
    dirty = sorted(
        line[2:].strip() for line in porcelain.splitlines()
        if line and not line.startswith("??"))
    return {"head": head, "dirty": dirty}


def pytest_sessionstart(session):
    _STATE["start"] = _snapshot()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    start = _STATE.get("start")
    if start is None:
        return
    end = _snapshot()
    if end is None:
        return

    write = terminalreporter.write_line
    failed = bool(terminalreporter.stats.get("failed") or
                  terminalreporter.stats.get("error"))

    moved_head = start["head"] != end["head"]
    moved_files = start["dirty"] != end["dirty"]

    if moved_head or moved_files:
        write("")
        write("=" * 70)
        what = []
        if moved_head:
            what.append("HEAD moved %s -> %s" % (start["head"][:7], end["head"][:7]))
        if moved_files:
            changed = sorted(set(start["dirty"]) ^ set(end["dirty"]))
            what.append("working tree changed: %s" % ", ".join(changed[:6]))
        if failed:
            write("VERDICT UNATTRIBUTABLE: the tree MOVED during this run.")
            write("A failure here may be a defect, or may be the tree changing "
                  "under the run.")
            write("Re-run on a still tree before filing anything.")
        else:
            write("NOTE: the tree moved during this run. The green verdict "
                  "covers no single state.")
        for line in what:
            write("  " + line)
        write("=" * 70)
    elif start["dirty"]:
        write("")
        write("NOTE: verdict taken on UNCOMMITTED changes in %d file(s); it "
              "expires if they are reshaped." % len(start["dirty"]))
        write("      %s" % ", ".join(start["dirty"][:6]))
