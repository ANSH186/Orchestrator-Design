from __future__ import annotations

from pathlib import Path

import pytest

from procurement_desk.exceptions import IngestionError
from procurement_desk.kb import (
    load_label_file,
    load_threads,
    thread_coverage_summary,
    validate_threads_against_kb,
)


def test_full_thread_file_shape(threads):
    assert len(threads) == 2000
    assert len({t.thread_id for t in threads}) == 2000
    assert threads[0].thread_id == "T10001"
    assert threads[-1].thread_id == "T12000"
    assert all(t.quantity > 0 for t in threads)
    assert all(t.round >= 1 for t in threads)


def test_sample_files_shape(data_dir: Path, sample_threads, sample_answers):
    assert len(sample_threads) == 40
    assert len(sample_answers) == 40
    assert [t.thread_id for t in sample_threads] == list(sample_answers)
    assert set(sample_answers.values())


def test_all_threads_resolve_against_kb(threads, kb):
    errors = validate_threads_against_kb(threads, kb)
    assert errors == []


def test_coverage_summary(threads, kb):
    summary = thread_coverage_summary(threads, kb)
    assert summary["rows"] == 2000
    assert summary["unique_ids"] == 2000
    assert summary["categories_used"] == 15
    assert summary["suppliers_used"] == 40
    assert summary["missing_last_counter"] == 577
    assert summary["date_min"] == "2026-09-01"
    assert summary["date_max"] == "2026-12-20"
    assert summary["kb_categories"] == 15
    assert summary["kb_suppliers"] == 40


def test_label_file_round_trip(data_dir: Path, sample_answers):
    labels = load_label_file(data_dir / "sample_answers.csv")
    assert labels == sample_answers
    assert labels["T00012"] == "COUNTER:COUNTER_OFFER:270"
    assert labels["T00028"] == "ESCALATE:PROMPT_INJECTION:"


def test_invalid_path_raises(tmp_path: Path):
    with pytest.raises(IngestionError):
        load_threads(tmp_path / "missing.csv")


def test_duplicate_ids_rejected(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "thread_id,date,supplier,category,quantity,round,our_last_counter,supplier_message\n"
        "T1,2026-10-01,Coastline Caterers,laptops,1,1,,We can do INR 1 per laptop.\n"
        "T1,2026-10-01,Coastline Caterers,laptops,1,1,,We can do INR 2 per laptop.\n",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError, match="duplicate"):
        load_threads(path)
