"""CSV ingestion and validation for competition threads and labels."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from procurement_desk.exceptions import IngestionError
from procurement_desk.models import ThreadRecord
from procurement_desk.pricing.money import to_decimal

REQUIRED_THREAD_COLUMNS = [
    "thread_id",
    "date",
    "supplier",
    "category",
    "quantity",
    "round",
    "our_last_counter",
    "supplier_message",
]


def load_threads(path: Path) -> list[ThreadRecord]:
    """Load and validate a thread CSV without changing input order."""

    if not path.exists():
        raise IngestionError(f"thread CSV not found: {path}")
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises several parser types
        raise IngestionError(f"could not read {path}: {exc}") from exc

    actual_columns = list(frame.columns)
    if actual_columns != REQUIRED_THREAD_COLUMNS:
        raise IngestionError(
            f"{path} columns must be exactly {REQUIRED_THREAD_COLUMNS}, "
            f"found {actual_columns}"
        )
    if frame.empty:
        raise IngestionError(f"{path} contains no data rows")

    seen_ids: set[str] = set()
    threads: list[ThreadRecord] = []
    errors: list[str] = []
    for row_number, row in enumerate(frame.to_dict(orient="records"), start=2):
        thread_id = str(row["thread_id"]).strip()
        if not thread_id:
            errors.append(f"row {row_number}: empty thread_id")
            continue
        if thread_id in seen_ids:
            errors.append(f"row {row_number}: duplicate thread_id {thread_id}")
            continue
        seen_ids.add(thread_id)
        try:
            thread_date = date.fromisoformat(str(row["date"]).strip())
        except ValueError:
            errors.append(f"{thread_id}: invalid date {row['date']!r}")
            continue
        try:
            quantity = int(str(row["quantity"]).strip())
            round_number = int(str(row["round"]).strip())
        except ValueError:
            errors.append(f"{thread_id}: quantity and round must be integers")
            continue
        if quantity <= 0:
            errors.append(f"{thread_id}: quantity must be positive")
            continue
        if round_number <= 0:
            errors.append(f"{thread_id}: round must be positive")
            continue

        counter_raw = str(row["our_last_counter"]).strip()
        counter: Decimal | None
        if counter_raw == "":
            counter = None
        else:
            try:
                counter = to_decimal(counter_raw)
            except ValueError:
                errors.append(f"{thread_id}: invalid our_last_counter {counter_raw!r}")
                continue

        message = str(row["supplier_message"])
        if not message.strip():
            errors.append(f"{thread_id}: empty supplier_message")
            continue
        threads.append(
            ThreadRecord(
                thread_id=thread_id,
                date=thread_date,
                supplier=str(row["supplier"]).strip(),
                category=str(row["category"]).strip(),
                quantity=quantity,
                round=round_number,
                our_last_counter=counter,
                supplier_message=message,
            )
        )

    if errors:
        preview = "\n".join(errors[:20])
        raise IngestionError(
            f"{len(errors)} validation error(s) in {path}:\n{preview}"
        )
    return threads


def load_label_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise IngestionError(f"label CSV not found: {path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns) != ["thread_id", "label"]:
        raise IngestionError(
            f"label CSV must have exactly ['thread_id', 'label'], got {list(frame.columns)}"
        )
    labels: dict[str, str] = {}
    for row in frame.to_dict(orient="records"):
        thread_id = str(row["thread_id"]).strip()
        if thread_id in labels:
            raise IngestionError(f"duplicate thread_id in {path}: {thread_id}")
        labels[thread_id] = str(row["label"]).strip()
    return labels


def validate_threads_against_kb(threads: list[ThreadRecord], kb) -> list[str]:
    """Return controlled-mapping errors for supplied thread rows."""

    errors: list[str] = []
    for thread in threads:
        if kb.resolve_category(thread.category) is None:
            errors.append(f"{thread.thread_id}: unknown category {thread.category!r}")
        if kb.resolve_supplier(thread.supplier) is None:
            errors.append(f"{thread.thread_id}: unknown supplier {thread.supplier!r}")
        category = kb.resolve_category(thread.category)
        if category is not None and thread.round > category.rounds:
            errors.append(
                f"{thread.thread_id}: round {thread.round} exceeds category R "
                f"{category.rounds}"
            )
    return errors


def thread_coverage_summary(threads: list[ThreadRecord], kb) -> dict[str, object]:
    category_counts: dict[str, int] = {}
    supplier_counts: dict[str, int] = {}
    missing_counter = 0
    for thread in threads:
        category_counts[thread.category] = category_counts.get(thread.category, 0) + 1
        supplier_counts[thread.supplier] = supplier_counts.get(thread.supplier, 0) + 1
        if thread.our_last_counter is None:
            missing_counter += 1
    return {
        "rows": len(threads),
        "unique_ids": len({t.thread_id for t in threads}),
        "categories_used": len(category_counts),
        "suppliers_used": len(supplier_counts),
        "missing_last_counter": missing_counter,
        "date_min": min(t.date for t in threads).isoformat(),
        "date_max": max(t.date for t in threads).isoformat(),
        "category_counts": dict(sorted(category_counts.items())),
        "supplier_counts": dict(sorted(supplier_counts.items())),
        "kb_categories": len(kb.categories),
        "kb_suppliers": len(kb.suppliers),
    }
