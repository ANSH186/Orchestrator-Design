# Decision Logic — The Procurement Desk

This document records the implemented decision procedure. The first applicable rule
wins. The playbook is authoritative; this is an implementation reference.

## 1. Rule precedence

1. **Missing information** → `ESCALATE:MISSING_INFO:`
   - No usable price in the latest supplier offer.
   - Unsupported currency (anything other than INR/USD/EUR/GBP).
   - Subscription price with no billing period.
   - Unusable correction/previous quote/total/tier/range structure.
2. **Blacklisted supplier** → `REJECT:BLACKLISTED_SUPPLIER:`
3. **Prompt injection anywhere in the thread** → `ESCALATE:PROMPT_INJECTION:`
4. **Banned contractual term in the latest supplier message** → `ESCALATE:BANNED_TERM:`
5. **Price decision**
   - `p ≤ L(r)` → go to rule 6.
   - `p > L(r)` and `round = R` → `REJECT:ABOVE_WALKAWAY:`.
   - `p > L(r)` and `round < R` → `COUNTER:COUNTER_OFFER:<round_half_up(L(r))>`.
6. **Approval limit**
   - `p × quantity > approval_limit` → `ESCALATE:OVER_APPROVAL_LIMIT:`.
   - Otherwise → `ACCEPT:ACCEPTABLE_PRICE:`.

Probation suppliers use `L(r) = target` in every round; earlier rules still win.
The final-round rejection rule still applies to probation suppliers.

## 2. Policy resolution

For a thread date `d`:

1. Start from the category page.
2. Select amendments of that category with `effective_from <= d` (inclusive).
3. Sort by `(effective_from, amendment_id)`.
4. Apply in order; later applicable amendments replace earlier values for the same
   field.
5. Preserve every applied amendment and its effective date in provenance.
6. Supplier contract caps are applied **after** amendments by the Supplier Agent:
   a cap replaces the effective walk-away for that category.
7. Supplier currency contract rates replace standard rates only for the matching
   supplier and currency.

Key effective-date examples:

- LED: base walk-away 2,200; AMD-08 (2026-12-04) → 2,330; AMD-07 (2026-12-05) → 2,360.
- Courier: 200 before 2026-09-22, 210 on/after.
- Catering: target 280 before 2026-09-20, 270 on/after.
- Headsets approval: 400,000 before 2026-11-09, 320,000 on/after.
- Monitors approval: 1,200,000 before 2026-12-14, 960,000 on/after.

## 3. Normalization order

The deterministic Pricing Agent applies, using `Decimal`:

1. Select the offer amount (correction replacement, previous quote, tier branch,
   range high, or direct amount).
2. Apply list-price discount, previous-supplier-quote discount, qualifying volume
   discount, and free-unit effective factor.
3. Convert `total for all N units` to per-unit.
4. Convert packs, dozens, reams, and per-N quotes to the category base unit.
5. Convert currency to INR using supplier contract rate first, then standard table.
6. Remove GST if the quote is GST-inclusive, using the category's actual rate:
   `price_ex_gst = price_incl_gst / (1 + gst_rate)`.
7. Convert billing period to the category's normalized period:
   - monthly → yearly: ×12
   - yearly → monthly: ÷12
   - missing period on a subscription category: missing information.
8. Compute approval amount `p × quantity`.
9. Keep full precision; round only the counter label with `ROUND_HALF_UP`.

## 4. Concession schedule

For effective target `T`, effective walk-away `W`, maximum rounds `R`, current
round `r`, and exponent `β`:

```text
L(r) = T + (W − T) × ((r − 1) / (R − 1))^β
```

- `r = 1` → exactly `T`.
- `r = R` → exactly `W`.
- Probation → `L(r) = T` for all rounds.

Counter price = `round_half_up(L(r))`, whole INR.

## 5. Category normalization units

Monthly-normalized subscriptions: `cleaning`, `security-guards`.
Yearly-normalized subscriptions: `cloud-servers`, `crm-licenses`, `design-software`.
One-time categories: the remaining ten.

Examples:

- CRM ₹1,600/seat/month → ₹19,200/seat/year (precedent P-06).
- Cleaning ₹12,00,000/site/year → ₹1,00,000/site/month.
- Cloud $1,080.20/server/year at standard USD → ₹91,276.90/server/year.

## 6. Pricing transformations

| Input | Transformation |
|---|---|
| GST-inclusive | Divide by `1 + category GST`. |
| Total for all N | Divide by N. |
| Per dozen | Divide by 12. |
| LED per pack of 4 | Divide by 4. |
| Printer paper per ream | Multiply by 10 (one box = 10 reams). |
| Per 100 units | Divide by 100. |
| Per month ↔ year | ×12 / ÷12 to category period. |
| List discount D% | `list_price × (1 − D/100)`. |
| Further D% off previous quote | `supplier_previous_quote × (1 − D/100)`; never Acme's counter. |
| Volume D% for N+ | Apply only when thread quantity ≥ N. |
| Tier "up to N / larger" | Use first tier when quantity ≤ N, else second. |
| Range "between A and B" | Use higher amount B. |
| Free 1 per N paid | Effective unit price = `P × N/(N+1)`. |
| Correction "read A, not B" | Use A. |
| ₹x.y k / lakh | Convert to full rupees. |
| English words | Convert with Indian grouping. |
| Unsupported currency | Missing information. |

## 7. Approval-limit interpretation

The playbook: `p × quantity (INR excl. GST, one billing period for subscriptions)`.

Implemented interpretation:

- `p` is the normalized price in the category's normalized period:
  - month for cleaning/security-guards;
  - year for cloud/CRM/design;
  - one-time other categories.
- Multiply by quantity once.
- Compare strictly above the effective approval limit; equality is acceptable.

This matches the calibration of category approval limits to target prices
(e.g. design software target 30,000/seat/year × 50 seats = 1,500,000 limit).
The alternative monthly re-annualization of a yearly-normalized category is not
used. The rule is centralized in `pricing/concessions.py`.

## 8. Worked sample decisions

- **T00010** cleaning, qty 300, round 1, ₹1,05,042 incl 18% GST → p=₹89,018.64.
  L(1)=target ₹85,000. p > L, not final round → `COUNTER:COUNTER_OFFER:85000`.
- **T00033** laptops, qty 50, round 2/4, β=2 → L(2)=62,000+8,000×(1/3)²=62,888.89
  → `COUNTER:COUNTER_OFFER:62889`.
- **T00027** design software, qty 10, round 4/4, ₹3,036/seat/month → p=₹36,432
  > final L(4)=₹36,000 → `REJECT:ABOVE_WALKAWAY:`.
- **T00031** CRM, Jade Express (probation), qty 150, round 2/4, p=₹22,277.
  L=target ₹18,000 → p > L, not final → `COUNTER:COUNTER_OFFER:18000`.
- **T00004** headsets, Ivory cap ₹4,400, qty 150, round 1, ₹4,049 incl GST
  → p=₹3,431.36 ≤ L=₹3,500; approval ₹5,14,703 > ₹4,00,000
  → `ESCALATE:OVER_APPROVAL_LIMIT:`.
- **T00028** catering correction ₹264 + prompt injection in latest message
  → injection precedence over price → `ESCALATE:PROMPT_INJECTION:`.

## 9. Recorded ambiguities

- Five threads (T10823, T11323, T11552, T11753, T11819) quote a subscription
  price "per … for this order" with no period. Implemented as
  `ESCALATE:MISSING_INFO:` per the explicit playbook rule; documented in
  `docs/KNOWN_LIMITATIONS.md`.
- P-03's ₹82/USD is illustrative of contract-rate precedence, not a global or
  supplier-recorded rate. It is not added to the FX table.
- Approval-limit subscription interpretation is stated above.
- If a future playbook adds a new precedence branch, update `DecisionAgent`,
  `AuditAgent`, tests, and this document together.
