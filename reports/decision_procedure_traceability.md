# Decision Procedure Traceability Matrix

Source of truth: `data/playbook/playbook/policies/decision-procedure.md`
Status: re-read and mapped clause-by-clause after the advanced QA audit.
Final run: `final-run-6` — 2,000/2,000 `ok`; 348 tests; 40/40 samples.

The 40 sample threads are treated as a regression set, not as the specification.
The specification is the playbook; the full 2,000-thread corpus was used to discover
unseen message forms and to build adversarial tests.

---

## 1. Rule-by-rule implementation

| Playbook clause | Implemented in | Independent test evidence | Full-run count / observation |
|---|---|---|---|
| **Rule 1: Missing information** — no usable price in latest supplier offer | `agents/thread_analyst.py`, `agents/pricing_agent.py`, `agents/decision_agent.py` | `test_no_price_is_missing`, `test_unsupported_currency_and_no_price_are_missing`, QA malformed/fuzz tests | 55 threads |
| Rule 1 — subscription price with no billing period | `ThreadAnalyst` marks missing period; `PricingAgent` confirms; `DecisionAgent` rule 1 | `test_subscription_period_missing`, `test_fabricated_llm_period_is_rejected_by_graph` | 5 threads: T10823, T11323, T11552, T11753, T11819 |
| Rule 1 — currency not in units-and-currency table | `security`/`ThreadAnalyst` currency parser; `PricingAgent` unsupported currency | `test_unsupported_currency_is_missing`, QA unsupported JPY/AED/SGD/CHF | 32 threads |
| Rule 1 — correction to earlier quote | `ThreadAnalyst` correction parser; replacement amount | `test_correction_replaces_previous_quote` | 175 correction threads |
| Rule 1 — prior-quote discount and total basis | `ThreadAnalyst`, `PricingAgent` (one basis application), independent audit | `test_previous_quote_uses_supplier_not_acme`, `test_previous_quote_total_basis_is_not_double_converted` | 168 prior-quote discount threads |
| **Rule 2: Blacklisted supplier** | `SupplierAgent` resolves status; `DecisionAgent` rule 2 | `test_supplier_statuses`, `test_blacklist_beats_injection` | 105 threads |
| **Rule 3: Prompt injection anywhere in thread** | `security/injection.py`, `SecurityAgent`; full message list | `test_known_injection_forms_are_detected`, QA multilingual/Unicode/earlier-message tests | 160 threads |
| Rule 3 — ordinary AI/ERP/assistant wording is not injection | `ALLOWED_BUSINESS_PHRASES` neutralization | `test_ordinary_business_wording_is_not_injection`, QA false-positive set | 0 false positives on corpus |
| **Rule 4: Banned terms in latest message only** | `security/banned_terms.py`, `SecurityAgent` latest message | `test_banned_terms_detected`, `test_banned_terms_scope_is_latest_only`, QA allowed-term set | 144 threads |
| **Rule 5: Normalize current offer to p** | `PricingAgent.normalize`; `pricing/money.py`, `currency.py`, `audit_recalc.py` | Pricing agent/adversarial/metamorphic suites | 1,499 priced threads |
| Rule 5 — L(r) formula | `pricing/concessions.py::acceptable_price` | `test_concession_examples_from_samples`, independent concession tests | 1,499 comparisons |
| Rule 5 — p ≤ L(r) → step 6 | `DecisionAgent` price branch | `test_price_exactly_at_level_is_acceptable` | Accept/over branches |
| Rule 5 — otherwise final round → ABOVE_WALKAWAY | `DecisionAgent` round comparison | `test_above_walkaway_on_final_round`, `test_final_price_beats_approval_limit` | 227 threads |
| Rule 5 — otherwise counter at L(r), half-up | `DecisionAgent` + `round_half_up_int` | `test_counter_before_final_round`, `test_counter_round_half_up_exact_half` | 627 threads |
| **Rule 6: Approval limit** | `DecisionAgent` + `approval_amount` / `exceeds_approval_limit` | `test_accept_and_approval_exact_boundary`, `test_acceptable_price_exact_limit_is_accept`, `test_acceptable_price_over_limit_is_escalate` | 359 ACCEPT, 286 OVER_APPROVAL_LIMIT |
| **Rule 7: Probation suppliers L(r)=target** | `SupplierAgent` status; `acceptable_price(probation=True)` | `test_probation_uses_target_every_round`, QA probation precedence tests | 297 probation threads |
| **Which numbers apply** — category base + dated amendments | `PolicyAgent.resolve`, `kb/playbook_parser.py` | `test_policy_supplier.py`, QA full 15-category/9-amendment matrix | 0 unresolved |
| Amendments effective on/before date, later replaces earlier | `PolicyAgent` sorted by `(effective_from, amendment_id)` | `test_led_amendments_apply_by_effective_date_not_filename`, boundary tests | LED AMD-08/07 verified |
| Supplier cap replaces walk-away | `SupplierAgent` cap; `DecisionAgent` effective walkaway | `test_supplier_status_and_caps_are_separate`, `test_contract_cap_replaces_walkaway...` | 6 cap suppliers |
| Supplier FX rate replaces table rate | `SupplierAgent` currency rates; `PricingAgent` / audit recalc | currency override tests; full 4 suppliers | 16 override-using threads |
| **Output format** | `models/decision.py` label validator; `output/submission.py` validator | `test_output.py`, final validator | PASS |

---

## 2. Edge cases present in the 2,000 but not covered by the 40 samples

The system was tested beyond the samples:

| Unseen form | Count | Test coverage |
|---|---:|---|
| Unsupported currency | 32 | QA pricing/security |
| Subscription missing period | 5 | explicit regression |
| Correction | 175 | sample + QA |
| Prior-quote discount | 168 | sample + total-basis regression |
| Quoted range | 62 | sample + adversarial |
| Tiered prices | 68 | sample + boundary tests |
| Volume threshold | 71 | threshold `>=` test |
| Free units | 57 | formula + metamorphic |
| GST inclusive 5/12/18% | 192 | all three rates |
| Per dozen | 115 | equivalent unit test |
| Pack of four | 12 | equivalent unit test |
| Per 100 units | 9 | equivalent unit test |
| Printer ream | 9 | box equivalence test |
| Indian k/lakh/words | many | adversarial tests |
| Large/decimal numbers | several | adversarial tests |
| Multiple prices/list/order/budget | not in supplied data | QA adversarial tests expose and fix |
| Zero-width/full-width injection | not in supplied data | QA security tests expose and fix |
| Multilingual injection | one Hindi + synthetic | QA tests expose and fix |
| Prior quote total basis | not in supplied data | regression test |

---

## 3. Defects found and fixed because the playbook was tested, not just the samples

| Defect | What would have happened | Fix | Regression |
|---|---|---|---|
| Multi-price first-match | List/order-value/liability price could be used as the offer | Offer-context scoring + ambiguity fallback | 5 QA cases |
| LLM fabricated period/GST/basis | Missing-info case could become a priced accept/counter | Ground every material fact in source text | 14 QA LLM tests |
| Audit reused PricingAgent | A systematic pricing bug could pass audit | Independent Decimal arithmetic | differential audit test |
| Unicode zero-width bypass | Injected instruction missed | NFKC + zero-width removal | QA security |
| Several languages missed | Injected instruction missed | Generic ignore+action detection | 11 language cases |
| Standalone approval claim | Injection missed | Approval-claim rule | QA security |
| Previous quote total double basis | Prior ₹3,000/5 became ₹108 after 10% | Apply prior basis once | explicit ₹540 regression |
| Windows progress lock | Batch aborted with PermissionError | bounded atomic retries + non-fatal progress | runner regression |
| Resume invalid label trusted | Invalid checkpoint could persist | label validation on resume | runner regression |
| Zero counter accepted | Invalid submission | counter > 0 | output test |

The supplied-data labels are unchanged after all fixes (2,000/2,000 identical).

---

## 4. Where the 40 examples still do not settle behavior

These are documented ambiguities, not silent assumptions:

1. **Five “for this order” subscription threads** — treated as `MISSING_INFO` because
   the playbook says a subscription price with no billing period is missing.
2. **Approval “one billing period” interpretation** — implemented as normalized
   price × quantity, one normalized period. An alternative quoted-period
   interpretation would change roughly 10 labels.
3. **Novel real-world prose** — deterministic extraction is corpus/template-coupled;
   optional LLM is guarded, not live-verified.
4. **External procurement environments** — the architecture is reusable, but the KB
   loader and Acme decision/security rules require adaptation.

---

## 5. Verification commands

```powershell
python -m pytest -q
python -m procurement_desk evaluate-sample
python -m procurement_desk run --run-id reproduction --workers 8 --no-cache
python -m procurement_desk validate-submission
```

Current evidence:
- **348 tests passed**
- **40/40 sample labels**
- **2,000/2,000 full run `ok`**
- **17/17 selected mutation defects killed**
- final submission validation **PASS**

This is the correct standard for the competition: the sample set is a regression
check, the playbook is the specification, and the full corpus plus independent
adversarial tests is the evidence.
