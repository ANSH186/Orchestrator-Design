# Sample Evaluation — The Procurement Desk

Generated: 2026-11-23T16:17:37.961587+00:00
Playbook hash: `14b36328afb1c704b45258903081e0f2890236642a6bcfe4c921546ac23cfcce`
LLM mode: `none`

## Headline

- Threads evaluated: **40**
- Exact-match correct: **40**
- Exact-match incorrect: **0**
- Exact-match accuracy: **100.00%**
- Comparison key: `thread_id` from `sample_answers.csv` (not row position).

## Confusion by action

| expected \ predicted | ACCEPT | COUNTER | ESCALATE | REJECT |
|---|---|---|---|---|
| **ACCEPT** | 7 | 0 | 0 | 0 |
| **COUNTER** | 0 | 10 | 0 | 0 |
| **ESCALATE** | 0 | 0 | 16 | 0 |
| **REJECT** | 0 | 0 | 0 | 7 |

## Confusion by full reason

| expected \ predicted | ABOVE_WALKAWAY | ACCEPTABLE_PRICE | BANNED_TERM | BLACKLISTED_SUPPLIER | COUNTER_OFFER | OVER_APPROVAL_LIMIT | PROMPT_INJECTION |
|---|---|---|---|---|---|---|---|
| **ABOVE_WALKAWAY** | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| **ACCEPTABLE_PRICE** | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| **BANNED_TERM** | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| **BLACKLISTED_SUPPLIER** | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| **COUNTER_OFFER** | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| **OVER_APPROVAL_LIMIT** | 0 | 0 | 0 | 0 | 0 | 9 | 0 |
| **PROMPT_INJECTION** | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## Per-thread results

| thread_id | category | supplier | round | qty | expected | predicted | status | audit |
|---|---|---|---:|---:|---|---|---|---|
| T00001 | laptops | Coastline Caterers | 4 | 60 | `REJECT:ABOVE_WALKAWAY:` | `REJECT:ABOVE_WALKAWAY:` | PASS | pass |
| T00002 | led-lighting | Falcon Security Services | 2 | 310 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00003 | monitors | Jupiter Devices | 1 | 50 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00004 | headsets | Ivory Events Catering | 1 | 150 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00005 | headsets | Monsoon Foods | 2 | 60 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00006 | mobile-phones | Orbit Electronics | 4 | 25 | `REJECT:BLACKLISTED_SUPPLIER:` | `REJECT:BLACKLISTED_SUPPLIER:` | PASS | pass |
| T00007 | headsets | Cobalt Compute | 2 | 20 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00008 | monitors | Northstar Facilities | 1 | 150 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00009 | monitors | Ivory Events Catering | 3 | 100 | `REJECT:ABOVE_WALKAWAY:` | `REJECT:ABOVE_WALKAWAY:` | PASS | pass |
| T00010 | cleaning | Monsoon Foods | 1 | 300 | `COUNTER:COUNTER_OFFER:85000` | `COUNTER:COUNTER_OFFER:85000` | PASS | pass |
| T00011 | cleaning | Saffron Kitchens | 1 | 60 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00012 | catering | Vertex Mobile | 2 | 100 | `COUNTER:COUNTER_OFFER:270` | `COUNTER:COUNTER_OFFER:270` | PASS | pass |
| T00013 | catering | Northstar Facilities | 2 | 25 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00014 | headsets | Ivory Events Catering | 2 | 20 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00015 | training | GreenLeaf Facility Care | 2 | 60 | `REJECT:BLACKLISTED_SUPPLIER:` | `REJECT:BLACKLISTED_SUPPLIER:` | PASS | pass |
| T00016 | led-lighting | Kestrel Learning | 3 | 40 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00017 | office-chairs | Monsoon Foods | 1 | 300 | `COUNTER:COUNTER_OFFER:9000` | `COUNTER:COUNTER_OFFER:9000` | PASS | pass |
| T00018 | laptops | Deccan Logistics | 1 | 50 | `COUNTER:COUNTER_OFFER:62000` | `COUNTER:COUNTER_OFFER:62000` | PASS | pass |
| T00019 | laptops | Saffron Kitchens | 4 | 60 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00020 | crm-licenses | Ivory Events Catering | 3 | 5 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00021 | monitors | Tidewater Systems | 3 | 10 | `REJECT:ABOVE_WALKAWAY:` | `REJECT:ABOVE_WALKAWAY:` | PASS | pass |
| T00022 | office-chairs | Redwood Couriers | 3 | 5 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00023 | design-software | Ivory Events Catering | 2 | 150 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00024 | crm-licenses | Arvind Office Supplies | 3 | 100 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00025 | monitors | Jupiter Devices | 3 | 20 | `REJECT:ABOVE_WALKAWAY:` | `REJECT:ABOVE_WALKAWAY:` | PASS | pass |
| T00026 | monitors | Quartz Software | 2 | 40 | `COUNTER:COUNTER_OFFER:15250` | `COUNTER:COUNTER_OFFER:15250` | PASS | pass |
| T00027 | design-software | Nimbus Hosting | 4 | 10 | `REJECT:ABOVE_WALKAWAY:` | `REJECT:ABOVE_WALKAWAY:` | PASS | pass |
| T00028 | catering | Garnet Print & Paper | 3 | 150 | `ESCALATE:PROMPT_INJECTION:` | `ESCALATE:PROMPT_INJECTION:` | PASS | pass |
| T00029 | catering | Horizon Cloud | 3 | 10 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00030 | catering | Helix CRM | 1 | 3880 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00031 | crm-licenses | Jade Express | 2 | 150 | `COUNTER:COUNTER_OFFER:18000` | `COUNTER:COUNTER_OFFER:18000` | PASS | pass |
| T00032 | led-lighting | Xenon Displays | 3 | 250 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00033 | laptops | Monsoon Foods | 2 | 50 | `COUNTER:COUNTER_OFFER:62889` | `COUNTER:COUNTER_OFFER:62889` | PASS | pass |
| T00034 | training | Fjord Design Tools | 2 | 25 | `COUNTER:COUNTER_OFFER:6750` | `COUNTER:COUNTER_OFFER:6750` | PASS | pass |
| T00035 | training | Zephyr SaaS | 1 | 80 | `ACCEPT:ACCEPTABLE_PRICE:` | `ACCEPT:ACCEPTABLE_PRICE:` | PASS | pass |
| T00036 | monitors | Kestrel Learning | 1 | 60 | `COUNTER:COUNTER_OFFER:14000` | `COUNTER:COUNTER_OFFER:14000` | PASS | pass |
| T00037 | training | Arvind Office Supplies | 2 | 60 | `COUNTER:COUNTER_OFFER:6750` | `COUNTER:COUNTER_OFFER:6750` | PASS | pass |
| T00038 | mobile-phones | Northstar Facilities | 4 | 60 | `ESCALATE:BANNED_TERM:` | `ESCALATE:BANNED_TERM:` | PASS | pass |
| T00039 | cleaning | Zephyr SaaS | 4 | 200 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |
| T00040 | led-lighting | Ember Telecom | 3 | 320 | `ESCALATE:OVER_APPROVAL_LIMIT:` | `ESCALATE:OVER_APPROVAL_LIMIT:` | PASS | pass |

## Mismatch investigation

No mismatches. Every sample label matched exactly and passed the independent audit.
## Error categories

- None.
