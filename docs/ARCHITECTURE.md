# Architecture — The Procurement Desk

## 1. Overview

The system is a LangGraph-orchestrated multi-agent pipeline with deterministic
business logic. Agents communicate through a typed shared state and Pydantic models.
The orchestrator coordinates the workflow; it does not contain the decision rules.

```text
CSV + Playbook Markdown
        │
        ▼
Ingestion + Knowledge Base (provenance, controlled mappings)
        │
        ▼
LangGraph Orchestrator
  Thread Analyst
       ↓
  Policy Agent → Supplier Agent → Security Agent
       ↓
  route_after_security
    ├─ early terminal → Decision Agent
    └─ price required → Pricing Agent → Decision Agent
       ↓
  Audit Agent
    ├─ pass → finalize
    ├─ fail first time → deterministic recovery → audit again
    └─ fail again → controlled fallback → finalize
        │
        ▼
Batch Runner (cache, checkpoints, resume, concurrency)
        │
        ▼
Submission builder + strict validator → output/submission.csv
```

## 2. Package responsibilities

| Package / module | Responsibility |
|---|---|
| `config.py` | Environment-driven settings, path validation, bounded concurrency. |
| `logging_utils.py` | Structured JSON or text logging. |
| `models/domain.py` | Pydantic models for every boundary: thread, offer facts, policy, supplier, security, pricing, decision, audit, outcomes. |
| `kb/playbook_parser.py` | Parses all 80 playbook documents; controlled category/supplier mappings; provenance; completeness validation. |
| `kb/ingest.py` | CSV ingestion and schema validation; no row reordering. |
| `text/thread_segmentation.py` | Splits earlier/latest supplier and Acme messages; never treats Acme as the supplier. |
| `agents/thread_analyst.py` | Extracts structured offer facts and evidence; deterministic core with optional LLM fallback. |
| `agents/policy_agent.py` | Resolves category + applicable amendments by effective date. |
| `agents/supplier_agent.py` | Resolves controlled identity, status, category caps, currency overrides. |
| `security/injection.py` | Whole-thread prompt-injection rules with ordinary-business false-positive guards. |
| `security/banned_terms.py` | Latest-message banned-contract-term rules with negation/context handling. |
| `agents/security_agent.py` | Combines both security scopes and retains evidence. |
| `pricing/money.py` | Decimal conversion, Indian notation, word numbers, percentages, half-up rounding. |
| `pricing/currency.py` | Standard/supplier FX and billing-period normalization. |
| `pricing/concessions.py` | Concession schedule, probation, approval amount/limit. |
| `agents/pricing_agent.py` | Full normalization trace, normalized price, approval amount. |
| `agents/decision_agent.py` | Pure ordered rules; no language model, no free-form judgement. |
| `agents/audit_agent.py` | Independent re-resolution/re-extraction/re-pricing and decision invariant checks. |
| `llm/provider.py` | Optional provider abstraction with structured output validation and grounding. |
| `orchestrator/state.py` | `GraphState` typed shared state. |
| `orchestrator/graph.py` | LangGraph nodes, conditional edges, recovery/fallback. |
| `orchestrator/runner.py` | Bounded concurrency, extraction cache, per-thread checkpoints, resume, diagnostics. |
| `evaluation/sample.py` | Sample evaluation by `thread_id` and markdown report. |
| `output/submission.py` | Exact two-column submission writer and strict validator. |

## 3. Shared graph state

`GraphState` is a `TypedDict` (total=False) with:

- `thread`: validated `ThreadRecord`
- `analysis`: `ThreadAnalysis`
- `policy`: `ResolvedPolicy`
- `supplier`: `SupplierAnalysis`
- `security`: `SecurityAnalysis`
- `pricing`: `PricingAnalysis | absent` (absent only on the early-terminal path)
- `decision`: `Decision`
- `audit`: `AuditResult`
- `errors`, `warnings`
- `retry_count`, `recovery_attempted`, `fallback_used`
- `final_label`, `outcome_status`
- `execution`: run ID, timings, versions, LLM mode

The state is per thread. Batch durability is achieved with atomic per-thread
checkpoint files, not by sharing graph state between threads.

## 4. Graph nodes and edges

```text
START
  → analyze_thread
  → resolve_policy
  → resolve_supplier
  → security
  → conditional route:
       decide  (if missing info / blacklisted / injection / banned)
       price   (otherwise)
  → decide (pricing may be absent on early terminal routes)
  → audit
  → conditional:
       finalize (audit passed)
       recover  (first audit failure)
       fallback (repeat audit failure)
  → finalize → END
```

The early terminal route is an optimisation. `DecisionAgent` applies the full
official order independently, so routing cannot change the priority.

## 5. Decision and audit separation

- `DecisionAgent` sees the resolved facts and applies the ordered rules.
- `AuditAgent` trusts none of the decision's conclusions. It:
  1. Checks thread identity and round/quantity.
  2. Re-resolves policy and amendments from the raw KB.
  3. Re-resolves supplier status/cap/FX from the raw KB.
  4. Re-extracts the offer deterministically from the original thread.
  5. Re-runs security detectors.
  6. Re-normalizes the price with a fresh `PricingAgent`.
  7. Applies a separately coded decision-invariant checker.
  8. Recomputes the expected counter, approval amount and label.
  9. Validates label syntax.
- For an LLM-extracted offer, the audit accepts it only if the deterministic
  extractor cannot read a price **and** the LLM facts are grounded in the latest
  supplier text (evidence substring and amount text), then re-prices it
  independently.
- Audit failure routes to a strict deterministic recovery. A second failure
  produces a controlled fallback; no row is omitted.

## 6. Financial arithmetic

- All prices and limits use `decimal.Decimal`.
- Binary floats are never used for financial calculations.
- Full precision is retained through comparison.
- Only the final counter is converted to an integer with `ROUND_HALF_UP`.
- `Fraction`/percentage application is deterministic and traceable.
- Approval uses `p × quantity` where `p` is already normalized to the category's
  billing period (month or year). This is the "one billing period" interpretation.

## 7. Reliability

- `ThreadPoolExecutor` bounded by `PROCUREMENT_MAX_WORKERS`.
- LLM provider has a bounded semaphore, timeout and retry handling for 429/5xx.
- Extraction cache keyed by thread content + KB hash + extractor version + LLM mode.
- Per-thread atomic JSON checkpoints in `artifacts/runs/<run-id>/threads/`.
- Resume validates input hash and KB hash; corrupt/incomplete checkpoints are retried.
- Every unhandled thread error gets a recorded diagnostic and a valid safe fallback.
- Submission validation rejects wrong schema, row count, IDs, order, labels,
  counters, nulls and duplicate IDs.
- No input row is silently dropped.

## 8. Security boundaries

- Supplier text is always untrusted data.
- Security scanning occurs before pricing in the logical precedence, and in the
  early route after policy/supplier resolution.
- Prompt injection is scanned across the whole thread.
- Banned terms are scanned only in the latest supplier message.
- LLM prompts delimit supplier text and explicitly prohibit following it.
- LLM output is schema-validated and grounded; failures fall back to deterministic
  extraction or explicit missing information. No fabricated facts are accepted.
- No secrets are logged or committed.

## 9. Extension points

- Add a new category: add the Markdown page and controlled mapping.
- Add amendments: drop a well-formed Markdown amendment into `amendments/`.
- Add supplier overrides: add status/contract lines to the supplier page.
- Add an LLM provider: implement `BaseLLMProvider.extract_offer`.
- Add pricing transformations: extend `OfferFacts` + `PricingAgent` with tests.
- Add output checks: extend `output/submission.py` validation.
