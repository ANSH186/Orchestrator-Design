# Performance and Reliability Report

Measured on the hardened system with Python 3.13.7 on Windows. Raw JSON:
`reports/performance_reliability.json`.

## Results

| Scenario | Result |
|---|---|
| 200 threads, 1 worker | 4.271 s |
| 200 threads, 8 workers | 3.337 s |
| 200-thread labels, sequential vs concurrent | **identical** |
| 100 threads, cache enabled | 1.887 s (first fill) |
| 100 threads, cache disabled | 1.437 s |
| 100-thread labels, cache on/off | **identical** |
| Resume after deleting 1 checkpoint | retried, 100/100 rows present |
| Resume after corrupting 1 checkpoint | retried, 100/100 rows present |
| Resume processed rows | 2 |
| 2,200-thread synthetic batch | 38.459 s, 2,200 unique IDs, 0 errors |
| 205,036-character thread | 2.261 s, valid label, status `ok` |
| Full 2,000 threads, 1 worker | 28.915 s, 0 errors |
| Full 1-worker labels vs final 8-worker submission | **identical, 0 mismatches** |
| Peak traced Python memory, 200 rows | 2.15 MB |

The final no-cache 8-worker run (`final-run-6`) completed 2,000/2,000 `ok` in
30.913 s.

## Reliability incidents found and fixed

### R-1: transient Windows file-lock abort

During an early QA full run, replacing `progress.json` raised:

```text
PermissionError: [WinError 5] ... progress.json.tmp -> progress.json
```

This aborted the entire batch. It was caused by a transient file lock, likely
Windows indexing/antivirus.

Fix:

- `atomic_write_text` retries `os.replace` up to six times with bounded backoff.
- `record_progress` catches remaining `OSError` and never aborts the batch.
- Final metadata/progress writes are guarded.
- Regression tests simulate transient `PermissionError` and permanent progress
  write failure.

### R-2: invalid checkpoint trust

Resume previously trusted any `ok` outcome. It now requires:

- matching thread ID;
- status `ok`/`recovered`;
- valid label grammar.

An invalid label checkpoint is retried; a regression test verifies this.

## Concurrency and determinism

- Batch concurrency is bounded by `max_workers`.
- Threads share only immutable KB/agent configuration; each graph invocation has
  its own state.
- Twenty concurrent graph calls match sequential calls.
- A 200-thread concurrent batch matches a 1-worker batch.
- A full 2,000-thread 1-worker run matches the 8-worker submission labels exactly.

## Cache behavior

The cache stores validated `ThreadAnalysis` results keyed by content, KB hash,
extractor version and LLM mode. First-fill cache timing is slightly slower than
no-cache because it writes every entry; the benefit is on repeated runs, not the
first run. Cache-on and cache-off labels were identical.

## Input corruption

Eight malformed-input tests pass:

- missing columns;
- corrupt row structure;
- empty supplier message;
- invalid date;
- non-positive quantity;
- non-positive round;
- duplicate thread ID;
- invalid `our_last_counter`.

All are rejected at ingestion, not silently converted into decisions.

## Limitations

- There is no hard per-thread wall-clock kill. LLM HTTP calls have timeouts, but a
  hung custom/deterministic path would be handled at process/batch level.
- The 2.15 MB figure is `tracemalloc` Python allocation, not total process RSS.
- The 2,200-thread batch reuses supplied message content with unique IDs; it tests
  scale, not new semantic distributions.
