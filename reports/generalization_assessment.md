# Generalization Assessment

## Verdict

The **agent and pricing architecture is reusable**. The **knowledge-base loader,
decision precedence, security policy, and amendment schema are currently Acme-specific**.
The system cannot accept an arbitrary procurement playbook by dropping in new
Markdown files.

This is an architectural scope statement, not a failure of the Acme competition run.

---

## 1. External knowledge-base probe

A valid category document for a fictional “Industrial Widgets” category was created:

```text
# Category: Industrial Widgets
GST: 7%
Target: ₹100
Walk-away: ₹120
R: 3, beta: 1
Approval limit: ₹10,000
```

Result:

```text
IngestionError: unmapped category name 'Industrial Widgets'
```

Reason: `CATEGORY_DISPLAY_TO_SLUG` is a hardcoded Acme mapping. Even with a mapping entry,
`KnowledgeBase._validate` requires exactly:

- 15 categories,
- 40 suppliers,
- 9 amendments,
- 8 precedents,
- 7 policy documents,
- 80 total documents.

A different company with 2 categories or 17 categories is rejected before operation.

---

## 2. What works with different data

Using directly constructed external models (no Acme KB parsing), the deterministic
core successfully handled:

| External scenario | Observed result |
|---|---|
| Different company/category `Industrial Widgets`, target 10,000, walk-away 12,000, approval 100,000 | pricing and decision operated normally |
| Supplier FX override USD → ₹90 (not Acme’s table) | USD 100 → ₹9,000 |
| GST 7% inclusive price ₹107 | normalized to ₹100 |
| Probation supplier, round 2/3, ₹11,000 against target ₹10,000 | `COUNTER:COUNTER_OFFER:10000` |
| Unsupported external currency CHF | `missing_information=true`, reason `unsupported_currency` |

Evidence: `reports/generalization_assessment.json`.

This demonstrates that the arithmetic, Decimal normalization, concession formula,
approval comparison, and status logic are reusable if a proper configuration layer
supplies the policy data.

---

## 3. What is reusable

- Pydantic domain models.
- Decimal money parsing and arithmetic.
- FX/GST/billing-period normalization utilities.
- Concession formula and approval-limit comparison.
- Supplier status/cap/FX override structure.
- LangGraph state/workflow pattern.
- Audit structure and recovery/fallback pattern.
- LLM provider abstraction, schema validation, grounding pattern.
- Submission builder/validator.
- Extraction grammar for the Acme synthetic templates (needs adaptation for a new corpus).

## 4. What is Acme-specific

| Component | Why it is specific |
|---|---|
| `CATEGORY_DISPLAY_TO_SLUG` | Hardcoded 15-name mapping. |
| KB completeness counts | Hardcoded 15/40/9/8/7/80. |
| `DecisionAgent` precedence | Implements Acme’s exact rule order in Python. |
| Security rules | Acme-specific banned terms and the observed injection phrase families. |
| Amendment schema | Three fields only; Acme Markdown change wording. |
| Precedents | Parsed and preserved, but not executed as configurable rules. |
| Thread extractor | Tuned to Acme’s generated offer grammar. |

## 5. What a general product would need

To claim arbitrary procurement support:

1. A configuration profile replacing the hardcoded name mapping and counts.
2. A policy DSL or rule registry for decision precedence, not Python `if` branches.
3. A generic amendment schema with field declarations.
4. Configurable security/contract-term policies.
5. A corpus-independent extraction layer or LLM-assisted extractor with grounding.
6. Precedents represented as executable test cases or rules.
7. External label/annotation workflow.

Until those exist, the honest claim is:

> “The architecture is reusable for another Acme-like environment with code/config
> adaptation; it is not a drop-in arbitrary procurement platform.”

---

## 6. Test status

- External category parse: **fails as expected** under current Acme-specific loader.
- External core pricing/decision via constructed models: **works**.
- External 7% GST: **normalizes correctly**.
- External FX override: **works**.
- External probation: **works**.
- External unsupported currency: **missing information**.
- No claim of arbitrary-domain support is made.
