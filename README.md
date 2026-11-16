# llm-eval-gate

**Offline regression gates for LLM systems.** Golden datasets, deterministic scorers,
frozen baselines, and a CI gate that fails the build when a "better" prompt scores worse.

It also guards against three evaluation leaks seen in production: **self-retrieval**,
**answer-bearing context**, and the **whole-text categorizer trap** (fixed by scoring only the
operative line). It comes out of judgment-prediction work at Mezan, where exact match went
from 20% to 80% mostly by fixing the evaluation, not by using bigger models
([case study](docs/case-study.md)).

```
$ evalgate check --prompt prompts/candidates/v2-fluent.txt
# ❌ evalgate: FAIL

Prompt `fcc4689a3e7a` (baseline) → `023cd6c8e5a6` (this change). Primary scorer: `operative_verdict`.

|                       | Baseline | This change | Δ      | Regressed | Fixed | p (paired) |
|-----------------------|----------|-------------|--------|-----------|-------|------------|
| **operative_verdict** | 82.1%    | 64.3%       | -17.9% | 13        | 3     | 0.0106     |

## Why the gate failed
- operative_verdict pass rate dropped 17.9% (82.1% -> 64.3%), limit 2.0%, p=0.0106 < 0.05
- 13 case(s) regressed (pass -> fail), limit 5
...
```

The candidate prompt reads better: it asks for a "thorough, balanced analysis in natural
prose". It also stops the model from ending with a clear ruling, and gets more verdicts
wrong. The full report is in [docs/demo-report.md](docs/demo-report.md).

## Why

- **Offline and deterministic.** CI never calls a model. Outputs are recorded once and
  replayed; replay runs with the network blocked. The same inputs always give the same
  score, so a red build means the change, not the weather.
- **Comparable or refused.** Results carry hashes of the dataset, scorers and guard
  config. Comparing against a baseline built from different ones is an error, not a
  silent apples-to-oranges diff.
- **Not fooled by noise.** A drop has to exceed a threshold *and* pass an exact paired
  test on the cases that flipped, so 56 cases don't produce a flaky gate.
- **Not fooled by leaks.** Guards run before scoring and exclude or fail on cases where
  the answer is already in the context.

## 5-minute quickstart

Requires Python 3.11+. No runtime dependencies.

```
git clone <this repo> && cd llm-eval-gate
python -m pip install -e .
cd examples/judgments

evalgate guard                                              # 16 of 72 cases leak
evalgate check                                              # PASS, exit 0
evalgate check --prompt prompts/candidates/v2-fluent.txt    # FAIL, exit 1
```

The demo is a synthetic Arabic/English judgment-prediction set with leakage traps planted on
purpose ([details](examples/judgments/README.md)). Its "model" is a deterministic simulator,
so anyone can re-record without API keys.

## Concepts

| | |
|---|---|
| **Dataset** | JSONL golden cases: `id`, `input`, `expected`, optional `context` docs, `tags`, `source_doc_id`. Validated strictly; hashed. [Schema](docs/schema.md) |
| **System** | Prompt + model + params. The prompt's hash is its version, so any edit needs a new recording. |
| **Recording** | Outputs keyed by hash(prompt version, model, params, what the model sees). `evalgate record` calls the live system; everything else replays. [Replay](docs/replay.md) |
| **Scorer** | A pure function `(case, output) -> score, passed, reason`, with a version. The first in the config, or `[gate] primary`, drives the gate. |
| **Guard** | A check on the dataset before scoring: self-retrieval, answer-bearing context, and the whole-text trap report. Mode `fail`, `exclude` or `warn`. |
| **Baseline** | A frozen results file from `main`. Byte-reproducible; no timestamps. |
| **Gate** | `evalgate check`: guard, replay, score, compare to the baseline, apply thresholds. |

## The three leaks

1. **Self-retrieval.** Retrieval pulls the case's own judgment into the context, and the
   model copies it. The guard matches `source_doc_id` against context doc ids, and falls back
   to n-gram containment to catch copies stored under another id.
2. **Answer-bearing context.** A different document states the outcome: a press summary, a
   later appeal, a headnote. The guard looks for the expected answer or its operative line
   in the input and context after Arabic/English normalization.
3. **Whole-text categorizer trap.** Judgments discuss other outcomes in their reasoning
   ("the objection to jurisdiction is rejected") before ruling the opposite way. A
   classifier over the whole text picks up those words. `operative_verdict` finds the
   operative line ("The court rules: ...", "حكمت المحكمة ...") and scores only that, and
   fails, rather than guesses, when there is none. The gate refuses a whole-text scorer
   as its primary metric.

On the demo, v1 scores 82.1% with leaks excluded and 86.1% with them in. On the 12 trap
cases, the operative-line scorer gets 9 right and the whole-text categorizer 2.

## Commands

| Command | What it does |
|---|---|
| `evalgate validate FILE` | Validate a golden dataset |
| `evalgate record` | Call the live system and add outputs to the recordings file |
| `evalgate run` | Replay outputs (network blocked) to `runs/outputs.jsonl` |
| `evalgate guard [--json]` | Leakage report |
| `evalgate score` | Guard + score, write `runs/results.json` |
| `evalgate freeze` | Write the baseline (`[gate] baseline`) |
| `evalgate check [--report F]` | The gate. Also appends to `$GITHUB_STEP_SUMMARY` when set |

All take `-c/--config` (default `evalgate.toml`) and `--prompt FILE` to try a candidate.

**Exit codes:** `0` pass · `1` regression · `2` could not run cleanly (bad config or
dataset, missing recording, incomparable baseline, or leakage in mode `fail`).

Configuration reference: [docs/config.md](docs/config.md).

## In CI

```yaml
- uses: actions/checkout@v4
- uses: <owner>/llm-eval-gate@v0.1.0
  with:
    config: evals/evalgate.toml
```

This repo's own [workflow](.github/workflows/ci.yml) runs the gate inside a container with
`--network none` to prove that it is offline.

Typical flow: a PR that edits a prompt must also commit its recordings (`evalgate record`).
The gate compares against the baseline frozen on `main`. When a change is meant to move the
baseline, re-freeze in the same PR so reviewers see both.

## Add your own scorer

```python
from evalgate.scorers import ScoreResult, register


@register
class AmountMatch:
    name = "amount_match"
    version = "1"  # bump on any behaviour change: old baselines become incomparable

    def __init__(self, tolerance: float = 0.0):
        self.tolerance = tolerance

    def score(self, case, output) -> ScoreResult:
        ...  # pure: no randomness, clock, network or model calls
        return ScoreResult(score=1.0, passed=True, reason="amounts match")
```

```toml
[[scorers]]
name = "amount_match"
tolerance = 0.01
```

Import the module before running (e.g. from your `live` factory module or a small wrapper
script). Built-in scorers: `exact_match`, `normalized_match`, `regex_match`,
`label_set_f1`, `operative_verdict`, and `whole_text_verdict` (comparison only).

## Develop

```
python -m pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
python scripts/build_demo_dataset.py   # regenerate the demo set (deterministic)
```

## License

MIT
