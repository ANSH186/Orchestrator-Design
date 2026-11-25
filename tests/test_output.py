from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from procurement_desk.models import (
    Action,
    ExecutionMetadata,
    ReasonCode,
    ThreadOutcome,
    ThreadRecord,
)
from procurement_desk.output import (
    label_is_valid,
    validate_submission,
    write_submission,
)
from tests.conftest import make_thread


def outcome(thread: ThreadRecord, label: str) -> ThreadOutcome:
    action, reason, counter_text = label.split(":")
    counter = int(counter_text) if counter_text else None
    return ThreadOutcome(
        thread_id=thread.thread_id,
        label=label,
        action=Action(action),
        reason=ReasonCode(reason),
        counter_price=counter,
        status="ok",
        audit_passed=True,
        execution=ExecutionMetadata(
            run_id="test", started_at=datetime.now(timezone.utc)
        ),
    )


def test_label_validator_rules():
    assert label_is_valid("ACCEPT:ACCEPTABLE_PRICE:")
    assert label_is_valid("COUNTER:COUNTER_OFFER:62889")
    assert label_is_valid("REJECT:ABOVE_WALKAWAY:")
    assert not label_is_valid("COUNTER:COUNTER_OFFER:0")
    assert not label_is_valid("COUNTER:COUNTER_OFFER:1.5")
    assert not label_is_valid("ACCEPT:ACCEPTABLE_PRICE")
    assert not label_is_valid("ACCEPT:ACCEPTABLE_PRICE:1")
    assert not label_is_valid("ESCALATE:NOT_A_REASON:")


def test_write_and_validate_submission(tmp_path: Path):
    threads = [
        make_thread(thread_id="T1", category="laptops"),
        make_thread(thread_id="T2", category="monitors"),
        make_thread(thread_id="T3", category="training"),
    ]
    outcomes = [
        outcome(threads[0], "ACCEPT:ACCEPTABLE_PRICE:"),
        outcome(threads[1], "REJECT:ABOVE_WALKAWAY:"),
        outcome(threads[2], "COUNTER:COUNTER_OFFER:6750"),
    ]
    path = tmp_path / "submission.csv"
    write_submission(path, threads, outcomes)
    assert path.read_text(encoding="utf-8").splitlines() == [
        "thread_id,label",
        "T1,ACCEPT:ACCEPTABLE_PRICE:",
        "T2,REJECT:ABOVE_WALKAWAY:",
        "T3,COUNTER:COUNTER_OFFER:6750",
    ]
    result = validate_submission(path, threads)
    assert result.passed, result.errors
    assert result.row_count == 3


def _write_raw(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "submission.csv"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "content",
    [
        "thread_id,label\nT1,ACCEPT:ACCEPTABLE_PRICE:\n",
        "thread_id,label\nT1,ACCEPT:ACCEPTABLE_PRICE:\nT1,REJECT:ABOVE_WALKAWAY:\nT3,COUNTER:COUNTER_OFFER:6750\n",
        "thread_id,label\nT2,REJECT:ABOVE_WALKAWAY:\nT1,ACCEPT:ACCEPTABLE_PRICE:\nT3,COUNTER:COUNTER_OFFER:6750\n",
        "thread_id,label\nT1,ACCEPT:ACCEPTABLE_PRICE:\nT2,REJECT:ABOVE_WALKAWAY:\nT3,COUNTER:COUNTER_OFFER:1.5\n",
        "thread_id,label\nT1,ACCEPT:ACCEPTABLE_PRICE\nT2,REJECT:ABOVE_WALKAWAY:\nT3,COUNTER:COUNTER_OFFER:6750\n",
        "id,label\nT1,ACCEPT:ACCEPTABLE_PRICE:\nT2,REJECT:ABOVE_WALKAWAY:\nT3,COUNTER:COUNTER_OFFER:6750\n",
        "thread_id,label\nT1,\nT2,REJECT:ABOVE_WALKAWAY:\nT3,COUNTER:COUNTER_OFFER:6750\n",
        "thread_id,label,extra\nT1,ACCEPT:ACCEPTABLE_PRICE:,x\nT2,REJECT:ABOVE_WALKAWAY:,x\nT3,COUNTER:COUNTER_OFFER:6750,x\n",
    ],
)
def test_invalid_submissions_are_rejected(tmp_path: Path, content: str):
    threads = [
        make_thread(thread_id="T1", category="laptops"),
        make_thread(thread_id="T2", category="monitors"),
        make_thread(thread_id="T3", category="training"),
    ]
    path = _write_raw(tmp_path, content)
    result = validate_submission(path, threads)
    assert result.passed is False
    assert result.errors


def test_missing_submission_is_rejected(tmp_path: Path):
    threads = [make_thread(thread_id="T1", category="laptops")]
    result = validate_submission(tmp_path / "missing.csv", threads)
    assert result.passed is False


def test_duplicate_outcomes_are_rejected(tmp_path: Path):
    thread = make_thread(thread_id="T1", category="laptops")
    outcomes = [
        outcome(thread, "ACCEPT:ACCEPTABLE_PRICE:"),
        outcome(thread, "ACCEPT:ACCEPTABLE_PRICE:"),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        write_submission(tmp_path / "submission.csv", [thread], outcomes)
