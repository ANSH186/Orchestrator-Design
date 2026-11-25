# Evaluation Integrity Audit

This audit distinguishes genuine evaluation from development-time tuning.

## Procedure

1. Loaded only `sample_threads.csv` for predictions.
2. Installed a Python audit hook to record file opens during prediction.
3. Ran the production LangGraph pipeline for all 40 samples.
4. Switched to comparison mode only after all predictions existed.
5. Loaded `sample_answers.csv` and compared by `thread_id`.

## Prediction-path file access

- Files opened during prediction: **293**
- Times `sample_answers.csv` was opened during prediction: **0**
- Source references to `sample_answers`/`sample_submission`: **3**
- Source references to sample thread IDs: **0**

The production prediction path contains no sample-answer access and no sample
thread-ID special cases. The only sample-answer references are the CLI loading
labels for post-prediction comparison and a report caption.

## Results

- Threads evaluated: **40**
- Predictions produced: **40**
- Exact matches: **40**
- Mismatches: **0**
- Accuracy: **100.00%**
- All predictions passed audit: **True**
- All predictions had status ok: **True**

## Confusion by action (expected rows × predicted columns)

| | ACCEPT | COUNTER | ESCALATE | REJECT |
|---|---|---|---|---|
| **ACCEPT** | 7 | 0 | 0 | 0 |
| **COUNTER** | 0 | 10 | 0 | 0 |
| **ESCALATE** | 0 | 0 | 16 | 0 |
| **REJECT** | 0 | 0 | 0 | 7 |

## Confusion by full reason (expected rows × predicted columns)

| | ABOVE_WALKAWAY | ACCEPTABLE_PRICE | BANNED_TERM | BLACKLISTED_SUPPLIER | COUNTER_OFFER | OVER_APPROVAL_LIMIT | PROMPT_INJECTION |
|---|---|---|---|---|---|---|---|
| **ABOVE_WALKAWAY** | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| **ACCEPTABLE_PRICE** | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| **BANNED_TERM** | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| **BLACKLISTED_SUPPLIER** | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| **COUNTER_OFFER** | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| **OVER_APPROVAL_LIMIT** | 0 | 0 | 0 | 0 | 0 | 9 | 0 |
| **PROMPT_INJECTION** | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## Genuine independent evaluation

- The **prediction pipeline** is genuine: it does not read the answer file.
- The comparison is by `thread_id` and evaluates all 40 rows.
- No cached predictions are used in this evaluation; the production graph is run
  directly without the batch extraction cache.

## Development-time tuning and provenance

- All 40 supplied labels were inspected during development.
- The full 2,000 unlabelled messages were also inspected for grammar coverage.
- Rules were derived from the playbook, not hardcoded sample answers.
- Because every labelled example was seen, **40/40 is not a blind holdout result**.

## Pseudo-holdout

A deterministic hash split was evaluated only for reporting: 1.0 accuracy on 18 rows.

**This is not a genuine holdout.** Both halves were already inspected during
development. See `reports/holdout_evaluation.md` for the full explanation.

## Unverified assumptions

- The 40 samples are assumed to be generated from the same rule distribution as
  the full dataset. This cannot be proven from the data.
- No official labels exist for the full 2,000 threads.
- Development-time tuning means sample accuracy is an upper-bound-style
  regression check, not an unbiased generalization estimate.

## Mismatches

- None on the supplied 40 samples.

## Verdict

The 40/40 result is **not caused by prediction-time label leakage**. It is a
genuine run of the production pipeline against labels that were already used
during development. It should be reported as sample regression accuracy, not as
independent proof of generalization.
