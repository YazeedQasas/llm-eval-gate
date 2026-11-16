# Golden case schema

A golden dataset is a UTF-8 JSONL file: one JSON object per line, one case per object.
Blank lines are ignored. Validate a file with:

```
evalgate validate datasets/demo.jsonl
```

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique, stable id. Baselines and diffs are keyed by it, so never reuse one for a different case. |
| `input` | string | yes | What the system under test is asked (e.g. the case summary). |
| `expected` | string | yes | The golden answer. Never shown to the model and not part of the replay cache key. |
| `context` | list of `{doc_id, text}` | no | Documents shown to the model (retrieved passages, attachments). `doc_id` must be unique within the case. |
| `tags` | list of strings | no | Slices for per-tag scores and thresholds, e.g. `["arabic", "civil"]`. Duplicates are dropped. |
| `source_doc_id` | string | no | The document the expected answer came from. If it appears in `context`, the self-retrieval guard flags the case. |
| `metadata` | object | no | Anything else. Not used by scoring. |

Unknown top-level fields are rejected: put extra data under `metadata`. This catches typos
like `expcted` that would otherwise silently drop the golden answer.

## Example

```json
{"id": "civ-0001", "input": "The claimant seeks rescission of a lease ...", "expected": "The court rules: the claim is accepted and the lease is rescinded.", "context": [{"doc_id": "cass-2019-114", "text": "A lease may be rescinded where ..."}], "tags": ["english", "civil"], "source_doc_id": "judg-civ-0001"}
```

## Validation rules

- `id`, `input`, `expected` present, strings, not blank.
- No duplicate `id` in a file (the error names both lines).
- `context` is a list of objects with exactly `doc_id` (non-empty string) and `text` (string).
- `tags` is a list of non-empty strings.
- Errors give the line number and the case id.
