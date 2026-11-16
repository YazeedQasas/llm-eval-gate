# Demo: synthetic judgment prediction

**Everything in this folder is synthetic.** The cases, parties, amounts, legal principles
and "model outputs" are invented. Nothing comes from real court records or from Mezan's
data. The set exists to show how the gate behaves, not to measure any real model.

## Files

| File | What it is |
|---|---|
| `cases.jsonl` | 72 golden cases (36 English, 36 Arabic), built by `scripts/build_demo_dataset.py` |
| `prompts/judgment.txt` | The current prompt (v1, terse, strict operative-line format) |
| `prompts/candidates/v2-fluent.txt` | A "better-looking" candidate: longer, more fluent, no format rule |
| `recordings.jsonl` | Recorded outputs for both prompts. CI only ever replays these |
| `simulated_model.py` | The stand-in "model" used to record. **Not an LLM**: it writes outputs with a fixed accuracy profile and reads the golden file to do so |
| `baselines/main.json` | The frozen baseline for v1 |
| `evalgate.toml` | Config tying it together |

## The task

Input: a case summary plus retrieved legal principles. Output: a short judgment that ends
with an operative line ("The court rules: ..." / "حكمت المحكمة ..."). The verdict is one of
accepted, partially accepted, rejected, or inadmissible (`dismissed`).

## Seeded traps

`metadata.seeded_trap` marks the traps so tests can check that the guards catch them.
The guards never read metadata.

| Trap | Cases | What it looks like |
|---|---|---|
| `self_retrieval` | 8 | The case's own judgment is in `context`, by its `source_doc_id` (6) or as a lightly edited "archived copy" under another id (2) |
| `answer_bearing` | 8 | A "press summary" in `context` states the ruling. Arabic ones add diacritics so only normalized matching finds them |
| `whole_text` | 12 | The reasoning says "rejected" three times (objections, adjournment, limitation) while the operative line accepts the claim, or the reverse |

## Re-recording

```
cd examples/judgments
evalgate record                                         # v1
evalgate record --prompt prompts/candidates/v2-fluent.txt
evalgate freeze                                         # only when v1 legitimately changes
```

To use a real model, point `[system] live` at a factory of your own:
`make_generate(prompt_text) -> fn(case, params) -> str`.
