# FINAL SYSTEM VALIDATION REPORT — The Procurement Desk

Audit type: independent architecture, correctness, security, robustness, and generalization review
Final verified run: `final-run-6`
Final test suite: **348 passed**
Final submission: `output/submission.csv` — **PASS**
Date: 2026-11-23

---

## 1. Initial audit findings

The initial audit is in `reports/independent_code_audit.md` with severity and reproduced
evidence. Findings and disposition:

| ID | Severity | Finding | Status |
|---|---|---|---|
| C-1 | Critical in LLM mode | LLM facts were grounded only by amount/evidence; fabricated period, GST, basis, discounts, free units, tier or quantity could pass. | **Fixed** |
| H-1 | High | Multi-price messages used the first price (list price, order value, liability cap, budget) instead of the actual offer. | **Fixed** |
| H-2 | High | Audit recomputed expected price with the same PricingAgent implementation; a systematic pricing bug could pass. | **Fixed with independent arithmetic** |
| H-3 | High for external data | KB parser hardcodes Acme’s 15/40/9/8/7/80 counts and category names. | **Accepted limitation** |
| H-4 | High | Security missed zero-width/full-width obfuscation and several languages; standalone approval claim missed. | **Partially fixed** |
| M-1 | Medium | No genuine labelled holdout; all 40 labels were development-visible. | **Unchanged limitation** |
| M-2 | Medium | Extraction remains template-coupled; free-form prose beyond corpus grammar needs LLM/rules. | **Accepted limitation** |
| M-3 | Medium | No hard per-thread wall-clock timeout. | **Accepted limitation** |
| M-4 | Medium | Precedents are parsed but decision rules are still Python-encoded for Acme. | **Accepted limitation** |
| L-1 | Low | Resume trusted an `ok` checkpoint without revalidating label grammar. | **Fixed** |
| L-2 | Low | Validator accepted zero counter price. | **Fixed** |
| L-3 | Low | `existing_checkpoints_used` metric is imprecise. | Informational |
| H-5 | High reliability | Transient Windows `PermissionError` on progress replacement aborted a full run. | **Fixed** |
| H-6 | Medium | Previous-quote **total** basis was applied twice. | **Fixed** |

The audit did not modify the system before documenting these findings.

---

## 2. Evaluation integrity findings

Detailed report: `reports/evaluation_integrity.md`.

Procedure:

1. Loaded only `sample_threads.csv` for prediction.
2. Installed a Python file-open audit hook.
3. Ran the production graph on all 40 samples.
4. Stored all predictions.
5. Only then opened `sample_answers.csv`.
6. Compared by `thread_id`.

Measured:

- Sample-answer opens during prediction: **0**
- Predictions: **40**
- Source references to sample thread IDs: **0**
- Source references to `sample_answers`: 3, all in the CLI evaluation loader/report caption, not in prediction.
- Predictions used actual production LangGraph, not a cached output.
- All 40 were evaluated; no subset or early success.
- No sample labels hardcoded.
- No special-case thread IDs.
- Cache does not participate in sample evaluation.

**Distinction:**

- **Genuine evaluation mechanism:** yes, prediction-before-comparison.
- **Development-time tuning:** yes; all 40 labels and all 2,000 unlabelled messages were inspected during development.
- **Prediction-time data leakage:** not found.
- **Potential leakage:** none found in the prediction path.

---

## 3. Original sample accuracy

Final sample evaluation after hardening:

- Threads: **40**
- Correct: **40**
- Incorrect: **0**
- Accuracy: **100.00%**
- All 40 passed independent audit.
- Report: `reports/sample_evaluation.md`.

This is **sample regression accuracy**, not a blind generalization estimate.

---

## 4. Holdout results

There is **no genuine holdout** in the supplied materials.

- Only 40 official labels exist.
- All 40 were used during development.
- No untouched labelled rows exist for the 2,000-thread dataset.
- A deterministic 18-row pseudo-holdout scored 100%, but it is **not independent** because both halves were already inspected.
- Synthetic/adversarial cases were assigned predicted labels by independent QA arithmetic, not by official competition labels.

Therefore:

- **Genuine holdout accuracy: unavailable.**
- **No claim of hidden-set accuracy is made.**
- Full report: `reports/holdout_evaluation.md`.

---

## 5. Pricing stress-test results

QA module: `tests/test_qa_adversarial_pricing.py` — **46 passed** after fixes.

Covered:

- standard USD, supplier EUR override, supplier GBP override;
- GST inclusive at 5%, 12%, 18%;
- monthly/yearly conversions;
- missing periods;
- totals, packs, dozens, reams, per-100;
- free units;
- tier and volume boundaries;
- list discount and supplier previous-quote discount;
- ranges, correction replacement;
- lakh/k/word notation;
- very large values;
- negative/malformed prices;
- ambiguous symbols and unsupported currencies;
- approval exact/over;
- subscription approval totals;
- independent concession values and exact half-up rounding.

Initial defects/fixes:

1. same-line list price + offer used list price;
2. list price on previous line used list price;
3. order value before offer used the order value;
4. liability cap before offer used the cap;
5. total budget before offer used the budget.

Fix: offer-context scoring and ambiguity fallback (`ambiguous_multiple_prices`), not guessing.
Regression: all 5 cases pass; supplied-data labels unchanged.

Additional defect found by the independent audit:

- previous quote total basis was applied twice;
- regression expects prior ₹3,000/5 = ₹600, 10% off = ₹540;
- fixed; test passes.

---

## 6. Policy test results

QA module: `tests/test_qa_policy_matrix.py` — **12 passed**.

- All 15 categories and explicit values checked.
- All 9 amendments checked before/on/after.
- All 40 supplier statuses checked.
- All category caps checked for category isolation.
- All supplier currency overrides checked.
- Probation/blacklist behavior checked across all suppliers.
- Unknown category/supplier safe fallback.
- Missing policy document rejected.
- Missing category field rejected.
- Conflicting target/walkaway preserved with warning.
- Unknown resolver errors checked.

No defects remained after testing.

---

## 7. Security test results

QA module: `tests/test_qa_security_adversarial.py` — **52 passed**;
base security module — **46 passed**.

Initial failures found and fixed:

1. zero-width obfuscation bypass;
2. full-width Unicode bypass;
3. missed Italian/Portuguese/Chinese/Japanese/Korean/Russian/Arabic ignore+accept forms;
4. missed standalone approval claim;
5. a long-message test was malformed (no price, so MISSING_INFO precedence actually won) and was corrected to include a price.

Fixes:

- NFKC normalization;
- zero-width/bidi-control removal;
- HTML handling that preserves HTML-comment injection text;
- generic multilingual ignore+action detection;
- standalone approval-claim detection;
- existing ordinary-business false-positive guards retained.

Full-corpus verification after fixes:

- injection: **160/160** known threads, zero false positives;
- banned terms: **144/144** known threads, zero false positives.

False-positive regression set includes AI-powered products, ERP systems, system
integration, assistant managers, automated invoicing, internal budget approval,
net terms, warranties and delivery dates.

Remaining limitation: homoglyph substitution and unconfigured languages are not
guaranteed.

---

## 8. Decision precedence results

QA module: `tests/test_qa_precedence.py` — **9 passed**, plus existing decision tests.

Verified:

- missing wins over blacklist/injection/banned;
- blacklist wins over injection/banned/price;
- injection wins over banned/price;
- banned wins over price/approval;
- final above-walkaway wins over approval;
- acceptable price exactly at approval limit → ACCEPT;
- acceptable price just over limit → ESCALATE;
- probation final bad price → REJECT;
- probation acceptable price + over approval → ESCALATE.

The official order is preserved.

---

## 9. LangGraph orchestration results

QA module: `tests/test_qa_langgraph.py` — **7 passed**.

Verified nodes and conditional edges; normal state population; early terminal
routes skip pricing; state isolation across repeated calls; concurrent calls match
sequential; node failure containment; unknown category/supplier fallback; evidence
fields not overwritten; audit recovery and fallback.

The decide node was intentionally corrected to accept a missing PricingAnalysis on
early-terminal routes; previous behavior created unnecessary recoveries.

---

## 10. LLM testing results and limitations

QA module: `tests/test_qa_llm_grounding.py` — **14 passed**;
base provider module — **9 passed**.

Tested with mocked/controlled responses:

- correct grounded extraction;
- fabricated period, GST, basis, discounts, free units rejected;
- hallucinated amount/evidence rejected;
- unsupported currency rejected;
- malformed JSON rejected;
- missing schema fields rejected;
- timeout retry bounded;
- 429/backoff retry;
- prompt delimiters and untrusted-data instruction;
- deterministic extractor skips LLM when price is usable;
- fabricated-period LLM result falls back to `MISSING_INFO`;
- grounded LLM result passes independent audit.

**No live API key was available. Live provider behavior remains unverified.** No
live LLM accuracy is claimed.

---

## 11. Property-based testing results

QA module: `tests/test_qa_property_fuzz.py` — **2 passed**.

- 140 randomized simple offer cases across all categories, suppliers, dates,
  rounds, quantities and boundary prices against an independent oracle.
- 60 randomized malformed text cases; every input produced one valid label.
- No final-round COUNTER; counter integer; concurrent labels matched sequential.
- 140/140 cases matched independent expected labels.

---

## 12. Metamorphic testing results

QA module: `tests/test_qa_metamorphic.py` — **10 passed**.

Verified:

- benign filler does not change decision;
- benign clause reorder does not change decision;
- date across courier amendment changes threshold correctly;
- probation changes intermediate threshold;
- quantity changes approval but not normalized price;
- USD/INR equivalents; GST inclusive/exclusive; month/year; pack/total/dozen/ream equivalents;
- price decrease does not create a worse pre-final decision.

---

## 13. Generalization assessment

Detailed report: `reports/generalization_assessment.md`.

External “Industrial Widgets” category parse:

```text
IngestionError: unmapped category name 'Industrial Widgets'
```

The parser hardcodes Acme category names and 15/40/9/8/7/80 counts, and the
decision/security rules are Acme-specific. The core pricing, concessions, status
and audit architecture worked with directly constructed external models:

- external 7% GST → ₹100 from ₹107 inclusive;
- external USD rate ₹90 → USD 100 = ₹9,000;
- external probation → counter at target;
- external CHF → missing information.

**Honest claim:** reusable architecture with adaptation; not drop-in arbitrary
procurement support. No claim of arbitrary-domain capability is made.

---

## 14. Performance and reliability results

Detailed report: `reports/performance_reliability.md`.

| Scenario | Result |
|---|---|
| 200 threads, 1 worker | 4.271 s |
| 200 threads, 8 workers | 3.337 s |
| Labels sequential vs concurrent | identical |
| 100 threads cache on/off | identical |
| Resume after deleted/corrupt checkpoint | 2 retried, 100/100, 0 errors |
| 2,200-thread batch | 38.459 s, 0 errors, 2,200 unique |
| 205,036-character thread | 2.261 s, status ok |
| Full 2,000, 1 worker | 28.915 s, 0 errors |
| Full 1-worker vs 8-worker labels | identical, 0 mismatches |
| Peak traced memory, 200 rows | 2.15 MB |

A real Windows progress-file lock abort was fixed with bounded atomic-write retries
and non-fatal progress writes. Resume now rejects invalid label checkpoints.

---

## 15. Mutation testing score

Detailed report: `reports/mutation_testing.md`.

- Applicable selected mutants: **17**
- Killed: **17**
- Survived: **0**
- Mutation score: **100%**

Mutants covered concession sign, final-round anchor, approval strictness, rounding,
decision boundary, supplier cap, amendment date, GST, free units, volume threshold,
tier boundary, 30% advance, bot injection, multilingual detection, audit label
equality, zero counter, and previous-quote double basis.

The production workspace was not mutated; each mutation was applied to a temporary
copy.

This is a selected mutation set, not an exhaustive all-branch mutation tool run.

---

## 16. Bugs discovered

1. **LLM grounding accepted fabricated commercial facts** (critical in LLM mode).
2. **Multi-price messages used list/order-value/liability/budget prices** instead of the offer.
3. **Audit reused PricingAgent arithmetic**, so a systematic price bug could pass.
4. **Security zero-width/full-width obfuscation bypass**.
5. **Several language families missed** (Italian, Portuguese, Chinese, Japanese, Korean, Russian, Arabic).
6. **Standalone approval claim missed**.
7. **Previous-quote total basis applied twice**.
8. **Transient Windows progress write aborted a batch**.
9. **Resume trusted invalid label checkpoints**.
10. **Counter price 0 accepted**.
11. **Malformed long-message test** (test defect, not production defect; corrected).

---

## 17. Bugs fixed

All of the above except accepted scope limitations were fixed with regression tests:

- context-aware offer selection;
- stricter LLM grounding for all material facts;
- independent Decimal audit arithmetic;
- Unicode normalization + broader multilingual detection + approval-claim rule;
- previous-quote basis double conversion;
- atomic write retries + non-fatal progress;
- resume label validation;
- counter > 0 validation;
- long-message test corrected;
- 5 multi-price regression tests;
- 1 prior-quote total regression test;
- audit-independence tests.

The supplied-data label set is **unchanged** after all fixes: 2,000/2,000 labels
identical to the pre-hardening run.

---

## 18. Remaining limitations

- **No genuine holdout.** 40/40 is development-contaminated sample accuracy.
- **No live LLM verification.** No API key; only mocks.
- **External knowledge base is Acme-specific.** No arbitrary-domain support.
- **No hard per-thread wall-clock timeout.** Provider HTTP timeout only.
- **Homoglyph substitution and unconfigured languages** are not guaranteed.
- **Deterministic extraction remains template-coupled.**
- **Precedents are documentation, not executable rules.**
- **Five subscription “for this order” threads** remain interpreted as
  `MISSING_INFO` under the explicit missing-period rule; this is a documented
  interpretation, not proven ground truth.
- **Approval-limit billing period** uses normalized price × quantity for one
  normalized period; alternate interpretations would change some labels.
- **No universal 100% accuracy claim.** Hidden accuracy is unknown.

---

## 19. Final submission validation

Final run: `final-run-6`, 8 workers, no extraction cache.

- Threads processed: **2,000**
- Outcome status: **2,000 `ok`**
- Error rows: **0**
- Fallbacks: **0**
- Recoveries: **0**
- Wall time: **30.913 s**
- Labels identical to pre-QA run: **yes, 0 mismatches**

Submission validator:

- Header exactly `thread_id,label`
- Exactly two columns
- 2,000 rows
- Every input ID exactly once
- No duplicates, missing or extra IDs
- Input order preserved
- All labels valid
- All COUNTER prices whole integers > 0
- All non-COUNTER labels end with a colon
- CSV reopens with uniform two-column rows

`output/submission.csv` is **valid and ready**.

---

## 20. Overall reliability assessment

**What is trustworthy:**

- The deterministic pipeline is internally consistent and completes every supplied
  thread.
- The supplied-data labels reproduce exactly before and after hardening.
- The 40 sample labels match exactly.
- Arithmetic, precedence, amendments, supplier overrides and security scopes have
  broad independent tests and mutation coverage.
- The audit now independently catches pricing-engine arithmetic defects.
- The final submission contract is validated.

**What is not proven:**

- Hidden 2,000-thread accuracy.
- Generalization to arbitrary real-world procurement emails.
- Live LLM extraction quality.
- Blind holdout performance.

**Honest final claim:**

> The system is highly reliable on the supplied synthetic Acme distribution and
> has a well-tested, auditable deterministic core. The 100% figure is sample
> accuracy on 40 development-visible labels, not proof of 100% hidden accuracy.
> The architecture is strong; the remaining uncertainty is external generalization
> and the documented ambiguous interpretations.
