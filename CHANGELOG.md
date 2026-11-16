# Changelog

## 0.1.0

First release.

- Golden case schema (JSONL) with strict validation and line-numbered errors.
- Dataset loader with a content hash and tag filtering.
- Replay cache keyed by prompt hash, model, params and model-visible case content. Live
  recording is pinned to temperature 0. Replay runs with the network blocked.
- Deterministic scorers: `exact_match`, `normalized_match` (incl. Arabic folding),
  `regex_match`, `label_set_f1`, `operative_verdict`, and `whole_text_verdict` (comparison
  only).
- Leakage guards: self-retrieval (by id and by n-gram containment), answer-bearing
  context, and a whole-text categorizer trap report. Modes: fail, exclude, warn.
- Byte-reproducible results and baselines, with fingerprints of dataset, scorers and
  eval config. Incomparable baselines are refused.
- Per-case diff, per-tag deltas, thresholds and an exact paired (McNemar) test.
- `evalgate check` with exit codes 0/1/2, a markdown report and GitHub job summary output.
  Includes a composite GitHub Action and a CI workflow that runs the gate with
  `--network none`.
- Synthetic Arabic/English judgment-prediction demo with seeded leaks and two prompts.
