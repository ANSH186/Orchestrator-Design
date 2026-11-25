# Agent Responsibilities — The Procurement Desk

Every agent has one job and a typed output. No agent is allowed to make a
free-form decision outside its contract. The Decision Agent is the only component
that produces the procurement action; the Audit Agent independently checks it.

## Orchestrator (`orchestrator/graph.py`)

- Controls the LangGraph workflow and conditional routing.
- Does not implement procurement rules.
- Holds the typed shared state, early exits, recovery and fallback.
- Ensures a valid label is finalized for every thread.
- Records execution metadata, errors, and outcome status.

## Agent 1 — Thread Analyst (`agents/thread_analyst.py`)

**Input:** raw `ThreadRecord`.

**Output:** `ThreadAnalysis` with:

- segmented `Message` list and latest supplier message;
- `OfferFacts`: currency, quoted amount, basis (per unit/total/dozen/pack/per-N/
  per-ream/previous quote), total quantity, pack size, per-N, billing period,
  GST inclusiveness, list/previous/volume discounts, tier branch, free units,
  correction flag, range flag, unsupported currency, missing reason;
- contract statements and evidence;
- extraction method.

**Must:** distinguish supplier vs Acme messages; use the latest supplier offer;
use the supplier's own prior quote for "previous quote" discounts; handle
corrections; leave unknowns unknown.

**Must not:** compute normalized price, approval amount, action, reason, or
counter price; use `our_last_counter` as the supplier quote.

**LLM option:** if injected and deterministic extraction has no usable price, a
structured LLM offer may be requested. It is Pydantic-validated and grounded in
the source text before use; otherwise deterministic/missing information wins.

## Agent 2 — Policy Agent (`agents/policy_agent.py`)

**Input:** thread category and date.

**Output:** `ResolvedPolicy` with effective target, walk-away, approval limit,
rounds, beta, GST, normalized period, pack conversions, applied amendments and
provenance.

**Rules:** amendments effective on/before the thread date, inclusive; later
applicable amendments replace earlier; supplier caps are not applied here.

## Agent 3 — Supplier Agent (`agents/supplier_agent.py`)

**Input:** thread supplier and category.

**Output:** `SupplierAnalysis` with canonical identity, status, category cap,
currency overrides and provenance.

**Rules:** controlled identity mapping, no substring matching; status separate
from contract overrides; cap only for the matching category; FX only for the
matching supplier and currency.

## Agent 4 — Security Agent (`agents/security_agent.py`)

**Input:** `ThreadAnalysis` (all messages + latest supplier message).

**Output:** `SecurityAnalysis` with injection and banned-term flags and evidence.

**Prompt injection:** scans the entire thread for text instructing an AI/model/bot/
assistant/automated system/reviewer, claiming an override, or asserting approval
was already granted. Negates ordinary "AI-powered", "ERP system", "system
integration team", and "assistant manager" wording. Language-independent patterns
including the supplied Hindi form.

**Banned terms:** latest supplier message only:
automatic renewal, advance/upfront > 30%, unlimited Acme liability, exclusivity.
Handles allowed wording: mutual renewal, ≤30% advance, net terms, warranties,
delivery dates, "not asking for exclusivity".

**Must not:** alter price or make the decision.

## Agent 5 — Pricing Agent (`agents/pricing_agent.py`)

**Input:** `OfferFacts`, `ResolvedPolicy`, `SupplierAnalysis`, thread quantity.

**Output:** `PricingAnalysis` with quoted amount/currency, exchange rate/source,
GST treatment, period conversion, normalized price, approval amount, complete
trace, transformations, missing reason, evidence.

**Rules:** all arithmetic in `Decimal`; no invented facts; full precision;
counter rounding is done by the Decision Agent via `ROUND_HALF_UP`.

**Must not:** apply decision precedence or decide the action.

## Agent 6 — Decision Agent (`agents/decision_agent.py`)

**Input:** thread, analysis, policy, supplier, security, optional pricing.

**Output:** `Decision` with action, reason, optional integer counter, label,
precedence trace, evidence and calculated values.

**Rules:** pure deterministic ordered rules. First match wins:
missing → blacklist → injection → banned → price → approval.

**Must not:** call an LLM, infer missing facts, or reorder rules for convenience.

## Agent 7 — Audit Agent (`agents/audit_agent.py`)

**Input:** thread and the workflow's analysis/policy/supplier/security/pricing/
decision.

**Output:** `AuditResult` with individual checks, failures, recalculated label
and price.

**Independence:** re-resolves policy/amendments and supplier data from the raw KB,
re-extracts the offer deterministically, re-detects security findings, re-prices
with a fresh Pricing Agent, and applies a separately coded decision invariant
checker. It does not ask the Decision Agent to confirm itself.

**LLM path:** accepts LLM offer facts only when deterministic extraction cannot
price the thread and the facts are grounded in the source; then re-prices them.

**Recovery:** the orchestrator reruns a strict deterministic pipeline on failure;
a second failure produces a controlled fallback and records the audit failures.

## Batch Runner (`orchestrator/runner.py`)

- Bounded concurrency.
- Extraction cache with content/KB/version keys.
- Atomic per-thread checkpoint writes.
- Resume only trusts completed `ok`/`recovered` checkpoints; corrupt or failed
  checkpoints are retried.
- Records errors, status, decision counts and metadata.
- Guarantees every input thread has a checkpoint/outcome; no silent drops.

## Output layer (`output/`)

- `write_submission` writes exactly two columns in input order.
- `validate_submission` enforces header, columns, row count, unique/missing/extra
  IDs, order, label grammar, integer COUNTER prices, trailing colons, nulls, and
  CSV reopenability.

## Separation summary

| Concern | Owner |
|---|---|
| Language interpretation | Thread Analyst (optional LLM) |
| Policy/date resolution | Policy Agent |
| Supplier status/overrides | Supplier Agent |
| Security/contract risk | Security Agent |
| Arithmetic | Pricing Agent / Decimal utilities |
| Procurement action | Decision Agent |
| Independent verification | Audit Agent |
| Coordination | Orchestrator |
| Durability and output | Batch Runner / Output layer |
