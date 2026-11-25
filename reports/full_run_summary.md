# Full Competition Run Summary

- Generated: 2026-11-25T04:57:27.221090+00:00
- Run id: `reproduce-final`
- Run directory: `artifacts\runs\reproduce-final`
- Playbook hash: `14b36328afb1c704b45258903081e0f2890236642a6bcfe4c921546ac23cfcce`
- LLM mode: `none`
- Threads: 2000
- Submission: `output\submission.csv`
- Validation passed: **True**

## Decision counts

| ACTION:REASON | Count |
|---|---:|
| ACCEPT:ACCEPTABLE_PRICE | 359 |
| COUNTER:COUNTER_OFFER | 627 |
| ESCALATE:BANNED_TERM | 144 |
| ESCALATE:MISSING_INFO | 92 |
| ESCALATE:OVER_APPROVAL_LIMIT | 286 |
| ESCALATE:PROMPT_INJECTION | 160 |
| REJECT:ABOVE_WALKAWAY | 227 |
| REJECT:BLACKLISTED_SUPPLIER | 105 |

## Outcome status

| Status | Count |
|---|---:|
| ok | 2000 |

## Validation checks

- PASS: header is exactly thread_id,label
- PASS: CSV has exactly two columns in the right order
- PASS: row count is 2000
- PASS: thread IDs are unique
- PASS: thread ID set matches the input exactly
- PASS: submission order matches input order
- PASS: all labels match the official ACTION:REASON: contract
- PASS: all COUNTER labels carry a whole-number INR price
- PASS: all non-COUNTER labels end with the empty final field
- PASS: CSV reopens successfully with uniform two-column rows

## Error rows

- None.
