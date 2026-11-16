# Adapters and the replay cache

The gate must be offline and deterministic, so CI never calls a model. Outputs are
recorded once on a developer machine and replayed everywhere else.

## Two modes

- **Live** (`LiveAdapter`): calls your `fn(case, params) -> str`, records each output into
  a `ReplayCache`. Temperature is pinned to 0 (and seed to 0 where the provider supports it);
  anything else raises `NondeterministicParams` unless you pass `allow_nondeterministic=True`.
- **Replay** (`ReplayAdapter`): looks outputs up in the cache. A missing output raises
  `CacheMiss` with the case id and adapter. It never falls back to a live call.

## Cache key

```
sha256(canonical_json({
  format, adapter, adapter_version, model, params, case: {id, input, context}
}))
```

- `adapter_version` is the prompt version. Bump it whenever the prompt changes; old
  recordings stop matching and replay fails until you re-record.
- `expected`, `tags` and `metadata` are not in the key: fixing a golden answer doesn't
  force a re-record.
- Canonical JSON (sorted keys, no whitespace, real Unicode) makes the key identical
  across machines and Python versions.

## Recorded outputs file

JSONL, one recording per line, written sorted by `(case_id, key)` so diffs are readable:

```json
{"adapter": "judgment-prompt", "adapter_version": "v1", "case_id": "civ-0001", "key": "3f9c...", "model": "claude-sonnet-5-5", "output": "...", "params": {"extra": {}, "max_tokens": null, "seed": 0, "temperature": 0.0}, "recorded_at": "2026-11-16T10:00:00+00:00"}
```

`recorded_at` is for humans and is not part of the key. Two recordings with the same key
and different outputs are an error: it means the model was not deterministic, and the
cache would no longer describe one system.
