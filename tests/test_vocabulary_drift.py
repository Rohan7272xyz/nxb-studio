"""Refusal vocabulary drift, in both directions, as a FAST guard.

Nothing forces a reason the code emits to be a reason a contract publishes, so
the two drift silently. C11 in the conformance suite catches the adapter half by
probing, but probing only sees reasons a hostile input can provoke, it lives in
the slow `spawns_children` target, and it cannot see `nxb/h2.py` or
`nxb/dispatch.py` at all. This is the static complement: it reads every reason
literal in `nxb/` and every published vocabulary, and compares the sets.

It spawns nothing and runs in milliseconds, so drift detection belongs to the
fast signal rather than to the target people defer.

WHY THIS DOES NOT EDIT THE CONTRACT, which is what nxb-032 asked for.
The five known divergences are waived here rather than resolved, because the
contract is under a blind-implementation embargo (HANDOFF ~676: the missing
clauses stay unwritten until a blind arm reports, and that arm does not exist
yet). I checked the boundary rather than assuming these terms sit outside it,
and I do not think they do. See the waiver reasons: publishing
`malformed_start_signal` would hand a blind implementer the very distinction
another property measures, and REMOVING `registration_unproven_capability` would
delete the record of the one divergence nxb-009 actually found.

So this guard does the part that is safe now: it makes the drift unable to GROW
without a decision, while leaving what to do about the five to whoever lifts the
embargo. A waiver is a claim with an expiry, not an exemption: any waived term
that becomes conformant fails as stale.
"""

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
NXB = REPO / "nxb"
WAIVERS = pathlib.Path(__file__).resolve().parent / "adapter_conformance_waivers.json"

#: A reason literal in a `reason=` / `"reason":` position. ANCHORED to the
#: closing quote so the whole string must be one snake_case token: an early
#: draft captured the first word of the prose `"no outcome recorded for this
#: key"` and reported a refusal term called `no`. A guard that cries wolf gets
#: disabled, which is worse than not having it.
_REASON_LITERAL = re.compile(
    r'reason\s*=\s*\(?\s*["\']([a-z][a-z0-9_]*)["\']'
    r'|["\']reason["\']\s*:\s*["\']([a-z][a-z0-9_]*)["\']')


def published_terms():
    terms = {}
    for path in sorted((REPO / "contract").glob("*.json")):
        for term in json.loads(path.read_text(encoding="utf-8")).get("refusal_vocabulary", []):
            terms.setdefault(term, path.name)
    return terms


def emitted_terms():
    """Reasons reached through a `reason=` position. DELIBERATELY CONSERVATIVE.

    Refusals also leave the code as bare tuple elements (`return "REJECTED",
    "count_divergence"`) and as exception arguments
    (`raise RegistrationRefused("registration_omitted_field", ...)`), which this
    does not see. Widening it to every snake_case literal in nxb/ would sweep up
    state names and dict keys and produce false alarms.

    So this direction UNDER-reports and never over-reports. That asymmetry is
    deliberate and is named again in the module docstring: a guard that misses
    something stays trusted, a guard that invents something gets switched off.
    """
    found = {}
    for path in sorted(NXB.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _REASON_LITERAL.finditer(text):
            term = next(g for g in match.groups() if g)
            found.setdefault(term, str(path.relative_to(REPO)))
    return found


def mentioned_anywhere():
    """Every published term that appears as a quoted literal ANYWHERE in nxb/.

    Used for the ORPHAN direction, which must not over-report either: a term
    emitted as a tuple element or an exception argument is still emitted, and
    calling it an orphan would be a false alarm. Matched at the START of a
    literal rather than as a whole one, because `nxb/h2.py` emits
    `f"parent_not_accepted: {state}"` and requiring a closing quote called that
    an orphan too.
    """
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(NXB.rglob("*.py")))
    return {term for term in published_terms()
            if re.search(r'["\']%s(?=["\':\\s])' % re.escape(term), text)}


def code_side_vocabularies():
    """Any closed vocabulary of refusal terms maintained in code, not in a contract.

    Matches BOTH shapes. An earlier version matched only `NAME = [...]` and
    therefore missed `REFUSAL_SCOPE`, which is `NAME = {...}`: the guard that
    existed to catch a code-side vocabulary could not see the fourth one. Shape
    is not a property anyone should have to remember, so both are matched and a
    third shape would still be missed, which is stated rather than hidden.

    For a list the members ARE the terms. For a dict the KEYS are the terms and
    the values are prose, so only keys are extracted.
    """
    out = {}
    for path in sorted(NXB.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
                r'^([A-Z_]*REFUSAL[A-Z_]*)\s*=\s*\[([^\]]*)\]', text, re.MULTILINE):
            out[match.group(1)] = (
                str(path.relative_to(REPO)),
                sorted(set(re.findall(r'["\']([a-z][a-z0-9_]*)["\']', match.group(2)))))
        for match in re.finditer(
                r'^([A-Z_]*REFUSAL[A-Z_]*)\s*=\s*\{([^}]*)\}', text, re.MULTILINE):
            out[match.group(1)] = (
                str(path.relative_to(REPO)),
                sorted(set(re.findall(r'["\']([a-z][a-z0-9_]*)["\']\s*:', match.group(2)))))
    return out


def stale_code_side_waivers(waived=None):
    """Waivers for tokens no code-side vocabulary carries any more.

    Module-level so the test and the findings-ledger check share ONE copy. A
    second copy of this rule would drift from the first, which is the defect
    this whole file exists to catch.
    """
    live = set()
    for _where, terms in code_side_vocabularies().values():
        live.update(terms)
    if waived is None:
        waived = _waivers("code_side_vocabulary_tokens")
    return sorted(t for t in waived if t not in live)


def _published_scope_terms():
    """Capability-vocabulary terms any contract publishes. Derived, not restated."""
    terms = set()
    for path in sorted((REPO / "contract").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for key, value in doc.items():
            if key.endswith("_vocabulary") and isinstance(value, dict):
                terms.update(k for k in value if not k.startswith("_"))
    return terms


def _waivers(key):
    if not WAIVERS.exists():
        return {}
    return json.loads(WAIVERS.read_text(encoding="utf-8")).get("waivers", {}).get(key, {})


class VocabularyDrift(unittest.TestCase):

    def test_every_emitted_reason_is_published(self):
        published, emitted = published_terms(), emitted_terms()
        waived = _waivers("unpublished_reasons")
        offenders = {t: where for t, where in emitted.items()
                     if t not in published and t not in waived}
        self.assertFalse(
            offenders,
            "code emits refusal reason(s) no contract publishes: %s. Publish "
            "them or waive them in %s." % (sorted(offenders.items()), WAIVERS.name))

    def test_every_published_reason_is_emitted(self):
        published, mentioned = published_terms(), mentioned_anywhere()
        waived = _waivers("unemitted_terms")
        orphans = {t: src for t, src in published.items()
                   if t not in mentioned and t not in waived}
        self.assertFalse(
            orphans,
            "contract publishes refusal term(s) nothing emits: %s. An orphan "
            "term is a guard that guards nothing." % sorted(orphans.items()))

    def test_no_code_side_vocabulary_grows_without_a_decision(self):
        """`EXTRA_REFUSALS` exists because someone needed a term and did not add
        it to a contract. Whether it should exist is not mine to decide while the
        contract is under embargo. That it must not GROW silently is."""
        waived = set(_waivers("unpublished_reasons")) | set(
            _waivers("code_side_vocabulary_tokens"))
        # nxb-042: REFUSAL_SCOPE now HAS a published counterpart, so its tokens
        # are checked against it rather than waived. This guard was written when
        # nothing published a capability vocabulary and could only ask that one
        # not GROW; it can now ask that it MATCH.
        published = set(published_terms()) | _published_scope_terms()
        for name, (where, terms) in code_side_vocabularies().items():
            unaccounted = sorted(set(terms) - published - waived)
            with self.subTest(vocabulary=name):
                self.assertFalse(
                    unaccounted,
                    "%s in %s carries term(s) no contract publishes and no "
                    "waiver names: %s" % (name, where, unaccounted))

    def test_a_waiver_for_a_deleted_token_is_stale(self):
        """The expiry rule this design was MISSING, and it cost a live example.

        Every other waiver here expires by becoming CONFORMANT: a term gets
        published, or an orphan gets emitted. A token waived because it is being
        REMOVED has no such condition, because it was never published and there
        is nothing for it to become conformant with. `opaque_tool_failure` was
        waived in nxb-032b with the text "if this waiver is still here after that
        lands, the removal did not happen", and when nxb-034 removed it nothing
        would have noticed. The waiver would simply have sat there being true
        about nothing.

        So this category expires in the opposite direction: a waiver for a
        code-side vocabulary token is stale once that token is no longer IN any
        code-side vocabulary. Removal is the expiry condition.
        """
        stale = stale_code_side_waivers()
        self.assertFalse(
            stale,
            "waiver(s) for token(s) no code-side vocabulary carries any more: "
            "%s. The token was removed; delete the waiver." % stale)

    def test_waivers_expire(self):
        """A waived term that is now conformant is stale and must be removed."""
        published = published_terms()
        stale_unpublished = sorted(t for t in _waivers("unpublished_reasons")
                                   if t in published)
        # BOTH ways a waiver in this category dies. It expires by becoming
        # CONFORMANT (the orphan gets emitted) or by the term being REMOVED from
        # every contract, at which point there is no orphan left to excuse. Only
        # the first was checked, which is exactly the hole WD-2 recorded for the
        # code-side category, in its mirror. Found by publishing the batch in
        # nxb-042 and noticing the three orphan waivers would have sat there
        # being true about nothing.
        published = published_terms()
        mentioned = mentioned_anywhere()
        stale_unemitted = sorted(t for t in _waivers("unemitted_terms")
                                 if t in mentioned or t not in published)
        self.assertFalse(stale_unpublished,
                         "waived as unpublished but now published: %s" % stale_unpublished)
        self.assertFalse(stale_unemitted,
                         "waived as unemitted but now emitted: %s" % stale_unemitted)


if __name__ == "__main__":
    unittest.main()
