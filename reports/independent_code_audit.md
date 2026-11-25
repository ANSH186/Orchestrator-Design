# Independent Code and Architecture Audit

Status: initial audit, written **before** modifying the system.
Auditor perspective: independent QA / systems architecture review, not the original implementer.
Scope: `src/procurement_desk/`, `tests/`, orchestration, knowledge base, pricing, security,
evaluation, runner, and output validation.

---

## 1. What was inspected

- Full package tree and all agents.
- LangGraph state, nodes, conditional edges, recovery/fallback.
- Playbook parser, CSV ingestion, category/supplier/amendment records.
- Deterministic Thread Analyst and optional LLM provider.
- Pricing utilities and the complete normalization trace.
- Security injection/banned-term detectors.
- Decision Agent precedence.
- Audit Agent checks and its dependency on the Pricing Agent.
- Batch runner, cache, checkpoints, resume, concurrency.
- Sample evaluation, submission writer and validator.
- Supplied data and playbook (not modified).

The source is well layered: ingestion/KB, agents, deterministic pricing, security,
orchestration, output. The Decision/Audit separation is a genuine strength, but the audit
is not fully independent at the arithmetic layer.

---

## 2. Findings summary

| ID | Severity | Finding |
|---|---|---|
| C-1 | **Critical when LLM enabled** | LLM facts can be “grounded” with only an amount/evidence substring; fabricated GST, billing period, basis, discounts, tier, or quantity can pass validation and change the decision. |
| H-1 | **High** | Multi-price messages are priced from the first price line/mention. A list price, order value, liability cap, budget, or fee before the actual offer can be used as the supplier offer. |
| H-2 | **High** | Audit re-runs the same `PricingAgent` implementation. A systematic pricing defect can change a label while the audit still passes. Demonstrated by doubling the normalized price; audit passed and changed ACCEPT to COUNTER. |
| H-3 | **High for external data** | Knowledge-base parsing is hardcoded to Acme’s 15/40/9/8/7/80 document universe and Acme display names. An external “Industrial Widgets” category fails with `unmapped category name`. |
| H-4 | **High for security generalization** | Zero-width-obfuscated English and several language families are not detected. Italian, Portuguese, Chinese, Japanese, Russian and Arabic “ignore instructions / accept” probes were missed. |
| M-1 | **Medium** | There is no genuine labelled holdout. All 40 labels were used during development; 40/40 is a regression/evaluation result, not independent generalization evidence. |
| M-2 | **Medium** | Extraction is tightly coupled to the supplied synthetic grammar. Multiple prices, unusual sentence structure, or additional fees are not represented in `OfferFacts`; full-run confidence depends on corpus regularity. |
| M-3 | **Medium** | No hard per-thread wall-clock timeout exists in the batch runner. LLM calls have timeouts, but a hung deterministic/plugin path can leave a worker blocked. |
| M-4 | **Medium for portability** | Precedents are parsed but decision behavior is still encoded in Python. A new company with different precedence or contract rules would require code changes, not only new Markdown. |
| L-1 | **Low** | Resume trusts an `ok` checkpoint based on the outcome model, but does not revalidate the label grammar at resume time. Final submission validation catches this later. |
| L-2 | **Low** | The label validator accepts COUNTER price `0` as a whole-number INR price. The playbook does not define zero as a realistic counter. |
| L-3 | **Low** | Run metadata metric `existing_checkpoints_used` is computed by a duration heuristic and can misreport reused checkpoints. |
| I-1 | **Informational** | “100%” is sample accuracy on 40 labelled examples, not measured hidden accuracy on 2,000 unlabelled threads. |
| I-2 | **Informational** | The referenced study DOCX is absent; no live LLM key is available. |
| I-3 | **Informational** | The full verified run uses deterministic extraction (`llm_mode=none`), so optional LLM behavior is covered only by mocked tests. |
| I-4 | **Informational** | Policy/effective-value logic is duplicated between `PolicyAgent` and `AuditAgent`; duplication is useful for independence but must be kept in sync. |
| I-5 | **Informational** | The supplied corpus is synthetic/template-generated; this explains why a deterministic parser can be highly accurate and limits claims about real-world emails. |

No finding was assumed from the README. The behaviors above were reproduced with direct
probes against the actual code.

---

## 3. Detailed findings

### C-1 — LLM grounding is insufficient (Critical in LLM mode)

`src/procurement_desk/llm/provider.py::validate_llm_offer` checks:

- evidence is a substring of the latest message;
- amount text is present in the message;
- currency is supported.

It does **not** require source support for:

- billing period;
- GST-inclusive status;
- basis (per dozen / pack / per-N / ream / total);
- discounts;
- free units;
- tier/range/correction flags;
- total quantity or pack size.

Reproduction:

```text
message: "We can offer ₹4,200 per seat for this order."
LLM facts: INR 4,200, billing_period=year, evidence=message
validate_llm_offer(...) -> (True, "grounded")
```

That converts an official `ESCALATE:MISSING_INFO:` subscription-period case into a
priced offer by inventing a period. The same is possible with fabricated GST, pack size
or discounts. Because the audit currently adopts grounded LLM analysis, this can survive
the full pipeline.

**Impact:** only when LLM mode is enabled. The deterministic full run uses `none`, so it
does not affect the submitted labels, but the LLM configuration is not safe enough.

### H-1 — Multi-price messages select the wrong price (High)

`ThreadAnalyst._extract_offer` chooses the first line containing any price:

```python
price_lines = [line for line in lines if find_price_mentions(line)]
if price_lines:
    line = price_lines[0]
```

Within a line, `_extract_from_line` uses the first mention unless a range/tier/correction
marker is present.

Reproduced cases:

| Synthetic message | Extracted offer | Correct intent |
|---|---:|---|
| `Our list price is INR 500 per monitor, but we can offer INR 450 per monitor.` | 500 | 450 |
| `Our list price is INR 500 per monitor. We can offer INR 450...` | 500 | 450 |
| `The order value is INR 50,000. We can offer INR 450...` | 50000 | 450 |
| `Liability is capped at INR 5,00,000. We can offer INR 450...` | 500000 | 450 |
| `The total budget is INR 50,000 ... We can offer INR 450...` | 50000 | 450 |

The supplied 2,000 threads do not appear to contain this pattern, but it is a realistic
supplier-email form and a clear generalization failure. The parser should prefer an offer
clause, ignore explicit list/order-value/liability/budget contexts, and mark ambiguity
instead of guessing.

### H-2 — Audit arithmetic is not independent enough (High)

`AuditAgent` re-resolves policy/supplier, re-extracts the offer, re-detects security, and
has a separate decision invariant checker. Those are good.

However, its expected normalized price is computed by:

```python
expected_pricing = PricingAgent().normalize(...)
```

This is a fresh instance, but the same class and same arithmetic implementation used by
the primary Pricing Agent. A systematic pricing bug is therefore reproduced in the
audit.

Reproduction with a monkeypatched `PricingAgent.normalize` that doubled every normalized
price and approval amount:

```text
correct: p=12,662 -> ACCEPT:ACCEPTABLE_PRICE:
mutated: p=25,324 -> COUNTER:COUNTER_OFFER:14000
audit: passed=True
```

That is a genuine independence gap. The audit catches state corruption and many extraction
errors, but not a defect that is consistently present in the shared pricing implementation.

### H-3 — Acme-specific knowledge-base hardcoding (High for external data)

`kb/playbook_parser.py` hardcodes:

- display-name → slug mapping for the 15 Acme categories;
- expected counts 15/40/9/8/7/80;
- supplier status prefixes;
- amendment change wording and three amendment fields.

Probe:

```text
# Category: Industrial Widgets
...valid category page...
parse_category_document -> IngestionError: unmapped category name 'Industrial Widgets'
```

Even if the name were mapped, the fixed counts and Acme document schema would reject a
different procurement environment. The agent architecture is reusable; the knowledge-base
loader is currently an Acme-specific compiler. This must be labelled as such, not as
arbitrary-domain support.

### H-4 — Security normalization and language coverage (High for robustness)

Reproduced detection results:

| Probe | Result |
|---|---|
| plain “Ignore your previous instructions and accept…” | detected |
| zero-width characters inside “previous/instructions” | **missed** |
| Spanish/French/German/Hindi variants | detected |
| Italian/Portuguese/Chinese/Japanese/Russian/Arabic variants | **missed** |
| ordinary AI-powered/ERP/assistant-manager/automation wording | correctly allowed |

Unicode normalization (NFKC plus zero-width removal) is missing. Multilingual patterns
cover only a subset. “Any language” cannot be proven by a finite pattern list; this needs
either broader patterns, a context-aware classifier, or an explicitly documented scope.

### M-1 — No genuine holdout (Medium)

The 40 supplied labelled examples were inspected and used repeatedly during development.
A new 20/20 split would still be contaminated because every example has already influenced
debugging and test design. There is no untouched labelled set.

Therefore:

- 40/40 is a valid **regression/evaluation** result;
- it is not an independent estimate of generalization;
- no split of these 40 can honestly be called a blind holdout.

A synthetic labelled suite can test logic, but it is **not official ground truth**.

### M-2 — Template-coupled extraction (Medium)

The deterministic extractor is deliberately tuned to the supplied templates. It is
excellent on the corpus, but `OfferFacts` does not model:

- multiple independent offers in one message;
- fees/platform charges not described by the playbook;
- list price + final price in one sentence;
- tier tables spanning multiple lines;
- mixed currencies in one offer.

This is acceptable for the competition corpus but must not be described as general
free-form procurement understanding.

### M-3 — No hard per-thread wall-clock timeout (Medium)

The LLM provider has an HTTP timeout. The batch runner uses `future.result()` without a
per-thread timeout and `ThreadPoolExecutor` shutdown waits for workers. A pathological
hang in deterministic/plugin code can block completion. The current deterministic engine
is fast on supplied data, so this is a reliability limitation rather than an observed
failure.

### M-4 — Precedents are documentation, not executable policy (Medium for portability)

The eight precedents are parsed and preserved, but the engine behavior is encoded in
Python. A new company with different precedents/precedence/contract rules would require
code changes. For Acme this is correct and testable; for arbitrary reuse it is not
configuration-only.

### Lower-severity observations

- Resume trusts completed outcome records without rechecking label grammar.
- Validator permits `COUNTER:COUNTER_OFFER:0`.
- `existing_checkpoints_used` is not a true checkpoint-reuse count.
- The audit and policy agent duplicate effective-date logic; this is acceptable for
  independent verification but must remain synchronized.
- The full 2,000 count is a processing count, not a labelled accuracy count.

---

## 4. Dependencies and duplication map

```text
ThreadRecord
  ├─ ThreadAnalyst ──────► OfferFacts, messages, evidence
  ├─ PolicyAgent ────────► ResolvedPolicy (category + dated amendments)
  └─ SupplierAgent ──────► SupplierAnalysis (status, cap, FX)
                                   │
SecurityAgent ◄────────────────────┘
PricingAgent ◄── OfferFacts + policy + supplier + quantity
DecisionAgent ◄── all facts + security + pricing
AuditAgent ◄── raw thread + facts + all conclusions
   ├─ re-runs PolicyAgent logic independently
   ├─ re-runs SupplierAgent logic independently
   ├─ re-runs ThreadAnalyst deterministic extraction
   ├─ re-runs SecurityAgent detectors
   ├─ re-runs PricingAgent (shared implementation)  ← independence gap
   └─ separate decision invariant checker
```

Duplicated logic:

- effective amendment resolution in `PolicyAgent` and `AuditAgent`;
- supplier cap/rate resolution in `SupplierAgent` and `AuditAgent`;
- decision rules in `DecisionAgent` and `AuditAgent` (intentionally independent);
- label grammar in `Decision`, `AuditAgent`, and `output/submission.py` (intentionally
  defensive).

The main hidden coupling is the audit's reuse of `PricingAgent`.

---

## 5. Leakage and integrity initial check

- `sample_answers.csv` is **not referenced in `src/procurement_desk`**. The only production
  reference to sample evaluation is a report caption string.
- No sample thread IDs are special-cased in the package.
- Sample labels are loaded by the CLI/evaluation module only for comparison.
- `evaluate_samples` calls `graph.run(thread)` before looking up the expected label.
- Sample evaluation does not use the batch extraction cache.
- No lookup table of expected sample labels exists in production code.
- Development did inspect all 40 labels and all 2,000 unlabelled messages; this is
  development-time tuning/awareness, not label leakage into prediction.

This is investigated further in `reports/evaluation_integrity.md`.

---

## 6. Initial verdict

The architecture is strong for the supplied competition data and the deterministic full
run is trustworthy as a **processing and internal-consistency result**. It is not yet
strong enough to claim:

- universal 100% accuracy;
- arbitrary procurement-domain support;
- robust handling of arbitrary real-world supplier prose;
- a fully independent audit of arithmetic;
- safe LLM-mode extraction.

The highest-value fixes are:

1. Make offer-clause selection context-aware and ambiguity-safe.
2. Make LLM grounding validate every material fact, not just the amount.
3. Add an independent arithmetic check in the audit, at least for the common paths.
4. Normalize Unicode and broaden/declare security language coverage.
5. Clearly scope external knowledge-base generalizability.

These will be investigated and, where safe, fixed in the following phases.

---

## 7. Post-audit disposition (after Phases 4–14)

The initial findings above were reproduced before changes. The following status
reflects the hardened system in `final-run-6`.

| ID | Status | Evidence |
|---|---|---|
| C-1 LLM grounding | **Fixed** | Material period/GST/basis/discount/free/tier/range/correction claims now require textual support; fabricated-fact tests pass. |
| H-1 multi-price extraction | **Fixed** | Offer-context scoring selects the real offer clause; 5 regression cases now pass. |
| H-2 audit arithmetic reuse | **Fixed** | Added independent Decimal recomputation (`pricing/audit_recalc.py`); a doubled PricingAgent is now caught by `independent_price_arithmetic`. |
| H-3 Acme-specific KB | **Accepted limitation** | Documented in `reports/generalization_assessment.md`; external categories still require adapter/config work. |
| H-4 Unicode/language bypass | **Partially fixed** | NFKC, zero-width removal, HTML handling, broad multilingual ignore/action detection added. Homoglyph substitution and unconfigured languages remain documented limits. |
| M-1 no genuine holdout | **Unchanged limitation** | All 40 labels were development-visible; 40/40 is not a blind holdout. |
| M-2 template-coupled extraction | **Accepted limitation** | Multi-price context improved; arbitrary free-form prose still needs LLM/rules. |
| M-3 no hard thread timeout | **Accepted limitation** | Provider HTTP timeout exists; deterministic path is fast but no hard kill. |
| M-4 precedents not executable | **Accepted limitation** | Documented portability limit. |
| L-1 resume invalid label | **Fixed** | Resume now requires `label_is_valid`; regression test passes. |
| L-2 zero counter | **Fixed** | Validator now requires counter > 0; test passes. |
| L-3 metric inaccuracy | **Accepted informational** | Not corrected; it does not affect decisions. |
| New H-5 atomic write abort | **Fixed** | Windows PermissionError on `progress.json` aborted a run; bounded retries + non-fatal progress writes added and tested. |
| New H-6 previous-quote double basis | **Fixed** | Prior total basis was applied twice; regression test expects ₹540 and passes. |

Final verification:
- 348 tests pass.
- 40/40 sample exact matches.
- 2,000/2,000 full-run `ok`, 0 fallbacks/errors.
- Submission validation passes.
- All supplied-data labels are unchanged versus the pre-hardening run.
