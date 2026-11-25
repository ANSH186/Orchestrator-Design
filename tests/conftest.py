from __future__ import annotations

from pathlib import Path

import pytest

from procurement_desk.kb import build_knowledge_base, load_threads
from procurement_desk.models import ThreadRecord
from datetime import date
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return ROOT / "data"


@pytest.fixture(scope="session")
def playbook_dir(data_dir: Path) -> Path:
    return data_dir / "playbook" / "playbook"


@pytest.fixture(scope="session")
def kb(playbook_dir: Path):
    return build_knowledge_base(playbook_dir)


@pytest.fixture(scope="session")
def threads(data_dir: Path):
    return load_threads(data_dir / "threads.csv")


@pytest.fixture(scope="session")
def sample_threads(data_dir: Path):
    return load_threads(data_dir / "sample_threads.csv")


@pytest.fixture(scope="session")
def sample_answers(data_dir: Path) -> dict[str, str]:
    import pandas as pd

    frame = pd.read_csv(data_dir / "sample_answers.csv", dtype=str, keep_default_na=False)
    return dict(zip(frame["thread_id"], frame["label"]))


def make_thread(
    *,
    thread_id: str = "T99999",
    supplier: str = "Coastline Caterers",
    category: str = "laptops",
    quantity: int = 10,
    round_number: int = 1,
    thread_date: date = date(2026, 10, 1),
    message: str = "We can do INR 62,000 per laptop.",
    last_counter: Decimal | None = None,
) -> ThreadRecord:
    return ThreadRecord(
        thread_id=thread_id,
        date=thread_date,
        supplier=supplier,
        category=category,
        quantity=quantity,
        round=round_number,
        our_last_counter=last_counter,
        supplier_message=message,
    )
