# Known Limitations and Recorded Ambiguities — The Procurement Desk

This file is intentionally explicit. It records what was not available, what was
interpreted, and what remains out of scope.

## 1. Study manual DOCX missing

The task references
`Procurement_Desk_Manual_Multi_Agent_Orchestrator.docx`, but it is not present in
the workspace, the supplied ZIP, or searched parent directories. The implementation
therefore follows the stated precedence: competition output contract → actual
playbook → sample answers → engineering judgement. This is not silently ignored.

## 2. Optional LLM not live-verified

No API key is configured. The full 2,000-thread run uses the deterministic
extractor (`llm_mode=none`). The LLM provider abstraction, structured schema,
untrusted-data delimiters, grounding validation, retries and mock tests are
implemented, but **no live provider call has been verified** in this environment.
Do not claim a live-LLM accuracy figure.

## 3. Subscription offers without a billing period

Five supplied threads quote a subscription category "per seat/server/guard for
this order" with no month/year:

- T10823, T11323 (design-software)
- T11552 (cloud-servers)
- T11753 (crm-licenses)
- T11819 (security-guards)

The playbook explicitly says a subscription price with no period is missing
information. These are implemented as `ESCALATE:MISSING_INFO:`. Treating them as
monthly or yearly would invent a period, which the task forbids. This decision is
isolated in the Thread Analyst/Pricing Agent and can be changed without touching
other logic if competition guidance says otherwise.

## 4. Approval-limit period for subscriptions

Implemented as normalized price × quantity, where the normalized price is already
in the category's normalized period:

- month for cleaning and security-guards;
- year for cloud servers, CRM, design software;
- one-time for the rest.

This matches the calibration of category limits to target prices. The playbook's
phrase "one billing period for subscriptions" is interpreted this way rather than
re-annualizing monthly-normalized categories. The rule is centralized in
`pricing/concessions.py`.

## 5. P-03 illustrative contract rate

Precedent P-03 uses $760 × ₹82/USD = ₹62,320 to demonstrate supplier contract-rate
precedence. ₹82/USD is not present in any supplier record and is not a global rate.
It is not added to the FX table. Only the four documented supplier overrides are
used.

## 6. Deterministic extraction scope

The deterministic Thread Analyst handles every offer grammar observed in the
supplied corpus, plus constructed tests for numeric k/lakh, English word amounts,
ranges, tiers, volume thresholds, free units, list/previous discounts, corrections,
totals, packs, reams, dozens, per-N units, GST, FX and periods. A future dataset
with substantially different free-form wording may need the optional LLM path or
new deterministic rules. The LLM path is an aid, not a guarantee.

## 7. Unknown categories/suppliers

All supplied rows resolve against the controlled mappings. For safety, unknown
identities produce a recorded resolution error and a conservative
`ESCALATE:MISSING_INFO:` fallback; the system never invents a status, policy or
supplier override. This path is not exercised by the supplied data.

## 8. Security classifier coverage

Prompt-injection detection matched all 160 injection threads in the supplied data
with no false positives on ordinary AI/ERP/assistant-manager language. The rules
cover the observed nine phrase families plus Hindi. A genuinely novel multilingual
or obfuscated injection could evade a deterministic rule set; the optional LLM can
serve as a second opinion only if explicitly configured and is still subject to
grounding/audit checks. Security text is never followed.

## 9. Counterfactual rule conflicts

The supplied data has no overlapping missing-information + blacklist, blacklist +
injection, or injection + banned-term threads. The official precedence is
implemented and tested with synthetic combinations. Any future playbook version
that changes the precedence must update Decision and Audit together.

## 10. Hard wall-clock timeout per thread

LLM calls have configurable timeouts and bounded retries. The deterministic graph
is CPU-fast and has no hard per-thread wall-clock kill; a pathological hang would
be handled at the process/batch level rather than by forcibly terminating a Python
thread. No supplied thread exhibited this behavior.

## 11. Concurrency and external provider limits

The batch runner bounds workers and the provider has a semaphore, timeout and
429/5xx retry handling. There is no token-bucket requests-per-minute limiter.
Lower `PROCUREMENT_LLM_MAX_CONCURRENCY` if a provider enforces strict RPM limits.

## 12. Internal diagnostics size

`output/internal_decisions.jsonl` intentionally retains full traces and evidence;
the verified run is roughly 33 MB. That is separate from the tiny submission CSV
and is not part of the competition output.

## 13. Environment note

The tests were run with a Python 3.13.7 virtual environment inheriting the
preinstalled scientific stack. `pip check` reports unrelated global packages
(easyocr/ninja/opencv) missing from the base interpreter; these are not project
dependencies. The project's own imports and 348 tests pass.

## 14. No genuine holdout

All 40 official labels were inspected during development; the full 2,000
unlabelled messages were also inspected for grammar coverage. The 40/40 result is
a genuine prediction-before-comparison evaluation, but it is **not a blind
holdout** and must not be presented as an unbiased hidden-set estimate. No
untouched official labels exist for the 2,000 threads. See
`reports/holdout_evaluation.md`.

## 15. External dataset support

The architecture (models, Decimal pricing, concessions, audit pattern, batch
runner, output layer) is reusable, but the knowledge-base loader and decision/
security layers are Acme-specific. New category names, document counts, amendment
fields, precedence, or contract rules require configuration/code adaptation. The
system is **not** drop-in arbitrary procurement support. See
`reports/generalization_assessment.md`.

## 16. Security residual risk

NFKC, zero-width removal, HTML handling, and broad multilingual ignore+action
patterns are implemented and tested. Homoglyph substitution (e.g. Cyrillic letters
that resemble Latin) and unconfigured languages can still evade deterministic
rules. The optional LLM can provide a second opinion only when configured and is
subject to grounding/audit checks. See `reports/qa_test_results.md`.

## 17. Post-QA behavioral scope

The QA audit fixed multi-price selection, LLM grounding, audit arithmetic
independence, previous-quote double conversion, progress-write resilience, resume
label validation and zero-counter validation. The supplied-data labels remained
identical after those fixes. These fixes improve unseen-input behavior, but they
do not turn the synthetic-benchmark 40/40 into proof of hidden 100% accuracy.

## 18. No fabricated success

All reported results in this project come from commands that were actually run:
- 40/40 sample labels matched;
- 2,000/2,000 full threads produced `ok` outcomes after the terminal-route fix;
- the final submission validator passed every check;
- the test suite passed.

No sample answers are hardcoded, and no thread ID is special-cased.
