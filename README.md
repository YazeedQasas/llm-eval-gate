# llm-eval-gate

Offline regression gates for LLM systems: golden datasets, deterministic scorers,
frozen baselines, and a CI gate that fails the build when a "better" prompt scores worse.

> Status: phase 1 (contracts). The full README and quickstart arrive with v0.1.

## Core principle

The gate is **offline and deterministic**. CI never calls a model: it replays recorded
outputs from a cache and scores them. The same inputs always give the same score.

## Layout

```
src/evalgate/
  cli.py        evalgate command (run, score, freeze, check, guard)
  schema.py     golden case schema + validation
  adapters.py   system-under-test adapters, replay cache, recorder
  hashing.py    canonical JSON + content hashes
docs/
  schema.md     golden case format
  replay.md     adapters and the recorded-outputs file
tests/
```

## Develop

```
pip install -e ".[dev]"
pytest
ruff check .
```
