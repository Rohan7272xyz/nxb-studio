"""The never-read guard's blind spot: a value dropped by a PARAMETER, not a field.

WD-1 was `work_dir`: computed in nxb/run.py, threaded through RoundTrip and
SpawnHop, accepted by ClaudeCodeAdapter.build_command, and consumed by nobody.
Popen had no `cwd=`, so every dispatched Claude Code child ran in the broker's
own source tree with Write and Edit. The never-read guard could not see it,
because that guard checks CONTRACT FIELDS and this was a FUNCTION ARGUMENT. Same
defect class, different carrier, and nothing was positioned to notice the scope
was narrower than the class.

WHAT IT FLAGS
A parameter that a real implementation accepts, never reads, and that at least
one caller explicitly passes by keyword. All three clauses matter: without the
third it becomes a generic unused-argument linter, which flags interface
conformance everywhere and gets switched off.

TWO EXCLUSIONS, EACH REMOVING A CATEGORY RATHER THAN CASES
  1. Abstract bodies: docstring, `pass`, or a bare `raise`. A declaration is not
     a consumer.
  2. Dunder methods, whose signatures are imposed by a protocol. `__exit__(exc)`
     is not dropping anything.

THE EXCLUSION I TRIED AND REMOVED, which is the useful part of this file.
My first draft also excused a parameter if ANY function of the same name
elsewhere read it, which cleanly removed every subclass override and left a
residual of exactly one. It also made the guard BLIND TO WD-1: `work_dir` was
read by `codex.build_command`, a SIBLING of the adapter that dropped it, so the
rule excused the dropper on the strength of its sibling. Verified by running both
versions against the pre-fix tree at 3d2c883: with the exclusion the historical
defect is invisible; without it, `claude_code.build_command work_dir` is flagged
on the line it lived on.

A sibling consuming a value does not excuse a dropper, because the CALLER cannot
tell them apart. That is WD-1's whole mechanism. So the exclusion is gone and the
two interface-conformance hits it used to hide are waived explicitly, with the
reason each is safe named in the waiver rather than assumed.
"""

import ast
import collections
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
NXB = REPO / "nxb"
WAIVERS = pathlib.Path(__file__).resolve().parent / "adapter_conformance_waivers.json"


def _loads(fn):
    return {n.id for n in ast.walk(fn)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _is_abstract(fn):
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return not body or (len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Raise)))


def dropped_parameters(root=None):
    """(file, function, parameter, line) for every accepted-and-dropped value."""
    root = pathlib.Path(root or NXB)
    funcs, passed = [], collections.defaultdict(set)
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((path, node))
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                for kw in node.keywords:
                    if kw.arg:
                        passed[name].add(kw.arg)

    hits = []
    for path, fn in funcs:
        if _is_abstract(fn) or (fn.name.startswith("__") and fn.name.endswith("__")):
            continue
        args = fn.args
        params = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
        read = _loads(fn)
        for p in params:
            if p in ("self", "cls") or p in read:
                continue
            if p not in passed[fn.name]:
                continue
            hits.append((str(path.relative_to(root.parent)), fn.name, p, fn.lineno))
    return sorted(hits)


def _waived():
    if not WAIVERS.exists():
        return {}
    return json.loads(WAIVERS.read_text(encoding="utf-8")).get(
        "waivers", {}).get("dropped_parameters", {})


class NoValueIsAcceptedAndDropped(unittest.TestCase):

    def test_no_unwaived_dropped_parameter(self):
        waived = _waived()
        offenders = [h for h in dropped_parameters()
                     if "%s:%s:%s" % (h[0], h[1], h[2]) not in waived]
        self.assertFalse(
            offenders,
            "value(s) accepted by a signature and read by nobody: %s. This is "
            "WD-1's class. Either consume it, remove it from the signature, or "
            "waive it in %s naming what makes it safe." % (offenders, WAIVERS.name))

    def test_waivers_expire(self):
        """A waiver for a parameter that is now consumed, or gone, is stale."""
        live = {"%s:%s:%s" % (f, fn, p) for f, fn, p, _l in dropped_parameters()}
        stale = sorted(k for k in _waived() if k not in live)
        self.assertFalse(
            stale, "waiver(s) for parameters that are no longer dropped: %s. "
                   "Delete them." % stale)


class TheGuardFires(unittest.TestCase):
    """Proven against a synthetic tree, both directions.

    The historical proof is in the module docstring and was run by hand against
    3d2c883; it cannot live here because it needs a git checkout. What lives here
    is the property: the rule flags a dropped parameter and does NOT flag the
    three categories it deliberately excuses.
    """

    SOURCE = '''
def consumer(*, used, dropped):
    return used

def caller():
    consumer(used=1, dropped=2)

class Base:
    def hook(self, *, thing):
        raise NotImplementedError

    def __exit__(self, exc):
        return False

    def call(self):
        self.hook(thing=1)
'''

    def setUp(self):
        import tempfile, shutil
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="dropparam-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "pkg").mkdir()
        (self.tmp / "pkg" / "m.py").write_text(self.SOURCE, encoding="utf-8")

    def test_it_flags_a_dropped_parameter(self):
        found = {(h[1], h[2]) for h in dropped_parameters(self.tmp / "pkg")}
        self.assertIn(("consumer", "dropped"), found)

    def test_it_does_not_flag_the_categories_it_excuses(self):
        found = {(h[1], h[2]) for h in dropped_parameters(self.tmp / "pkg")}
        self.assertNotIn(("consumer", "used"), found, "flagged a consumed parameter")
        self.assertNotIn(("hook", "thing"), found, "flagged an abstract declaration")
        self.assertNotIn(("__exit__", "exc"), found, "flagged a protocol signature")


if __name__ == "__main__":
    unittest.main()
