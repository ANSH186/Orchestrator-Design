"""QA Phase 13: input corruption and malformed-data handling."""
from __future__ import annotations

from pathlib import Path

import pytest

from procurement_desk.exceptions import IngestionError
from procurement_desk.kb import load_threads

HEADER = "thread_id,date,supplier,category,quantity,round,our_last_counter,supplier_message\n"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "threads.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_missing_column_is_rejected(tmp_path: Path):
    path = tmp_path / "threads.csv"
    path.write_text("thread_id,date\nT1,2026-10-01\n", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_corrupt_row_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,2026-10-01\n")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_empty_message_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,2026-10-01,Coastline Caterers,monitors,10,1,, \n")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_invalid_date_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,not-a-date,Coastline Caterers,monitors,10,1,,We can offer INR 10.\n")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_non_positive_quantity_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,2026-10-01,Coastline Caterers,monitors,0,1,,We can offer INR 10.\n")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_non_positive_round_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,2026-10-01,Coastline Caterers,monitors,10,0,,We can offer INR 10.\n")
    with pytest.raises(IngestionError):
        load_threads(path)


def test_duplicate_thread_id_is_rejected(tmp_path: Path):
    path = write(
        tmp_path,
        "T1,2026-10-01,Coastline Caterers,monitors,10,1,,We can offer INR 10.\n"
        "T1,2026-10-02,Coastline Caterers,monitors,10,1,,We can offer INR 20.\n",
    )
    with pytest.raises(IngestionError):
        load_threads(path)


def test_bad_counter_is_rejected(tmp_path: Path):
    path = write(tmp_path, "T1,2026-10-01,Coastline Caterers,monitors,10,1,abc,We can offer INR 10.\n")
    with pytest.raises(IngestionError):
        load_threads(path)
