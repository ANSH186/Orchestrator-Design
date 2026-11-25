# Quality Review — The Procurement Desk

This review was performed after the final implementation and verified runs. It
records actual checks, not intentions.

## Architecture

- Clear separation: ingestion/KB, policy, supplier, security, pricing, decision,
  audit, orchestration, output.
- LangGraph owns coordination; Decision Agent owns precedence.
- All important boundaries use Pydantic models, including `extra="forbid"`.
- The orchestrator does not contain agent implementation logic.
- Early terminal routing is documented and the Decision Agent enforces precedence
  independently; an early-exit bug discovered during the first full run was fixed
  and the full dataset re-verified with 0 recoveries.

## Error handling

- Known resolution failures raise typed exceptions.
- Graph nodes catch/report errors; the decide/audit/recovery/fallback path still
  produces a valid label for every supplied thread.
- Batch runner records per-thread errors and uses a safe `ESCALATE:MISSING_INFO:`
  fallback only as a last resort. The verified run had 0 fallbacks.
- No silent row drops; assembly checks every input ID and fills a recorded fallback
  if a checkpoint is missing/corrupt.
- Resume refuses changed input/KB hashes, trusts only completed `ok/recovered`
  checkpoints, and retries corrupt/failed rows.

## Security

- Supplier text treated as untrusted data.
- Injection scan covers the whole thread; banned terms cover only the latest
  supplier message.
- Ordinary business phrases (AI-powered, ERP system, system integration team,
  assistant manager) were explicitly tested and do not trigger injection.
- Allowed contract clauses (mutual renewal, ≤30% advance, net terms, warranties,
  delivery dates, no exclusivity) were tested and do not trigger banned-term flags.
- No API keys in source; `.env`/`.venv` ignored.
- LLM prompts delimit untrusted text and prohibit following it; output schema and
  grounding validation prevent fabricated facts.

## API/provider reliability

- Optional provider is behind an abstraction.
- Timeout, bounded retries, 429/Retry-After/5xx handling, and concurrency semaphore.
- Structured output is JSON-schema-guided, Pydantic-validated, then grounded in the
  source sentence/amount text.
- Provider failure falls back to deterministic extraction or explicit missing data.
- No live provider verification due to missing key; mock tests cover parsing,
  retries, grounding and graph/audit integration.

## Performance

- Full 2,000-thread deterministic run: ~31 seconds on 8 workers, no extraction cache
  (`final-run-6`).
- Extraction cache and per-thread checkpoints avoid repeated work on resume.
- Full internal diagnostics are ~33 MB, separate from the 66 KB submission.
- No external services are needed for the deterministic path.

## Reproducibility

- `.env.example`, `requirements.txt`, exact `requirements-lock.txt`, `pyproject.toml`.
- Playbook SHA-256 and input hash recorded in run metadata.
- Extractor/policy/graph versions recorded.
- All commands are documented in README and `docs/SETUP_AND_EXECUTION.md`.
- Supplied ZIP/CSVs/playbook are retained; outputs are in separate directories.

## Dependency versions

Verified: Python 3.13.7, pandas 3.0.5, pydantic 2.13.5, pydantic-settings 2.15.0,
python-dotenv 1.2.3, langgraph 1.2.16, pytest 8.4.2.

## Tests

`python -m pytest -q` → **348 passed**.

Coverage includes:
- playbook completeness and exact KB values;
- CSV validation and controlled mappings;
- all amendment boundaries and LED ordering;
- supplier status/cap/currency isolation;
- every pricing transformation and Decimal edges;
- security false positives/negatives and scope;
- Thread Analyst extraction over every observed offer grammar;
- all decision precedence combinations and boundaries;
- audit error injection;
- LangGraph early exits, recovery, fallback;
- submission schema and ID validation;
- the 40-thread sample evaluation.

A line-coverage percentage was not measured with a coverage plugin; the test count
and breadth are reported instead of an unverified percentage.

## Output correctness

- `output/submission.csv` is exactly `thread_id,label`, 2,000 rows in input order.
- Validator passed every check after the final no-cache run.
- Decision counts sum to 2,000.
- Sample labels: 40/40 exact.
- Every full-run outcome is `ok`; audit passed for all 2,000.
- No hardcoded sample answers or thread-ID special cases.

## Residual risks

See `docs/KNOWN_LIMITATIONS.md`. The main ones are the absent DOCX, the five
subscription "for this order" threads (implemented as missing information), the
subscription approval-period interpretation, and no live LLM verification.
