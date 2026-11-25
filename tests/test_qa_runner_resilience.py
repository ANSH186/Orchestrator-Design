"""QA regression tests for batch-runner atomic writes and progress resilience."""
from __future__ import annotations

import json
import os
from pathlib import Path

from procurement_desk.config import Settings
from procurement_desk.orchestrator import runner as runner_module
from procurement_desk.orchestrator.runner import BatchRunner, atomic_write_text


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="none",
        artifacts_dir=tmp_path / "artifacts",
        output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        max_workers=2,
        cache_enabled=False,
    )


def test_atomic_write_retries_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "file.txt"
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(runner_module.os, "replace", flaky_replace)
    atomic_write_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"
    assert calls["n"] == 3


def test_progress_write_failure_does_not_abort_batch(kb, threads, tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    real_write = runner_module.atomic_write_json

    def flaky_write(path: Path, payload: dict):
        if path.name == "progress.json":
            raise OSError("progress disk unavailable")
        return real_write(path, payload)

    monkeypatch.setattr(runner_module, "atomic_write_json", flaky_write)
    runner = BatchRunner(kb, settings, cache_enabled=False)
    result = runner.run(threads[:2], run_id="progress-failure", resume=False, max_workers=2)
    assert len(result.outcomes) == 2
    assert all(outcome.status == "ok" for outcome in result.outcomes)


def test_resume_retries_invalid_label_checkpoint(kb, threads, tmp_path: Path):
    settings = settings_for(tmp_path)
    runner = BatchRunner(kb, settings, cache_enabled=False)
    first = runner.run(threads[:2], run_id="invalid-label", resume=False, max_workers=2)
    checkpoint = first.run_dir / "threads" / f"{threads[0].thread_id}.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["outcome"]["label"] = "ACCEPT:WRONG:"
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    resumed = runner.run(threads[:2], run_id="invalid-label", resume=True, max_workers=2)
    assert resumed.stats["processed_now"] == 1
    repaired = next(o for o in resumed.outcomes if o.thread_id == threads[0].thread_id)
    assert repaired.label != "ACCEPT:WRONG:"
    assert repaired.status == "ok"
