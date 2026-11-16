# ❌ evalgate: FAIL

Prompt `fcc4689a3e7a` (baseline) → `023cd6c8e5a6` (this change). Primary scorer: `operative_verdict`.

| | Baseline | This change | Δ | Regressed | Fixed | p (paired) |
|---|---|---|---|---|---|---|
| **operative_verdict** | 82.1% | 64.3% | -17.9% | 13 | 3 | 0.0106 |

## Why the gate failed

- operative_verdict pass rate dropped 17.9% (82.1% -> 64.3%), limit 2.0%, p=0.0106 < 0.05
- 13 case(s) regressed (pass -> fail), limit 5

## Regressed cases (13)

| Case | Tags | Now | Operative line in output |
|---|---|---|---|
| `ar-construction-017` | arabic, construction | no operative line in output | _none_ |
| `ar-employment-031` | arabic, employment | got accepted, expected rejected | حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بالتنفيذ. |
| `ar-lease-000` | arabic, lease | got accepted, expected partial | حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بالتنفيذ. |
| `ar-lease-024` | arabic, lease | got accepted, expected partial | حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بالتنفيذ. |
| `ar-sale-032` | arabic, sale | no operative line in output | _none_ |
| `ar-tort-016` | arabic, tort | got accepted, expected dismissed | حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بالتنفيذ. |
| `en-employment-001` | english, employment | got dismissed, expected rejected | The court rules: the claim is inadmissible for lack of prior notice. |
| `en-employment-031` | english, employment | no operative line in output | _none_ |
| `en-loan-015` | english, loan | got dismissed, expected accepted | The court rules: the claim is inadmissible for lack of prior notice. |
| `en-sale-014` | english, sale | got partial, expected dismissed | The court rules: the claim is partially accepted and the remaining requests are rejected. |
| `en-sale-032` | english, sale | no operative line in output | _none_ |
| `en-tort-004` | english, tort | got rejected, expected partial | The court rules: the claim is rejected and the claimant bears the costs. |
| `en-tort-016` | english, tort | got rejected, expected partial | The court rules: the claim is rejected and the claimant bears the costs. |

## Fixed cases (3)

- `ar-tort-010`
- `en-construction-017`
- `en-lease-030`

## Per tag

| Tag | n | Baseline | This change | Δ | p |
|---|---|---|---|---|---|
| arabic | 28 | 92.9% | 75.0% | -17.9% | 0.0625 |
| construction | 6 | 83.3% | 83.3% | +0.0% | 0.7500 |
| employment | 8 | 87.5% | 50.0% | -37.5% | 0.1250 |
| english | 28 | 71.4% | 53.6% | -17.9% | 0.0898 |
| lease | 12 | 75.0% | 66.7% | -8.3% | 0.5000 |
| loan | 6 | 100.0% | 83.3% | -16.7% | 0.5000 |
| sale | 12 | 83.3% | 58.3% | -25.0% | 0.1250 |
| tort | 12 | 75.0% | 58.3% | -16.7% | 0.3125 |

## Scores

| Scorer | Pass rate | Mean | n |
|---|---|---|---|
| operative_verdict (primary) | 64.3% | 0.643 | 56 |
| normalized_match | 0.0% | 0.000 | 56 |

## Leakage guards

Mode **exclude**: flagged cases are excluded from scoring. 16 of 72 case(s) flagged.

| Guard | Cases flagged |
|---|---|
| self-retrieval | 8 |
| answer-bearing context | 16 |

<details><summary>Findings</summary>

| Case | Guard | Doc | Detail |
|---|---|---|---|
| `en-loan-003` | self_retrieval | `judg-en-loan-003` | context contains the case's own source document |
| `en-loan-003` | answer_bearing | `judg-en-loan-003` | expected answer appears verbatim in context |
| `en-construction-005` | answer_bearing | `news-en-005` | operative line appears verbatim in context |
| `en-construction-011` | self_retrieval | `judg-en-construction-011` | context contains the case's own source document |
| `en-construction-011` | answer_bearing | `judg-en-construction-011` | expected answer appears verbatim in context |
| `en-employment-013` | answer_bearing | `news-en-013` | operative line appears verbatim in context |
| `en-employment-019` | self_retrieval | `judg-en-employment-019` | context contains the case's own source document |
| `en-employment-019` | answer_bearing | `judg-en-employment-019` | expected answer appears verbatim in context |
| `en-loan-021` | answer_bearing | `news-en-021` | operative line appears verbatim in context |
| `en-loan-027` | self_retrieval | `archive-027-en` | context document is a near copy of the expected judgment (100% of its 5-grams) |
| `en-loan-027` | answer_bearing | `archive-027-en` | expected answer appears verbatim in context |
| `en-construction-029` | answer_bearing | `news-en-029` | operative line appears verbatim in context |
| `ar-loan-003` | self_retrieval | `judg-ar-loan-003` | context contains the case's own source document |
| `ar-loan-003` | answer_bearing | `judg-ar-loan-003` | expected answer appears verbatim in context |
| `ar-construction-005` | answer_bearing | `news-ar-005` | operative line appears verbatim in context |
| `ar-construction-011` | self_retrieval | `judg-ar-construction-011` | context contains the case's own source document |
| `ar-construction-011` | answer_bearing | `judg-ar-construction-011` | expected answer appears verbatim in context |
| `ar-employment-013` | answer_bearing | `news-ar-013` | operative line appears verbatim in context |
| `ar-employment-019` | self_retrieval | `judg-ar-employment-019` | context contains the case's own source document |
| `ar-employment-019` | answer_bearing | `judg-ar-employment-019` | expected answer appears verbatim in context |
| `ar-loan-021` | answer_bearing | `news-ar-021` | operative line appears verbatim in context |
| `ar-loan-027` | self_retrieval | `archive-027-ar` | context document is a near copy of the expected judgment (100% of its 5-grams) |
| `ar-loan-027` | answer_bearing | `archive-027-ar` | expected answer appears verbatim in context |
| `ar-construction-029` | answer_bearing | `news-ar-029` | operative line appears verbatim in context |

</details>

## Whole-text categorizer trap

12 golden answer(s) would be mislabelled by a whole-text categorizer (reasoning mentions other outcomes).
On these outputs: operative-line accuracy **72.2%**, whole-text accuracy 58.3% (22 disagreement(s)).
