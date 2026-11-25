# Setup and Execution — The Procurement Desk

All commands below are PowerShell, run from the project root
(`C:\Users\ANSH SINGH\Desktop\data-sprint\orchestrator`).

## 1. Prerequisites

- Python 3.11 or newer (verified with 3.13.7 on Windows).
- The supplied `data/` tree extracted from `the-procurement-desk.zip`:
  - `data/threads.csv`
  - `data/sample_threads.csv`
  - `data/sample_answers.csv`
  - `data/sample_submission.csv`
  - `data/playbook/playbook/` (80 Markdown documents)
- No API key is required for the deterministic path.

## 2. Create the environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks script activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If the editable install is unavailable, use the source path explicitly:

```powershell
$env:PYTHONPATH = "src"
```

The verified dependency versions are in `requirements-lock.txt`. The project
declares compatible lower bounds in `pyproject.toml` and `requirements.txt`.

## 3. Configure (optional)

```powershell
Copy-Item .env.example .env
```

The safe default is:

```dotenv
PROCUREMENT_LLM_PROVIDER=none
```

To use an OpenAI-compatible endpoint:

```dotenv
PROCUREMENT_LLM_PROVIDER=openai_compatible
PROCUREMENT_LLM_API_KEY=your-key
PROCUREMENT_LLM_BASE_URL=https://api.openai.com/v1
PROCUREMENT_LLM_MODEL=gpt-4o-mini
PROCUREMENT_LLM_TIMEOUT_SECONDS=40
PROCUREMENT_LLM_MAX_RETRIES=2
PROCUREMENT_LLM_MAX_CONCURRENCY=4
```

`mock` is available for tests only. Never commit `.env`.

## 4. Validate data and playbook

```powershell
python -m procurement_desk ingest
```

Outputs:
- `reports/playbook_completeness.json`
- `reports/playbook_completeness.md`
- `reports/data_validation.json`

Expected: 15 categories, 40 suppliers, 9 amendments, 8 precedents, 7 policies,
80 documents, 2,000 thread rows, 0 validation errors.

## 5. Run tests

```powershell
python -m pytest -q
```

Expected: all tests pass. Tests include ingestion, every playbook record,
amendment boundaries, supplier override isolation, all pricing transformations,
security false-positive/false-negative cases, decision precedence combinations,
audit error injection, LangGraph early exits/recovery, submission validation, and
the 40-sample evaluation.

## 6. Evaluate the 40 labelled samples

```powershell
python -m procurement_desk evaluate-sample
```

Outputs:
- `reports/sample_evaluation.md`

The comparison is by `thread_id`, not row position.

Expected from the verified run: **40 / 40 correct, 0 mismatches**.

## 7. Inspect one thread

```powershell
python -m procurement_desk show-thread T10001
```

Prints the full internal analysis, policy, supplier, security, pricing trace,
decision, audit checks and final label as JSON.

## 8. Full competition run

```powershell
python -m procurement_desk run --run-id final-20261123 --workers 8
```

Outputs:
- `output/submission.csv`
- `output/internal_decisions.jsonl`
- `output/run_diagnostics.json`
- `artifacts/runs/<run-id>/threads/<thread_id>.json`
- `artifacts/runs/<run-id>/run_metadata.json`
- `reports/full_run_summary.md`

The run uses bounded concurrency, extraction caching, and atomic per-thread
checkpoints. It preserves input order.

### Resume after an interruption

```powershell
python -m procurement_desk run --run-id final-20261123 --workers 8 --resume
```

Resume validates that the input rows and playbook hash are unchanged. It trusts
only complete `ok`/`recovered` checkpoints and retries corrupt or failed rows.

### Force recomputation

```powershell
python -m procurement_desk run --run-id final-20261123 --workers 8 --fresh
```

`--fresh` removes only that run's thread checkpoint files. It never touches
supplied data.

### Smoke run without overwriting the final file

```powershell
python -m procurement_desk run --run-id smoke-1 --limit 20 --output artifacts/smoke_submission.csv
```

## 9. Validate the final CSV

```powershell
python -m procurement_desk validate-submission
```

Expected checks:
- header exactly `thread_id,label`;
- exactly two columns;
- exactly 2,000 rows;
- every input ID once, no extras, no missing, no duplicates;
- input order preserved;
- labels match the official action/reason set;
- COUNTER prices are whole INR integers;
- other labels end with a trailing colon;
- CSV reopens cleanly.

## 10. Trouble-shooting

| Symptom | Resolution |
|---|---|
| `No module named procurement_desk` | Run `python -m pip install -e .` or set `$env:PYTHONPATH="src"`. |
| Console `.exe` blocked by policy | Use `python -m procurement_desk ...` instead. |
| `playbook directory not found` | Ensure the ZIP was extracted to `data/`; playbook is at `data/playbook/playbook/`. |
| Resume refused: input hash differs | Use a new `--run-id` or `--fresh` if appropriate. |
| Provider enabled but no key | Set `PROCUREMENT_LLM_API_KEY` or use `PROCUREMENT_LLM_PROVIDER=none`. |
| Long LLM run hits rate limits | Lower `PROCUREMENT_LLM_MAX_CONCURRENCY`; retries handle 429/5xx. |
| Need a clean rerun | Use a new run ID; do not delete supplied data. |

## 11. Run artifacts and auditability

- `artifacts/runs/<run-id>/run_metadata.json` records input hash, playbook hash,
  versions, LLM mode, decision counts, status counts and failures.
- Per-thread JSON contains the outcome plus full `ThreadDiagnostics`: analysis,
  policy, supplier, security, pricing trace, decision trace, audit checks/errors.
- `output/run_diagnostics.json` records submission validation and run summary.
- `reports/sample_evaluation.md` contains per-thread sample results and mismatch
  investigation (none in the verified run).
