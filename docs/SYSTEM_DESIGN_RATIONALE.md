# System Design Rationale — How The Procurement Desk Was Built and Why This Architecture Fits the Problem

This document explains the implementation end-to-end and justifies the architecture.
It is written against the actual code and verified results in this workspace, not as a
generic multi-agent design essay.

Related documents:

- `docs/PROJECT_BLUEPRINT.md` — Phase 0 inventory and source rules
- `docs/ARCHITECTURE.md` — component and state reference
- `docs/DECISION_LOGIC.md` — exact precedence and formulas
- `docs/AGENT_RESPONSIBILITIES.md` — agent contracts
- `docs/SETUP_AND_EXECUTION.md` — runnable commands
- `docs/KNOWN_LIMITATIONS.md` — ambiguities and honest limits

---

## 1. The problem being solved

The system receives a supplier negotiation thread and must emit exactly one of:

```text
ACCEPT:ACCEPTABLE_PRICE:
COUNTER:COUNTER_OFFER:<integer INR>
REJECT:ABOVE_WALKAWAY:
REJECT:BLACKLISTED_SUPPLIER:
ESCALATE:MISSING_INFO:
ESCALATE:PROMPT_INJECTION:
ESCALATE:BANNED_TERM:
ESCALATE:OVER_APPROVAL_LIMIT:
```

The difficulty is not merely classifying text. A correct answer requires all of the
following at once:

1. **Conversation understanding** — identify the supplier’s latest offer, distinguish
   it from Acme’s counter, resolve corrections, prior quotes, ranges and tiers.
2. **Rule retrieval with dates** — load the category, apply every amendment effective on
   or before the negotiation date, and apply supplier contract overrides after that.
3. **Financial normalization** — currency, GST, billing periods, totals, discounts,
   free units, packs, dozens, reams, per-N units and Indian number notation, all
   compared in INR excluding GST per the category’s normalized unit.
4. **Security analysis** — prompt injection anywhere in the thread, but banned
   contractual terms only in the latest supplier message, with scope-aware false-positive
   controls.
5. **Exact precedence** — a lower-priority condition must never override a higher one.
6. **Concession and approval math** — a non-linear acceptable-price schedule, probation
   behavior, approval limits, and half-up counter rounding.
7. **Auditability** — every answer must be explainable from source text and source rules.
8. **Operational robustness** — 2,000 threads, no missing rows, no fabricated prices,
   retries, resume, and a strict CSV contract.

That decomposition defines the architecture. The design is intentionally not “one big
LLM prompt” because most of the work is deterministic compliance and arithmetic, not
free-form language generation.

---

## 2. System at a glance

```text
the-procurement-desk.zip / threads.csv / playbook Markdown
                         │
                         ▼
        Ingestion + Knowledge Base (Pydantic, provenance)
                         │
                         ▼
                 LangGraph Orchestrator
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
 Thread Analyst     Policy Agent       Supplier Agent
 (facts only)       (dated rules)      (status/caps/FX)
       │                 │                  │
       └─────────────────┼──────────────────┘
                         ▼
                  Security Agent
        (injection anywhere; banned latest only)
                         │
                conditional early route
                 ┌───────┴────────┐
                 ▼                ▼
          early decision      Pricing Agent
          (no pricing)      (Decimal trace)
                 └───────┬────────┘
                         ▼
                  Decision Agent
              (pure ordered precedence)
                         │
                         ▼
                   Audit Agent
        (independent re-resolution/re-pricing)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          finalize             recover / fallback
              │
              ▼
       Batch Runner + Validator
              │
              ▼
       output/submission.csv
```

The orchestrator coordinates. It does not contain the procurement rules, the arithmetic,
or the decision logic.

---

## 3. How each part is made

### 3.1 Phase 0: source-first engineering

Before implementation, every supplied artifact was inspected:

- all 2,000 thread rows and all 40 sample rows;
- every one of the 80 playbook documents:
  - 15 category pages,
  - 40 supplier pages,
  - 9 dated amendments,
  - 8 precedents,
  - 7 policies,
  - the README;
- the exact CSV schemas, row counts, date range, round distribution, quantity range,
  `our_last_counter` null pattern, and message-history markers.

This produced the counts and edge cases that drove the design:

- 15 categories, 40 suppliers;
- 1,163 threads with no conversation markers, 837 with markers;
- 92 missing-information candidates, 105 blacklisted, 297 probation, 160 injection,
  144 banned-term threads;
- offer forms including totals, GST-inclusive prices, corrections, prior-quote
  discounts, list discounts, volume thresholds, tiers, ranges, free units, dozens,
  packs, reams, per-100 units, word amounts and `k` notation.

The repository records this in `docs/PROJECT_BLUEPRINT.md`. The important engineering
point is that the parser and tests were derived from the actual corpus, not from guesses
about what supplier emails usually look like.

### 3.2 Knowledge base: rule data is parsed, not hardcoded in decisions

`src/procurement_desk/kb/playbook_parser.py` parses every Markdown document into typed
Pydantic records:

- `CategoryPolicy`: target, walk-away, GST, rounds, beta, approval limit, normalized
  period, pack/sub-unit conversions, source path and raw text.
- `SupplierProfile`: status, currency contract rates, category price caps, source and
  raw text.
- `Amendment`: category, effective date, field, amount.
- `Precedent` and `PolicyDocument`: preserved for audit and completeness.

Controlled mappings connect Markdown names to CSV slugs and supplier keys. Lookup is
exact/normalized identity, not unsafe substring matching. The knowledge base validates
expected counts (15/40/9/8/7/80) and records a SHA-256 of all source documents.

Why this matters: a rule change is a data change, not a code change. The decision engine
does not contain category constants or supplier exception tables. This is the single
source of truth that both the Policy/Supplier agents and the Audit Agent consume.

### 3.3 Thread segmentation: separate supplier from Acme

`src/procurement_desk/text/thread_segmentation.py` parses:

```text
[Earlier message — Supplier, 2026-09-17]
...
[Earlier message — Acme Procurement]
...
[Latest message — Supplier, 2026-09-22]
...
```

It returns typed `Message` records with role, supplier name, date and latest flag. Marker-
free threads become one latest supplier message.

This is a small module but a critical one. The system never treats Acme’s counter as the
supplier’s latest offer. The rule “do not mistake `our_last_counter` for the supplier’s
offer” is enforced at multiple levels:

- segmentation separates supplier and Acme messages;
- prior-quote extraction searches earlier **supplier** messages only;
- the CSV `our_last_counter` column is loaded for audit context but is not used in
  pricing or decision logic.

### 3.4 Thread Analyst: language becomes structured facts, not a decision

`src/procurement_desk/agents/thread_analyst.py` converts the latest supplier message into
an `OfferFacts` object:

- currency and quoted amount;
- basis: per unit, total for N, per dozen, per pack, per N, per ream, or prior quote;
- total quantity, pack size, per-N;
- billing period;
- GST-inclusive flag;
- list discount, prior-supplier-quote discount, volume discount/threshold;
- tier threshold/branch;
- free units and paid units;
- correction replacement amount;
- range flag and whether the high end was used;
- unsupported-currency/missing reason;
- source sentence and evidence.

The deterministic parser handles the actual grammar observed in the supplied corpus,
including:

- `₹58.3k`, `₹1.2 lakh`, Indian comma grouping;
- English word amounts such as “one lakh seven thousand three hundred rupees”;
- “between A and B” with the high end used;
- corrections: “should read A, not B” → use A;
- prior quote: “further 10% off our previous quote” → apply to the supplier’s own
  earlier quote, never Acme’s counter;
- totals, packs, dozens, reams, per-100 units;
- tier selection using the thread quantity;
- volume discounts only when the quantity threshold is met;
- free-unit effective price;
- subscription periods.

The analyst does **not** calculate the normalized price, approval amount, action,
reason, or counter price. That separation prevents a language component from silently
making financial or compliance decisions.

### 3.5 Optional LLM extraction: bounded and grounded

`src/procurement_desk/llm/` provides a provider abstraction:

- `none` — deterministic extraction only;
- `mock` — test provider;
- `openai_compatible` — configurable endpoint/model/key/timeout/retries.

It is used only when the deterministic extractor cannot find a usable price. The prompt
places supplier text inside:

```text
<UNTRUSTED_SUPPLIER_MESSAGE>
...
</UNTRUSTED_SUPPLIER_MESSAGE>
```

and explicitly instructs that the delimited text is data, never instructions. Output is:

1. constrained to a JSON schema;
2. validated by Pydantic;
3. rejected unless the evidence is a substring of the source and the amount text is
   grounded in the source;
4. independently re-priced by the Pricing Agent and re-checked by the Audit Agent.

Failures fall back to deterministic extraction or explicit missing information. The full
competition run uses `llm_mode=none` because no key is available; no live LLM accuracy is
claimed. This is deliberately not a single-LLM-call architecture.

### 3.6 Policy Agent: dated rules with effective-date semantics

`src/procurement_desk/agents/policy_agent.py`:

1. resolves the category;
2. selects amendments with `effective_from <= thread.date` (inclusive);
3. sorts by effective date and amendment ID;
4. applies later values over earlier values for the same field;
5. returns effective target, walk-away, approval limit, rounds, beta, GST, normalized
   period, pack conversions and all applied amendments with provenance.

This correctly handles the LED case where AMD-08 (2026-12-04, ₹2,330) precedes AMD-07
(2026-12-05, ₹2,360), despite the larger filename number. Supplier caps are not applied
here; that separation keeps category/date rules distinct from supplier contracts.

### 3.7 Supplier Agent: contract overrides with isolation

`src/procurement_desk/agents/supplier_agent.py` resolves:

- canonical supplier identity;
- Approved / Blacklisted / Probation status;
- category-specific price cap;
- supplier-and-currency FX overrides.

The override rules are isolated:

- a Catering cap for Helix CRM does not affect Helix CRM in another category;
- a GBP rate for Arvind Office Supplies does not change its USD offers;
- status is kept separate from contract terms;
- the cap replaces the effective walk-away only after amendments, as the playbook says.

Status precedence still belongs to the Decision Agent. The Supplier Agent reports the
status; it does not decide the action.

### 3.8 Security Agent: two different scopes, with context

`src/procurement_desk/security/injection.py` scans **all messages** for prompt injection:
directives to an AI/model/bot/assistant/reviewer, override claims, “approval already
granted”, ignore-instructions, admin override, and the supplied Hindi form.

It neutralizes ordinary wording first:

- AI-powered route planning;
- ERP system;
- system integration team;
- assistant manager.

The full corpus verification found 160/160 injection threads with **zero false
positives** on the ordinary phrases.

`src/procurement_desk/security/banned_terms.py` scans **only the latest supplier
message** for:

- automatic renewal, with negation/mutual-renewal exceptions;
- advance/upfront payment > 30%, including “half the order value”;
- unlimited liability for Acme;
- exclusivity requiring Acme to buy only from the supplier.

Allowed terms were explicitly tested: mutual renewal, ≤30% advance, net-30/45/60,
warranties, delivery dates, and “not asking for exclusivity.” The corpus verification
found 144/144 banned-term threads with zero false positives on allowed wording.

The scope difference is critical: an old automatic-renewal clause in an earlier message
is not a violation of the latest offer; an injection anywhere in the thread is.

### 3.9 Pricing Agent: all money is Decimal and all transformations are traced

`src/procurement_desk/pricing/` contains small, independently testable utilities:

- `money.py` — Decimal conversion, Indian notation, word numbers, percentages,
  half-up rounding.
- `currency.py` — standard/supplier FX and monthly↔yearly conversion.
- `concessions.py` — `L(r)`, probation, approval amount and limit comparison.
- `agents/pricing_agent.py` — orchestration of the normalization trace.

Normalization order:

1. choose source amount (correction / prior quote / tier / range high / direct);
2. apply list/prior/volume discount and free-unit factor;
3. convert total → per unit, or pack/dozen/ream/per-N → base unit;
4. convert currency to INR, supplier rate first;
5. remove GST using the category rate;
6. convert billing period to the normalized period;
7. compute `p × quantity`;
8. keep full precision; only counter formatting rounds.

No binary floats are used for financial values. Every transformation appends a
`PricingStep` with before/after values. This is why the audit can re-run pricing and why
a human can inspect exactly how ₹44,07,800 for 60 laptops became ₹73,463.33 per laptop.

### 3.10 Decision Agent: pure precedence, no LLM

`src/procurement_desk/agents/decision_agent.py` is a pure Python ordered procedure:

```text
1. missing information
2. blacklist
3. prompt injection
4. banned term
5. price vs L(r)
6. approval limit
```

The first rule that fires returns immediately. The pricing branch is:

```text
L(r) = T + (W - T) * ((r - 1) / (R - 1)) ** beta
```

- round 1 = target;
- final round = effective walk-away;
- probation = target every round;
- final round and p > L → REJECT;
- otherwise p > L → COUNTER at half-up L;
- p ≤ L → approval check.

The Decision Agent can run without a pricing object on early-terminal routes because the
official procedure does not require pricing when rules 1–4 already fire. That is why the
early route is safe and why the decide/audit contracts accept optional pricing.

All action/reason combinations and mixed precedence cases are tested, including:

- missing + blacklist → missing wins;
- blacklist + injection → blacklist wins;
- injection + banned → injection wins;
- banned + bad price → banned wins;
- probation + earlier rule → earlier rule wins;
- approval exactly at limit → accept;
- exact `.5` counter → rounds up.

### 3.11 Audit Agent: deliberately not a self-confirmation

`src/procurement_desk/agents/audit_agent.py` trusts neither the decision nor the upstream
state. It independently:

1. checks thread identity, quantity and round;
2. re-resolves effective policy and amendments from the raw knowledge base;
3. re-resolves supplier status, cap and FX rates;
4. re-extracts the offer with the deterministic analyst;
5. re-runs injection and banned-term detection;
6. re-normalizes the price with a fresh Pricing Agent;
7. applies a separately coded decision-invariant checker;
8. recomputes the expected action, reason, counter and label;
9. validates label format.

If the state used an LLM offer, the audit accepts it only when deterministic extraction
cannot price the thread and the LLM facts are grounded in the source text; then it
re-prices those facts independently.

The tests intentionally corrupt:

- action;
- counter price;
- normalized price;
- policy/amendment values;
- supplier status;
- security flags;
- offer facts;
- label format;
- thread identity.

The audit catches each case.

### 3.12 LangGraph orchestrator: explicit state and controlled recovery

`src/procurement_desk/orchestrator/graph.py` builds the graph with typed `GraphState`.
The flow is:

```text
START
 → analyze_thread
 → resolve_policy
 → resolve_supplier
 → security
 → route
     ├─ early terminal → decide
     └─ normal → price → decide
 → audit
     ├─ pass → finalize
     ├─ first fail → recover (strict deterministic rerun) → audit
     └─ second fail → fallback → finalize
 → END
```

Why LangGraph rather than a simple function chain?

- conditional early exits are first-class, not nested `if` logic;
- the shared state is inspectable and testable at every node;
- audit recovery is an explicit graph loop, not recursion hidden in a function;
- each agent remains independently testable outside the graph;
- adding a retry or a new precedence-safe node is localized;
- it is still lightweight: no frontend, no database service, no unnecessary framework.

The orchestrator is a controller, not a decision engine. This is the key architectural
choice.

### 3.13 Batch runner: reliability is part of correctness

`src/procurement_desk/orchestrator/runner.py` provides:

- bounded concurrency (`ThreadPoolExecutor`, default 4, verified with 8);
- per-content extraction cache keyed by thread content, KB hash, extractor version and
  LLM mode;
- atomic per-thread checkpoints in `artifacts/runs/<run-id>/threads/`;
- resume that only trusts complete `ok`/`recovered` checkpoints, retrying corrupt or
  failed rows;
- input-hash and playbook-hash validation on resume;
- per-thread error capture and a recorded, valid fallback rather than a dropped row;
- run metadata with versions, decision counts, status counts and failures;
- assembly strictly in original input order.

The verified no-cache run processed all 2,000 threads with 8 workers in about 27 seconds
and produced 2,000 `ok` outcomes.

### 3.14 Output: exact competition contract

`src/procurement_desk/output/submission.py`:

- writes exactly `thread_id,label` with two columns;
- preserves input order;
- uses `COUNTER:COUNTER_OFFER:<integer>` only for counters;
- ends every other label with `:`;
- validates row count, unique/missing/extra IDs, order, nulls, label grammar, integer
  counter prices, and CSV reopenability.

Internal details never enter the submission. They live in:

- `output/internal_decisions.jsonl`;
- `output/run_diagnostics.json`;
- `artifacts/runs/<run-id>/threads/<thread_id>.json`;
- markdown reports.

---

## 4. End-to-end example

Take a thread with:

```text
category=laptops, quantity=50, round=2, R=4, beta=2
latest offer: INR 71,900 per laptop
```

1. Thread Analyst extracts `quoted_amount=71900`, currency INR, per-unit basis.
2. Policy Agent resolves laptops target ₹62,000, walk-away ₹70,000, R=4, beta=2,
   approval limit after any amendments.
3. Supplier Agent resolves status/cap/FX (none here).
4. Security Agent finds no injection; latest message has no banned term.
5. Pricing Agent normalizes to ₹71,900 excl. GST per laptop.
6. Decision Agent computes L(2) = 62,000 + 8,000 × (1/3)² = 62,888.89.
   p > L, round 2 < R=4 → counter at `ROUND_HALF_UP(62,888.89) = 62,889`.
7. Output: `COUNTER:COUNTER_OFFER:62889`.
8. Audit independently re-resolves, re-extracts, re-prices and re-checks all values.

This is sample T00033 and it matches the supplied label exactly.

---

## 5. Why this architecture is optimal for this problem

“Optimal” here means optimal under the competition’s real constraints: exact playbook
compliance, many generated edge cases, no tolerance for invented facts, a strict CSV
contract, limited labels, reproducibility, optional LLM availability, and a need to
explain every answer. The architecture minimizes the probability of a wrong label while
keeping the system maintainable.

### 5.1 It separates language, math, and policy

The three failure modes are fundamentally different:

- language errors: wrong price, wrong period, missed correction;
- math errors: GST, FX, periods, totals, discounts, rounding;
- policy errors: wrong precedence, wrong amendment, wrong cap.

A single LLM call can fail in all three ways at once and cannot be audited cleanly. This
system gives each failure mode its own typed component, its own tests, and its own
evidence. The Decision Agent is pure Python, so a fluent but wrong sentence cannot
change the action.

### 5.2 It uses the right tool for each task

| Task | Best tool here | Reason |
|---|---|---|
| Conversation segmentation | deterministic parser | marker grammar is explicit and exact |
| Price facts | deterministic extractor + optional LLM for ambiguity | corpus grammar is consistent; no key available; LLM guarded |
| Policy dates | deterministic date logic | exact, testable, no model variance |
| FX/GST/concessions | `Decimal` Python | exact arithmetic and half-up rounding |
| Security | context-aware rules | known phrases plus negations; verified 160/160 and 144/144 |
| Decision | pure ordered rules | official first-match-wins procedure |
| Audit | independent recomputation | catches state, extraction and arithmetic errors |

The LLM is an optional language aid, not the system’s brain. This is deliberately
conservative: suppliers are untrusted, and the task explicitly forbids inventing missing
facts or delegating arithmetic/precedence to an LLM.

### 5.3 The Decision Agent is the single authoritative rule engine

Only one component produces the final action, reason and counter. Everything else
supplies validated facts. This avoids:

- two components disagreeing about precedence;
- security findings being overridden by price logic;
- category or supplier exceptions leaking into a prompt;
- audit confirming a decision by asking the same component again.

The audit has a separate decision-invariant implementation, so a bug in the Decision
Agent is more likely to be caught.

### 5.4 Deterministic financial comparison is non-negotiable

Prices include:

- Indian comma grouping;
- decimals and `k`/lakh notation;
- GST at 5%, 12% or 18%;
- USD/EUR/GBP rates, including supplier overrides;
- monthly/yearly conversion;
- totals, discounts, free units, packs, reams, dozens, per-N units;
- ranges and tiers.

Binary floating point would produce avoidable boundary errors. Full-precision `Decimal`
plus a single final `ROUND_HALF_UP` step is the correct design for a decision that can
turn on an exact comparison. The audit re-runs the same deterministic rules and checks
the normalized value.

### 5.5 Scope-aware security prevents both dangerous misses and expensive false positives

The two scopes are not interchangeable:

- injection is dangerous anywhere in the thread;
- a banned contract term matters in the latest offer.

Using one scope for both would either miss earlier injections or incorrectly flag an old
superseded clause. The detector also explicitly neutralizes ordinary business words,
because flagging every “AI-powered” or “assistant manager” would destroy accuracy. The
full-corpus verification of 160/160 and 144/144 with zero false positives is direct
evidence that this context-aware rule layer is appropriate.

### 5.6 The audit makes the architecture trustworthy, not just accurate

Accuracy on 40 samples is necessary but not sufficient. The audit independently checks:

- the right thread, supplier, category, quantity and round;
- the right latest supplier offer;
- the right amendments and supplier overrides;
- the right FX, GST and normalized period;
- the right `L(r)`, approval amount, action, reason, counter and label.

It also catches intentionally corrupted state in tests. This is what turns a collection
of agents into a reliable decision engine: the system can prove its answer against the
source rules, not merely assert it.

### 5.7 LangGraph is used at the correct level of abstraction

LangGraph adds value where the workflow has:

- typed shared state;
- explicit early terminal routes;
- independent retrieval/security stages;
- audit-driven recovery;
- a controlled fallback.

It does not replace the agents, and the graph does not contain business logic. This keeps
the orchestration thin and the business components independently testable. A plain
function chain would work for the happy path, but it would hide the precedence-aware
early exits and recovery loop in nested conditionals, making the official procedure
harder to inspect and test.

### 5.8 Reliability features are not decoration

The competition requires a complete 2,000-row submission. A single unhandled thread must
not silently vanish. The batch runner therefore provides:

- bounded concurrency for throughput;
- cache for repeated extraction;
- atomic per-thread checkpoints;
- hash-validated resume;
- per-thread error records;
- input-order assembly;
- a safe fallback label if recovery fails.

This is why the final run could honestly report 2,000/2,000 `ok` and a passing validator,
and why a crash does not force starting from zero.

### 5.9 The architecture matches the only labels available

There are 40 labelled examples, not thousands. Training a custom classifier would risk
overfitting and would not encode the exact concessions, amendments, or security scopes.
The labelled examples are used for verification, not as hardcoded answers. The rules come
from the playbook, which is the actual authority. The 40/40 result validates the rule
implementation rather than a fitted model.

### 5.10 It is reproducible and inspectable

Every answer has:

- source message and evidence;
- extracted facts;
- effective policy and applied amendments;
- supplier overrides;
- exchange rate and GST rate;
- complete pricing trace;
- security findings;
- decision precedence trace;
- audit checks;
- run metadata with input/KB hashes and versions.

This is useful for debugging, for explaining mismatches, and for changing one rule
without rewriting the system.

---

## 6. Alternatives considered and why they were rejected

### Alternative A: one large LLM prompt that reads the playbook and outputs the label

Rejected because:

- prompt injection in supplier text is a direct threat;
- arithmetic and precedence are exact and should not depend on model sampling;
- no API key is available for the full run;
- 2,000 calls would add latency, cost and rate-limit risk;
- a wrong answer could not be independently recomputed;
- the task explicitly says not to replace the multi-agent architecture with one LLM call.

The implemented optional LLM is restricted to grounded extraction when deterministic
parsing is insufficient.

### Alternative B: train a classifier on the 40 samples

Rejected because:

- 40 labels cannot teach 15 categories, 40 suppliers, 9 amendments and the precedence
  structure;
- the hidden test distribution contains offer forms not present in the samples;
- the playbook is exact; the correct solution is rule execution, not pattern fitting;
- hardcoding sample answers or special-casing thread IDs is forbidden.

### Alternative C: pure keyword rules with no structured facts

Rejected because:

- “per dozen”, “in total for all N”, “further 5% off our previous quote”, tiered prices
  and GST-inclusive prices need semantic structure, not keyword flags;
- banned-term and injection rules need context and negation;
- arithmetic must be traceable and independently auditable.

The system still uses deterministic rules, but on extracted structured facts with
evidence and typed validation.

### Alternative D: every agent is an LLM call

Rejected because:

- Policy date resolution is deterministic;
- supplier caps/FX are table lookups;
- pricing is arithmetic;
- the final decision is an ordered rule procedure;
- unnecessary LLM calls add cost, latency, nondeterminism and attack surface.

### Alternative E: a monolithic Python function that returns the label

Rejected because:

- it would be hard to test each transformation and precedence rule;
- it would be hard to audit independently;
- a change to one category or amendment would risk the whole pipeline;
- failure recovery and resume would be tangled with business logic.

The implemented graph is more code than a one-file prototype, but it is the minimum
structure that supports correctness, auditability and competition-scale operation.

---

## 7. Verified evidence

| Verification | Result |
|---|---|
| Playbook completeness | 15 categories, 40 suppliers, 9 amendments, 8 precedents, 7 policies, 80 documents |
| Sample evaluation | **40/40 = 100%**, compared by `thread_id` |
| Full run | **2,000/2,000 `ok`**, 0 recoveries, 0 fallbacks, 0 error rows |
| Final run | `final-run-6`, no extraction cache, 8 workers, 30.913 s |
| Submission validation | PASS: 2,000 rows, exact 2-column header, unique IDs, input order, valid labels |
| Test suite | **348 passed** |
| LLM mode | `none`; deterministic full run; optional provider tested with mocks, not live-verified |
| Sample hardcoding | none |
| Thread-ID special cases | none |

Decision distribution from the final run:

| Label | Count |
|---|---:|
| `COUNTER:COUNTER_OFFER:*` | 627 |
| `ACCEPT:ACCEPTABLE_PRICE:` | 359 |
| `ESCALATE:OVER_APPROVAL_LIMIT:` | 286 |
| `REJECT:ABOVE_WALKAWAY:` | 227 |
| `ESCALATE:PROMPT_INJECTION:` | 160 |
| `ESCALATE:BANNED_TERM:` | 144 |
| `REJECT:BLACKLISTED_SUPPLIER:` | 105 |
| `ESCALATE:MISSING_INFO:` | 92 |

---

## 8. Honest trade-offs and limits

- The DOCX study manual referenced by the task was absent; the playbook, spec and sample
  answers were treated as authoritative. This is documented.
- Five subscription threads say “per … for this order” with no billing period. They are
  treated as `ESCALATE:MISSING_INFO:` under the explicit missing-period rule. This is an
  interpretation, documented rather than hidden.
- The subscription approval amount uses normalized price × quantity for one normalized
  billing period. This matches category-limit calibration and is documented.
- The deterministic extractor is tailored to the supplied grammar; a substantially
  different corpus may need new rules or the optional LLM path.
- The LLM path is implemented and mock-tested but not live-verified because no API key is
  available.
- The audit is independent but cannot prove that the playbook is internally
  self-consistent; it verifies the implementation against the supplied rules.

None of these limits changes the verified result on the supplied competition data.

---

## 9. How to extend it safely

- **New category:** add the category Markdown and controlled name/slug mapping; add tests
  for its GST, normalized period, packs and concessions.
- **New amendment:** add a dated Markdown file; tests should cover before/on/after.
- **New supplier override:** add the contract line to the supplier page; test category and
  currency isolation.
- **New offer grammar:** add a deterministic extraction rule with evidence; add a pricing
  normalization test; update audit comparison fields if needed.
- **New decision branch:** update `DecisionAgent`, the independent audit invariant
  checker, precedence tests, and `docs/DECISION_LOGIC.md` together.
- **New provider:** implement the provider interface and keep grounding/validation.
- **New output field:** do not add it to the competition CSV; put it in internal
  diagnostics only.

---

## 10. Conclusion

The architecture is not “multi-agent” for appearance. Every agent exists because it owns
a distinct kind of reasoning or evidence:

- the analyst owns language interpretation;
- policy and supplier agents own exact rule retrieval;
- the security agent owns scoped risk detection;
- the pricing agent owns money and units;
- the decision agent owns the official precedence;
- the audit agent owns independent verification;
- LangGraph owns coordination and recovery.

That separation is what makes the system accurate on the 40 labelled examples, complete
on all 2,000 threads, auditable under hostile supplier text, and reproducible without a
live LLM. For a problem whose core is deterministic compliance wrapped around ambiguous
natural language, this is the right balance — and the verified results support that
conclusion.
