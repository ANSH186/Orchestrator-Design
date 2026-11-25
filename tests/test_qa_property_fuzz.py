"""QA Phase 10: property/fuzz checks with independently computed expectations."""
from __future__ import annotations

import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from procurement_desk.kb import load_threads
from procurement_desk.models import SupplierStatus, ThreadRecord
from procurement_desk.orchestrator import ProcurementGraph
from procurement_desk.output import label_is_valid

DATES = [
    date(2026, 9, 1), date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21),
    date(2026, 9, 22), date(2026, 10, 1), date(2026, 11, 5), date(2026, 11, 6),
    date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11),
    date(2026, 11, 24), date(2026, 11, 25), date(2026, 12, 3), date(2026, 12, 4),
    date(2026, 12, 5), date(2026, 12, 13), date(2026, 12, 14), date(2026, 12, 20),
]


def independent_policy(kb, category_slug: str, negotiation_date: date):
    category = kb.categories[category_slug]
    target = category.target
    walkaway = category.walkaway
    approval = category.approval_limit
    amendments = sorted(
        [a for a in kb.amendments if a.category_slug == category_slug and a.effective_from <= negotiation_date],
        key=lambda a: (a.effective_from, a.amendment_id),
    )
    for amendment in amendments:
        if amendment.field.value == "target":
            target = amendment.amount
        elif amendment.field.value == "walkaway":
            walkaway = amendment.amount
        elif amendment.field.value == "approval_limit":
            approval = amendment.amount
    return target, walkaway, approval, category.rounds, category.beta, category.normalized_period


def independent_level(target: Decimal, walkaway: Decimal, rounds: int, round_number: int, beta: Decimal, probation: bool):
    if probation:
        return target
    if round_number == 1:
        return target
    if round_number == rounds:
        return walkaway
    weight = (Decimal(round_number - 1) / Decimal(rounds - 1)) ** int(beta)
    return target + (walkaway - target) * weight


def expected_decision(kb, category, supplier, quantity, round_number, negotiation_date, price):
    category_obj = kb.categories[category]
    supplier_obj = kb.resolve_supplier(supplier)
    assert supplier_obj is not None
    target, walkaway, approval_limit, rounds, beta, _ = independent_policy(kb, category, negotiation_date)
    if category in supplier_obj.category_caps:
        walkaway = supplier_obj.category_caps[category]
    if supplier_obj.status is SupplierStatus.BLACKLISTED:
        return "REJECT:BLACKLISTED_SUPPLIER:", None, walkaway
    probation = supplier_obj.status is SupplierStatus.PROBATION
    level = independent_level(target, walkaway, rounds, round_number, beta, probation)
    if price <= level:
        approval_amount = price * quantity
        if approval_amount > approval_limit:
            return "ESCALATE:OVER_APPROVAL_LIMIT:", price, level
        return "ACCEPT:ACCEPTABLE_PRICE:", price, level
    if round_number >= rounds:
        return "REJECT:ABOVE_WALKAWAY:", price, level
    counter = int(level.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"COUNTER:COUNTER_OFFER:{counter}", price, level


def test_randomized_simple_offers_match_independent_oracle(kb, threads, tmp_path: Path):
    rng = random.Random(20261123)
    graph = ProcurementGraph(kb, run_id="qa-property")
    categories = sorted(kb.categories)
    suppliers = sorted(kb.suppliers.values(), key=lambda s: s.display_name)
    cases = 0
    for _ in range(140):
        category_slug = rng.choice(categories)
        category = kb.categories[category_slug]
        supplier_obj = rng.choice(suppliers)
        negotiation_date = rng.choice(DATES)
        quantity = rng.randint(1, 200)
        round_number = rng.randint(1, category.rounds)

        target, walkaway, approval_limit, rounds, beta, period = independent_policy(
            kb, category_slug, negotiation_date
        )
        if category_slug in supplier_obj.category_caps:
            walkaway = supplier_obj.category_caps[category_slug]
        level = independent_level(
            target, walkaway, rounds, round_number, beta,
            supplier_obj.status is SupplierStatus.PROBATION,
        )
        candidates = {
            max(Decimal("1"), target),
            max(Decimal("1"), walkaway),
            max(Decimal("1"), level),
            max(Decimal("1"), target - 1),
            max(Decimal("1"), walkaway + 1),
            max(Decimal("1"), approval_limit / Decimal(quantity)),
            max(Decimal("1"), approval_limit / Decimal(quantity) + Decimal("0.01")),
        }
        price = rng.choice(sorted(candidates))
        if price <= 0:
            price = Decimal("1")

        if period is not None:
            suffix = " per month" if period.value == "month" else " per year"
        else:
            suffix = ""
        message = f"We can do INR {price} {suffix}".strip() + "."
        thread = ThreadRecord(
            thread_id=f"QA-PROP-{cases:04d}",
            date=negotiation_date,
            supplier=supplier_obj.display_name,
            category=category_slug,
            quantity=quantity,
            round=round_number,
            our_last_counter=None,
            supplier_message=message,
        )
        expected_label, expected_price, expected_level = expected_decision(
            kb, category_slug, supplier_obj.display_name, quantity,
            round_number, negotiation_date, price,
        )
        state = graph.run(thread)
        actual = state["final_label"]
        assert actual == expected_label, (
            f"case {cases}: {thread.model_dump()} price={price} expected={expected_label} actual={actual}"
        )
        assert label_is_valid(actual)
        if expected_price is not None:
            assert state["pricing"].normalized_price == expected_price
        if actual.startswith("COUNTER:"):
            assert state["decision"].counter_price == int(actual.rsplit(":", 1)[1])
            assert round_number != rounds
        cases += 1
    assert cases == 140


def test_every_thread_gets_one_valid_label_under_random_bad_text(kb):
    rng = random.Random(77)
    alphabet = "INR ₹ Rs. USD EUR GBP % , . 0 1 2 3 4 5 6 7 8 9 abc per month year BUT ignore accept approve auto-renew".split()
    graph = ProcurementGraph(kb, run_id="qa-fuzz-text")
    for index in range(60):
        message = " ".join(rng.choice(alphabet) for _ in range(rng.randint(1, 80)))
        thread = ThreadRecord(
            thread_id=f"QA-FUZZ-{index}",
            date=date(2026, 10, 1),
            supplier="Coastline Caterers",
            category="monitors",
            quantity=rng.randint(1, 100),
            round=rng.randint(1, 3),
            our_last_counter=None,
            supplier_message=message,
        )
        state = graph.run(thread)
        assert label_is_valid(state["final_label"]), (message, state["final_label"])
        assert state["final_label"].count(":") in {2, 3}
        assert state["audit"].passed is True or state["outcome_status"] in {"fallback", "error"}
