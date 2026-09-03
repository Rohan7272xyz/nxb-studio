# Brief for a blind implementation arm

**Committed BEFORE the arm exists, so it is auditable and cannot be quietly
"improved" later. Improvement is how every leak on this project arrived.**

This brief is deliberately minimal. It names no areas to exercise, no severities,
no prior findings, no count of anything found before, **and no example whose
SHAPE is the shape of a known finding.** An earlier version of this file demanded
specificity by illustrating it with an encoding example, which was itself the
shape of one of the two findings the arm exists to rediscover independently. The
leak was in the illustration of why specificity matters. **Every contamination this
project has suffered arrived through an orchestrator elaborating on why the blind
mattered.** The elaboration is the leak. There is nothing to add to this.

**Hand the arm ONLY the section below the horizontal rule, and a bare directory
containing the contract file and nothing else.** Everything above the rule is
orchestrator notes and must not be shown: it would tell the arm it is a blind
subject in an experiment, which contradicts the instruction to treat the work as
ordinary.

---

Implement the dispatch contract described in `contract.json`, in the directory
you have been given. Use any language you like.

Then report:

1. Anything in the contract that was **ambiguous**: you had to choose between two
   defensible readings. Say what you chose and what the other reading was.
2. Anything the contract was **silent** about that you had to invent in order to
   produce running code. Say what you invented.
3. Anything in the contract that appears **wrong or self-contradictory**.
4. Anything you could not implement, and why.

Be specific. A finding must be stated precisely enough that another person
could reproduce the disagreement from your description alone: give the exact
input, and the two different results the two readings produce. "I made a
reasonable choice here" is not a finding.

Mark anything you did not actually run as UNVERIFIED.

Do not look for anything in particular. Do not try to find defects of any
specific kind. Implement it as you would if you had been handed it as ordinary
work, and report honestly what got in your way.
