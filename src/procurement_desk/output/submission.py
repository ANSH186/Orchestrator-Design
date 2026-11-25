"""Submission generation and strict competition-format validation."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from procurement_desk.models import ThreadOutcome, ThreadRecord

HEADER = ["thread_id", "label"]
LABEL_RE = re.compile(
    r"^(?:"
    r"ACCEPT:ACCEPTABLE_PRICE:|"
    r"REJECT:BLACKLISTED_SUPPLIER:|"
    r"REJECT:ABOVE_WALKAWAY:|"
    r"ESCALATE:MISSING_INFO:|"
    r"ESCALATE:PROMPT_INJECTION:|"
    r"ESCALATE:BANNED_TERM:|"
    r"ESCALATE:OVER_APPROVAL_LIMIT:|"
    r"COUNTER:COUNTER_OFFER:[0-9]+"
    r")$"
)


def label_is_valid(label: str) -> bool:
    if not LABEL_RE.fullmatch(label):
        return False
    if label.startswith("COUNTER:"):
        counter = int(label.rsplit(":", 1)[1])
        return counter > 0
    return True


def write_submission(
    path: Path,
    threads: list[ThreadRecord],
    outcomes: list[ThreadOutcome],
) -> None:
    """Write exactly two columns in input order.  Internal data stays separate."""

    by_id: dict[str, ThreadOutcome] = {}
    for outcome in outcomes:
        if outcome.thread_id in by_id:
            raise ValueError(f"duplicate outcome for {outcome.thread_id}")
        by_id[outcome.thread_id] = outcome

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        for thread in threads:
            outcome = by_id.get(thread.thread_id)
            if outcome is None:
                raise ValueError(f"missing outcome for thread {thread.thread_id}")
            writer.writerow([thread.thread_id, outcome.label])
    tmp_path.replace(path)


def write_internal_decisions_jsonl(path: Path, diagnostics_paths: list[Path]) -> None:
    """Concatenate per-thread internal evidence bundles for offline analysis."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for diagnostics_path in diagnostics_paths:
            if diagnostics_path.exists():
                handle.write(diagnostics_path.read_text(encoding="utf-8").strip())
                handle.write("\n")
    tmp_path.replace(path)


@dataclass
class SubmissionValidationResult:
    path: Path
    passed: bool
    checks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    row_count: int = 0

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "passed": self.passed,
            "row_count": self.row_count,
            "checks": self.checks,
            "errors": self.errors,
        }


def validate_submission(
    path: Path,
    threads: list[ThreadRecord],
    *,
    expected_rows: int | None = None,
) -> SubmissionValidationResult:
    result = SubmissionValidationResult(path=path, passed=False)

    def fail(message: str) -> None:
        result.errors.append(message)

    def ok(message: str) -> None:
        result.checks.append(message)

    if not path.exists():
        fail(f"submission file does not exist: {path}")
        return result

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if not raw_lines:
        fail("submission file is empty")
        return result
    if raw_lines[0] != "thread_id,label":
        fail(f"header must be exactly 'thread_id,label', got {raw_lines[0]!r}")
    else:
        ok("header is exactly thread_id,label")

    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:
        fail(f"pandas could not reopen submission: {exc}")
        return result
    if list(frame.columns) != HEADER:
        fail(f"columns must be exactly {HEADER}, got {list(frame.columns)}")
        result.passed = False
        return result
    else:
        ok("CSV has exactly two columns in the right order")

    result.row_count = len(frame)
    expected_count = expected_rows if expected_rows is not None else len(threads)
    if len(frame) != expected_count:
        fail(f"row count must be {expected_count}, got {len(frame)}")
    else:
        ok(f"row count is {expected_count}")

    if frame.isna().any().any():
        fail("submission contains null values")
    if (frame["thread_id"].str.strip() == "").any():
        fail("submission contains empty thread_id values")
    if (frame["label"].str.strip() == "").any():
        fail("submission contains empty labels")

    expected_ids = [thread.thread_id for thread in threads]
    actual_ids = frame["thread_id"].tolist()
    if len(set(actual_ids)) != len(actual_ids):
        fail("submission contains duplicate thread IDs")
    else:
        ok("thread IDs are unique")
    if set(actual_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(actual_ids))
        extra = sorted(set(actual_ids) - set(expected_ids))
        if missing:
            fail(f"missing thread IDs: {missing[:10]}")
        if extra:
            fail(f"extra thread IDs: {extra[:10]}")
    else:
        ok("thread ID set matches the input exactly")
    if actual_ids != expected_ids:
        fail("submission order does not match input order")
    else:
        ok("submission order matches input order")

    invalid_labels = [
        (row.thread_id, row.label)
        for row in frame.itertuples(index=False)
        if not label_is_valid(str(row.label))
    ]
    if invalid_labels:
        fail(f"invalid labels ({len(invalid_labels)}): {invalid_labels[:10]}")
    else:
        ok("all labels match the official ACTION:REASON: contract")

    counter_bad = []
    trailing_bad = []
    for row in frame.itertuples(index=False):
        label = str(row.label)
        if label.startswith("COUNTER:"):
            parts = label.split(":")
            if len(parts) != 3 or not parts[2].isdigit():
                counter_bad.append((row.thread_id, label))
        elif not label.endswith(":"):
            trailing_bad.append((row.thread_id, label))
    if counter_bad:
        fail(f"COUNTER labels without whole-number price: {counter_bad[:10]}")
    else:
        ok("all COUNTER labels carry a whole-number INR price")
    if trailing_bad:
        fail(f"non-COUNTER labels without trailing colon: {trailing_bad[:10]}")
    else:
        ok("all non-COUNTER labels end with the empty final field")

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reopened = list(csv.reader(handle))
        if len(reopened) != expected_count + 1:
            fail(f"csv reread produced {len(reopened)} lines, expected {expected_count + 1}")
        elif any(len(row) != 2 for row in reopened):
            fail("csv reread found a row with a different column count")
        else:
            ok("CSV reopens successfully with uniform two-column rows")
    except Exception as exc:
        fail(f"CSV could not be reopened: {exc}")

    result.passed = not result.errors
    return result
