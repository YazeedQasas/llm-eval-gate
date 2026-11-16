# Case study: 20% → 80% by fixing the evaluation

> **DRAFT.** The structure and the synthetic reproductions are complete. The sections
> marked `TODO(Yazeed)` need the real Mezan timeline and numbers. Only shareable,
> non-confidential details should go there: no client names, case numbers or
> verbatim judgments.

## The task

Mezan's judgment prediction takes a case file (and retrieved legal material) and predicts
the court's ruling. The headline metric was exact match on the verdict.

`TODO(Yazeed)`: one paragraph on the setting: languages, verdict categories, dataset size,
and what "exact match" meant at the start.

## Where it started

Exact match was around **20%**. The obvious next step was a bigger model and a longer prompt.

`TODO(Yazeed)`: what was tried first and what it moved.

## What actually moved the number

Most of the gain came from finding out that the evaluation was measuring the wrong thing,
in three different ways. Some mistakes made the score look better than it was; others made
it look worse.

`TODO(Yazeed)`: a timeline table, one row per fix:

| When | Fix | Exact match before → after | Direction of the error |
|---|---|---|---|
| TODO | Score only the operative line | TODO | the scorer was wrong, not the model |
| TODO | Remove self-retrieved judgments | TODO | inflated |
| TODO | Remove answer-bearing context | TODO | inflated |
| TODO | Other (prompt/format) | TODO | |

### 1. The whole-text categorizer trap

**What happened.** Verdicts were read off the model output by a categorizer that looked at
the whole text. Judgments argue before they rule. A reasoning section that says "the
objection to jurisdiction is rejected" three times ends with "the claim is accepted", and a
whole-text classifier sees three rejections. Correct predictions were scored as wrong, and
wrong ones that happened to repeat the right words were scored as right.

**Fix.** Find the operative line ("The court rules: ...", "حكمت المحكمة ...", the last one if
the reasoning quotes an earlier ruling) and categorize only that. If there is no operative
line, the case fails. The scorer never guesses.

**Synthetic reproduction** (12 trap cases in the demo set, prompt v1):

| Scorer | Correct on the 12 trap cases |
|---|---|
| whole-text categorizer | 2 / 12 |
| operative line (`operative_verdict`) | 9 / 12 |

In `evalgate` the whole-text categorizer exists only as a comparison
(`whole_text_verdict`), and the gate refuses it as the primary metric.

### 2. Self-retrieval

**What happened.** The retrieval index contained the judgments being predicted. For some
cases, retrieval returned the case's own judgment as "relevant context", and the model
copied the ruling. Those cases scored perfectly and taught nothing.

**Fix.** Every golden case records `source_doc_id`. The guard flags any case whose context
contains that id, plus near copies under another id (≥ 80% of the judgment's word 5-grams).

### 3. Answer-bearing context

**What happened.** Other documents stated the outcome: a summary, a later appeal, a
headnote. Not the same document, but the same answer.

**Fix.** The guard looks for the expected answer, or the ruling in its operative line, in
the input and context after normalization (Arabic diacritics, hamza and ta marbuta folding,
punctuation). Flagged cases are excluded or fail the run.

**Synthetic reproduction of 2 and 3** (16 of 72 demo cases leak):

| Prompt | With leaky cases | Leaks excluded |
|---|---|---|
| v1 | 86.1% (n=72) | 82.1% (n=56) |
| v2 | 72.2% (n=72) | 64.3% (n=56) |

Leaks inflate both prompts, and they make prompts look closer than they are: every leaky
case is "right" whatever the prompt does.

## What we took from it

- Look at the failures before changing the model. Many of them were not model failures.
- Score the decision, not the prose around it.
- Assume the answer is in the context until a guard says it isn't.
- Freeze a baseline and gate on it, so a prompt that *reads* better can't quietly score
  worse. In the demo, the fluent v2 prompt loses 17.9 points, and four of its 13 regressions
  are outputs with no ruling at all.

`TODO(Yazeed)`: anything else, e.g. what the remaining 20% of errors look like.
