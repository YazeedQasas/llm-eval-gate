# evalgate.toml

All relative paths resolve against the config file's directory.

```toml
[dataset]
path = "cases.jsonl"
tags = []                         # keep only cases with any of these tags (a filtered
                                  # run is its own dataset version)

[system]
name = "judgment-prompt"          # adapter name, part of the recording key
model = "claude-sonnet-5-5"       # part of the recording key
prompt = "prompts/judgment.txt"   # its content hash is the prompt version
recordings = "recordings.jsonl"   # committed; replayed by every command except `record`
live = "my_model:make_generate"   # module:factory for `evalgate record`
                                  # factory(prompt_text) -> fn(case, params) -> str
                                  # the module is resolved relative to this file

[system.params]                   # part of the recording key
temperature = 0                   # live recording refuses anything else
seed = 0
max_tokens = 1024
# any other key goes into params.extra

[[scorers]]                       # one or more; first is primary unless [gate] says so
name = "operative_verdict"

[[scorers]]
name = "regex_match"
pattern = 'amount of ([\d,]+)'   # extra keys are the scorer's options
group = 1

[guards]
mode = "exclude"                  # fail: exit 2 on any leak
                                  # exclude: drop flagged cases from scoring
                                  # warn: report only
self_retrieval = { containment = 0.8, ngram = 5 }   # enabled = false to turn off
answer_bearing = { threshold = 0.7, ngram = 3 }
whole_text_trap = {}              # allow_naive_primary = true to permit a whole-text primary

[gate]
primary = "operative_verdict"
baseline = "baselines/main.json"
max_drop = 0.02                   # overall: fail if drop > max_drop AND p < alpha
alpha = 0.05
max_tag_drop = 0.10               # per tag, same rule, for tags with >= min_tag_cases
min_tag_cases = 8
max_regressed = 5                 # optional hard cap on pass -> fail flips
```

## What invalidates what

| You change | Effect |
|---|---|
| prompt text, model, params, a case's input/context | recording key changes: `run`/`check` exit 2 until you `record` |
| a case's expected answer, tags, metadata; add/remove cases; `[dataset] tags` | dataset hash changes: the baseline is incomparable until you `freeze` |
| scorer name, options, or a scorer's `version` | scorers fingerprint changes: re-`freeze` |
| `[guards]` settings or `[gate] primary` | eval-config hash changes: re-`freeze` |
| `[gate]` thresholds | nothing; they apply at compare time |

## Significance

The gate counts flips on the primary scorer: `b` cases went pass → fail and `c` went
fail → pass. If the change made no difference, each flip would be a fair coin, so
`p = P(X >= b)` for `X ~ Binomial(b + c, 1/2)` (an exact one-sided McNemar test). A drop
fails only when it exceeds the threshold and `p < alpha`. Use `max_regressed` for a hard
cap that ignores significance.
