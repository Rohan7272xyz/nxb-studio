# Blind judging brief — nxb-008

**This exact text is given to every judge, byte-identical, with no additions.**
If a judge is briefed differently from another, disagreement between judges is
confounded with difference in briefing and the comparison means nothing.

---

You are judging pairs of answers. Each pair is two responses to the SAME
question or the SAME artefact, labelled only A and B. You do not know where any
answer came from, and you will not be told.

## What to do, per pair

**1. SUBSTANTIVE or STYLISTIC?** This is the primary judgement.

- **STYLISTIC**: same conclusion, same identified cause, same recommendation.
  Differences are prose, length, structure, tone, or confidence only.
- **SUBSTANTIVE**: different conclusion, a different cause or failure mode
  identified, one catches something the other misses, or one is right and the
  other wrong.

Say which, and quote the specific text that decided it. "They feel different"
is not a judgement.

**2. Where the question has a determinate answer, say which answer is
correct** — A, B, both, neither, or disputed. You may conclude BOTH ARE WRONG.
That is a real and useful outcome, not a failure to decide.

**3. For the artefacts containing defects**, record separately:
- did it identify the specific defect present
- did it identify a DIFFERENT real defect (this is a positive result and the
  most interesting thing you can find)
- did it report something as a defect that is not one

## Rules that decide the result

**JUDGE SUBSTANCE, NOT VOLUME.** One set of answers may be several times longer
than the other. Length is not thoroughness. A short correct answer beats a long
wrong one, and a long answer that restates the question at greater length is
not more substantive.

**SOME PAIRS ARE CONTROLS: both answers come from the SAME source.** You are not
told which pairs, or how many. Judge every pair identically and by the same
standard. Do not try to work out which are controls; guessing corrupts the
result you are producing.

**THE ANSWER KEY MAY BE WRONG.** These artefacts and their expected answers were
written by hand. If an answer identifies something real that the key does not
anticipate, the key is what should be doubted, not the answer. Say so plainly
when you think it has happened. At least one expected answer is known to be
contested, where the widely taught answer differs from what was measured on real
hardware; an answer reasoning the other way is defensible rather than careless
and should be recorded as disputed.

**RECORD ANY SENSE OF AUTHORSHIP.** If at any point you believe you can tell who
or what produced an answer, or you recognise a style as your own, SAY SO for
that pair. This does not disqualify your judgement and you should still make it.
It is recorded so the result can be read with it in mind. Do not guess for the
sake of guessing; report only genuine recognition.

## Output

For each pair, in order:

```
PAIR <id>
verdict: SUBSTANTIVE | STYLISTIC
evidence: <the specific text that decided it>
correct: A | B | BOTH | NEITHER | DISPUTED | N/A
defect_found: <for artefacts only: PLANTED / OTHER-REAL / FALSE-POSITIVE / NONE, per answer>
authorship_recognised: NO | <what you noticed and for which answer>
```

Then a short summary: how many substantive, how many stylistic, and whether the
substantive differences cluster in any kind of question.

Do not rank the two sources. Do not say which is better overall. That is not
what is being measured.
