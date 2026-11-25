# Holdout Evaluation

## Bottom line

**There is no genuine independent holdout available in the supplied materials.**

The only official labels are the 40 rows in `sample_answers.csv`. Every one of those
rows was inspected during development. No untouched labelled rows exist for the full
2,000-thread dataset. Therefore no accuracy number in this project can be presented as
an unbiased estimate of hidden-set generalization.

This report distinguishes:

1. the genuine, prediction-before-answer evaluation procedure;
2. a pseudo-holdout that is useful for regression checking but is **not** independent;
3. the absence of a genuine holdout as a limitation.

---

## 1. Genuine evaluation mechanics

`scripts/qa_evaluation_integrity.py` performed the following:

1. Loaded only `data/sample_threads.csv`.
2. Installed a Python file-open audit hook.
3. Ran the production LangGraph pipeline on all 40 threads.
4. Stored all predictions.
5. Only then opened `data/sample_answers.csv`.
6. Compared expected and predicted labels by `thread_id`.

Measured results:

- Sample-answer opens during prediction: **0**
- Predictions produced: **40**
- Exact matches: **40**
- Incorrect: **0**
- Accuracy: **100.00%**
- All audit checks passed: **yes**
- All outcomes had status `ok`: **yes**
- Source references to sample thread IDs: **0**
- Source references to `sample_answers`: **3**, all in the CLI evaluation loader or a
  report caption, not in the prediction path.

The evaluation procedure itself is not comparing a prediction against itself. It compares
the production graph’s label with a separately loaded expected label.

---

## 2. Why this is still not a holdout

A holdout requires examples that did not influence development. Here:

- all 40 labelled examples were read during development;
- all 40 were used in repeated evaluation runs;
- the full 2,000 unlabelled messages were inspected for grammar coverage;
- parser rules and tests reflect patterns found in those messages.

This is **development-time tuning/awareness**, not label leakage into prediction. But it
means 40/40 is an in-sample regression/evaluation result.

A split of the 40 examples cannot repair this: both halves are already contaminated.

---

## 3. Pseudo-holdout (non-independent)

For reporting only, a deterministic SHA-256 hash split selected a subset:

- Rows in pseudo-holdout: **18**
- Accuracy: **100.00%**
- This is **not a genuine holdout**. Both sides were inspected during development.

No claim of generalization should be based on this split.

---

## 4. Full sample results

### Confusion by action

Expected rows × predicted columns:

| | ACCEPT | COUNTER | ESCALATE | REJECT |
|---|---:|---:|---:|---:|
| **ACCEPT** | 7 | 0 | 0 | 0 |
| **COUNTER** | 0 | 10 | 0 | 0 |
| **ESCALATE** | 0 | 0 | 16 | 0 |
| **REJECT** | 0 | 0 | 0 | 7 |

### Confusion by reason

| | ABOVE_WALKAWAY | ACCEPTABLE_PRICE | BANNED_TERM | BLACKLISTED_SUPPLIER | COUNTER_OFFER | OVER_APPROVAL_LIMIT | PROMPT_INJECTION |
|---|---:|---:|---:|---:|---:|---:|---:|
| **ABOVE_WALKAWAY** | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| **ACCEPTABLE_PRICE** | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| **BANNED_TERM** | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| **BLACKLISTED_SUPPLIER** | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| **COUNTER_OFFER** | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| **OVER_APPROVAL_LIMIT** | 0 | 0 | 0 | 0 | 0 | 9 | 0 |
| **PROMPT_INJECTION** | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

### Incorrect predictions

None on the supplied 40 samples.

---

## 5. What a genuine holdout would require

A meaningful holdout would need one of:

- additional official labelled threads not used during development;
- a pre-registered, held-back subset generated before any code or prompt tuning;
- an independent human labeler applying the playbook to unseen threads;
- a separate synthetic environment with independently derived ground truth, clearly
  labelled as synthetic rather than official.

The adversarial and synthetic suites in this QA project are useful for logic validation,
but their labels are derived independently by the QA process, not supplied by the
competition. They are reported separately and must never be called official accuracy.

---

## Verdict

- **Prediction-time label leakage:** not found.
- **Evaluation mechanism:** genuine prediction-before-comparison, by `thread_id`.
- **40/40:** real on the supplied labelled sample.
- **Independent holdout accuracy:** **unavailable and therefore unclaimed**.
- **Generalization evidence:** insufficient from 40 contaminated examples alone.
