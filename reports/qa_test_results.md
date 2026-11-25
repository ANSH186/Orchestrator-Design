# QA Test Results — Advanced Validation

Environment: Python 3.13.7, Windows, project `.venv`.
Final full test suite: **348 passed** (≈5–6 s).
Mutation audit: **17/17 selected mutants killed (100%)**.
Final full run: `final-run-6`, no cache, 8 workers, **2,000/2,000 `ok`**, 30.913 s.
Sample evaluation after hardening: **40/40**, 100%.

---

## 1. Test inventory

| Module | Tests | Area |
|---|---:|---|
| `test_ingestion.py` | 7 | CSV schema and malformed input |
| `test_knowledge_base.py` | 8 | playbook completeness and records |
| `test_policy_supplier.py` | 22 | amendment boundaries, supplier overrides |
| `test_pricing_math.py` | 10 | Decimal money, concessions, FX/period |
| `test_pricing_agent.py` | 16 | normalization paths |
| `test_thread_analyst.py` | 18 | offer extraction grammar |
| `test_security.py` | 46 | injection/banned base cases |
| `test_decision_agent.py` | 13 | precedence and boundaries |
| `test_audit_agent.py` | 10 | independent audit error injection |
| `test_orchestrator.py` | 8 | graph paths and recovery |
| `test_llm_provider.py` | 9 | mock/provider/retry/grounding |
| `test_output.py` | 12 | submission/validation |
| `test_runner.py` | 2 | checkpoint/resume/fallback |
| `test_sample_evaluation.py` | 1 | 40-sample evaluation |
| **QA Phase 4** `test_qa_adversarial_pricing.py` | 46 | adversarial pricing and concessions |
| **QA Phase 5** `test_qa_policy_matrix.py` | 12 | all categories/suppliers and document failures |
| **QA Phase 6** `test_qa_security_adversarial.py` | 52 | Unicode, multilingual, context, scope |
| **QA Phase 7** `test_qa_precedence.py` | 9 | mixed precedence |
| **QA Phase 8** `test_qa_langgraph.py` | 7 | nodes, edges, state, concurrency, failures |
| **QA Phase 9** `test_qa_llm_grounding.py` | 14 | fabricated facts, malformed responses |
| **QA Phase 10** `test_qa_property_fuzz.py` | 2 | 140 oracle cases + 60 malformed fuzz |
| **QA Phase 11** `test_qa_metamorphic.py` | 10 | equivalence/monotonicity/date relations |
| **QA Phase 13** `test_qa_input_reliability.py` | 8 | corrupt CSV, duplicates, empty/bad records |
| **QA Phase 13** `test_qa_runner_resilience.py` | 3 | atomic write, progress failure, resume repair |
| **Audit independence** `test_qa_audit_independence.py` | 3 | differential arithmetic and label check |

---

## 2. Phase 4 — adversarial pricing

Result: **46 passed** after fixes.

Coverage included:

- standard USD, supplier EUR override, supplier GBP override;
- GST-inclusive at 5%, 12%, 18%;
- monthly→yearly and yearly→monthly;
- missing billing period;
- totals, packs, dozens, reams, per-100 units;
- free units;
- tier boundary (up-to `<=`), volume boundary (`>=`);
- list discount, previous-supplier quote discount;
- range high end, correction replacement;
- lakh/k/word notation;
- very large values;
- negative/malformed values;
- ambiguous symbols and unsupported currencies;
- approval exactly at limit versus just over;
- subscription approval amounts;
- independent concession values, probation, exact half-up rounding.

Five failures were discovered before fixes:

1. same-line list price + offer used the list price;
2. list price on a previous line used the list price;
3. order value before offer used the order value;
4. liability cap before offer used the cap;
5. total budget before offer used the budget.

Fix: offer-context scoring/selection and ambiguity fallback. All 46 pass; supplied-data labels unchanged.

A further one-off test verified prior-quote **total** basis is not double-converted:
prior total ₹3,000 for 5 monitors, further 10% off → ₹540. Fixed and covered.

---

## 3. Phase 5 — policy and knowledge-base tests

Result: **12 passed**.

- All 15 category base records checked against explicit expected values.
- All 9 amendment boundaries tested before/on/after.
- LED AMD-08/AMD-07 ordering verified.
- All 40 supplier records checked for status.
- All category caps tested for matching-category isolation.
- All supplier currency overrides checked.
- All statuses exercised through the graph.
- Unknown category and supplier fall back safely.
- Missing policy document rejected.
- Missing category field rejected.
- Conflicting target/walkaway preserved with a warning.
- Unknown supplier/category resolver errors verified.

---

## 4. Phase 6 — security and prompt injection

Result after fixes: **52 QA tests + 46 base security tests passed**.

Initial failures found:

1. zero-width obfuscation bypassed English injection detection;
2. full-width Unicode bypassed detection;
3. Italian, Portuguese, Chinese, Japanese, Korean, Russian and Arabic ignore/accept probes were missed;
4. a standalone “approval has already been granted” claim was missed;
5. a long-message test was malformed (no price, so MISSING_INFO correctly preceded injection) and was corrected.

Fixes:

- NFKC normalization;
- zero-width/bidi-control removal;
- HTML tag stripping while preserving HTML comments;
- generic multilingual ignore+action detection;
- standalone approval-claim detection;
- existing ordinary-business false-positive guards retained.

Full-corpus recheck after fixes:

- known injection threads: **160 / 160**, zero false positives;
- known banned-term threads: **144 / 144**, zero false positives.

False-positive tests cover AI-powered products, ERP systems, system integration, assistant managers, automated invoicing, internal budget approval, net terms, warranties and delivery dates.

Remaining limitation: homoglyph substitution (e.g. Cyrillic “І” for Latin “I”) and languages outside the configured patterns are not guaranteed.

---

## 5. Phase 7 — decision precedence

Result: **9 passed**.

Verified combinations:

- missing + blacklist + injection + banned → MISSING;
- blacklist + injection + banned + price → BLACKLIST;
- injection + banned + final bad price → INJECTION;
- banned + final bad price + approval over → BANNED;
- final bad price + approval over → ABOVE_WALKAWAY;
- acceptable price + approval exact limit → ACCEPT;
- acceptable price + approval over → OVER_APPROVAL_LIMIT;
- probation final bad price + approval over → ABOVE_WALKAWAY;
- probation acceptable price + approval over → OVER_APPROVAL_LIMIT.

The official playbook order was preserved.

---

## 6. Phase 8 — LangGraph orchestration

Result: **7 passed**.

Verified:

- expected nodes: analyze, policy, supplier, security, price, decide, audit, recover, fallback, finalize;
- expected conditional edges from security and audit;
- full state populated on normal path;
- terminal routes skip pricing;
- same graph instance does not leak state between threads;
- concurrent calls match sequential;
- node failure is contained and recorded;
- unknown category/supplier fall back without crashing;
- audit re-checks and fallback labels remain valid.

Existing graph tests additionally verify recovery from a first audit failure and controlled fallback after a repeated failure.

---

## 7. Phase 9 — LLM testing

Result: **14 QA + 9 base tests passed**. No live API key was available.

Mocked/tested:

- correct grounded extraction;
- fabricated period, GST, basis, discounts, free units rejected;
- hallucinated amount/evidence rejected;
- unsupported currency rejected;
- malformed JSON rejected;
- missing schema fields rejected;
- timeout retries bounded;
- 429 retry/backoff;
- prompt delimiters and “untrusted data” instruction;
- deterministic parser does not call the LLM when a usable price exists;
- fabricated-period LLM result falls back to MISSING_INFO;
- LLM path can survive the independent audit only when grounded.

Remaining: **live provider validation unverified**.

---

## 8. Phase 10 — property/fuzz testing

Result: **2 passed**.

- 140 randomized simple offers across all categories, suppliers, dates, rounds, quantities and boundary prices were checked against an independently implemented oracle (policy dates, caps, status, concession, approval, rounding).
- 60 randomized malformed text inputs produced one valid label per thread; no crashes, invalid labels, or silent drops.
- Final-round COUNTER was forbidden and verified by the oracle.

No failures in the final run.

---

## 9. Phase 11 — metamorphic testing

Result: **10 passed**.

Verified relationships:

- irrelevant benign sentence does not change decision/price;
- reordering benign clauses does not change decision/price;
- date across a courier amendment changes the final threshold as expected;
- probation changes the intermediate threshold;
- quantity changes approval outcome without changing normalized price;
- USD vs equivalent INR gives the same normalized price;
- GST-inclusive vs equivalent exclusive gives the same normalized price;
- monthly vs yearly equivalents match;
- pack/total/dozen/ream equivalents match;
- a lower price does not create a worse pre-final decision.

---

## 10. Phase 12 — external dataset generalization

Result: documented in `reports/generalization_assessment.md`.

- Acme-specific loader rejects an external category: `unmapped category name 'Industrial Widgets'`.
- Core pricing/decision works with directly constructed external policy/supplier models.
- External 7% GST, custom FX and probation operated correctly.
- External CHF was correctly missing.
- The architecture is reusable; the Acme KB/decision/security/config layer is not drop-in arbitrary-domain support.

---

## 11. Phase 13 — performance and reliability

Measured on the hardened code in `reports/performance_reliability.json`:

| Scenario | Result |
|---|---|
| 200 rows, 1 worker | 4.271 s |
| 200 rows, 8 workers | 3.337 s |
| Labels sequential vs concurrent | identical |
| 100 rows, cache on | 1.887 s (first fill) |
| 100 rows, cache off | 1.437 s |
| Cache labels | identical |
| Resume after deleting/corrupting 2 checkpoints | 100 rows, 2 retried, 0 errors |
| 2,200-thread synthetic batch | 38.459 s, 2,200 unique, 0 errors |
| 205,036-character thread | 2.261 s, valid label, status ok |
| Full 2,000, 1 worker | 28.915 s, 0 errors |
| Full 2,000, 1-worker labels vs final concurrent submission | identical, 0 mismatches |
| Peak traced memory, 200 rows | 2.15 MB |

A real Windows `PermissionError` during `progress.json` replacement was discovered and fixed with bounded atomic-write retries; progress metadata failure is now non-fatal. Regression tests cover both.

Input corruption tests: **8 passed** — missing columns, corrupt rows, empty messages, invalid dates, non-positive quantity/round, duplicate IDs, invalid counters.

---

## 12. Phase 14 — mutation testing

Result: **17/17 selected mutants killed = 100%**.

Tested mutations:

- concession sign reversal;
- final round using target instead of walk-away;
- approval strict `>` changed to `>=`;
- half-up changed to half-even;
- decision boundary `<=` changed to `<`;
- supplier cap ignored;
- amendment date `<=` changed to `<`;
- GST removal disabled;
- free-unit denominator removed;
- volume threshold changed to strict;
- tier boundary changed to strict;
- 30% advance treated as banned;
- bot injection rule disabled;
- all multilingual detection disabled;
- audit final-label check disabled;
- zero counter allowed;
- prior-quote double basis conversion.

The production workspace was not mutated; each mutation was applied to a temporary copy and restored.

---

## 13. Overall QA result

- No remaining test failures.
- All discovered defects were either fixed with regression tests or documented as residual limitations.
- Full-data labels did not change after hardening.
- Final submission still validates.
- Claims now distinguish sample accuracy, processing completeness, internal audit consistency, and unknown hidden accuracy.
