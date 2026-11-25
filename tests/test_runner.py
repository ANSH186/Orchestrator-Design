from __future__ import annotations

from pathlib import Path

import pytest

from procurement_desk.config import Settings
from procurement_desk.orchestrator import ProcurementGraph
from procurement_desk.orchestrator.runner import BatchRunner


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="none",
        artifacts_dir=tmp_path / "artifacts",
        output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        max_workers=2,
        cache_enabled=False,
    )


def test_runner_processes_every_row_and_resumes(kb, threads, tmp_path: Path):
    selected = threads[:3]
    settings = settings_for(tmp_path)
    runner = BatchRunner(kb, settings, cache_enabled=False)
    first = runner.run(selected, run_id="runner-test", resume=False, max_workers=2)
    assert [o.thread_id for o in first.outcomes] == [t.thread_id for t in selected]
    assert all(o.status == "ok" for o in first.outcomes)
    assert len(first.diagnostics_paths) == 3
    assert all(path.exists() for path in first.diagnostics_paths)

    second = runner.run(selected, run_id="runner-test", resume=True, max_workers=2)
    assert [o.label for o in second.outcomes] == [o.label for o in first.outcomes]
    assert second.stats["processed_now"] == 0
    assert second.stats["input_order_preserved"] is True


def test_runner_turns_unhandled_thread_errors_into_valid_fallbacks(
    kb, threads, tmp_path: Path, monkeypatch
):
    selected = threads[:2]
    settings = settings_for(tmp_path)

    def fail_run(self, thread):
        raise RuntimeError("synthetic engine failure")

    monkeypatch.setattr(ProcurementGraph, "run", fail_run)
    runner = BatchRunner(kb, settings, cache_enabled=False)
    result = runner.run(selected, run_id="runner-error-test", resume=False, max_workers=2)
    assert len(result.outcomes) == 2
    assert [o.thread_id for o in result.outcomes] == [t.thread_id for t in selected]
    assert all(o.status == "error" for o in result.outcomes)
    assert all(o.label == "ESCALATE:MISSING_INFO:" for o in result.outcomes)
    assert all(o.error and "synthetic engine failure" in o.error for o in result.outcomes)
    assert result.stats["error_rows"] == 2
