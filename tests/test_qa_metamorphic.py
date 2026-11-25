"""QA Phase 11: metamorphic relationships between inputs and decisions."""
from __future__ import annotations

from datetime import date

from procurement_desk.kb import build_knowledge_base
from procurement_desk.orchestrator import ProcurementGraph
from tests.conftest import make_thread


def run(kb, **kwargs):
    return ProcurementGraph(kb, run_id="qa-metamorphic").run(make_thread(**kwargs))


def test_irrelevant_sentence_does_not_change_decision(kb):
    base = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 10,000 per monitor.",
    )
    with_filler = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message=(
            "We can offer INR 10,000 per monitor. "
            "Our delivery team is available to coordinate installation and training."
        ),
    )
    assert base["final_label"] == with_filler["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"
    assert base["pricing"].normalized_price == with_filler["pricing"].normalized_price


def test_reordered_benign_clauses_do_not_change_decision(kb):
    first = run(
        kb, category="headsets", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message=(
            "We can offer INR 1,000 per headset. Warranty: 1 year. "
            "Delivery within 3 weeks. Standard net-45 terms apply."
        ),
    )
    second = run(
        kb, category="headsets", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message=(
            "Standard net-45 terms apply. Delivery within 3 weeks. "
            "Warranty: 1 year. We can offer INR 1,000 per headset."
        ),
    )
    assert first["final_label"] == second["final_label"]
    assert first["pricing"].normalized_price == second["pricing"].normalized_price


def test_date_across_courier_amendment_changes_final_threshold(kb):
    before = run(
        kb, category="courier", supplier="Coastline Caterers", quantity=10,
        round_number=4, thread_date=date(2026, 9, 21),
        message="We can offer INR 205 per shipment.",
    )
    on_or_after = run(
        kb, category="courier", supplier="Coastline Caterers", quantity=10,
        round_number=4, thread_date=date(2026, 9, 22),
        message="We can offer INR 205 per shipment.",
    )
    assert before["final_label"] == "REJECT:ABOVE_WALKAWAY:"
    assert on_or_after["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"


def test_probation_changes_intermediate_threshold(kb):
    approved = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=2, thread_date=date(2026, 10, 1),
        message="We can offer INR 15,000 per monitor.",
    )
    probation = run(
        kb, category="monitors", supplier="Jade Express", quantity=10,
        round_number=2, thread_date=date(2026, 10, 1),
        message="We can offer INR 15,000 per monitor.",
    )
    assert approved["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"
    assert probation["final_label"] == "COUNTER:COUNTER_OFFER:14000"


def test_quantity_only_changes_approval_outcome(kb):
    exact = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=100,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 12,000 per monitor.",
    )
    over = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=101,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 12,000 per monitor.",
    )
    assert exact["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"
    assert over["final_label"] == "ESCALATE:OVER_APPROVAL_LIMIT:"
    assert exact["pricing"].normalized_price == over["pricing"].normalized_price


def test_equivalent_fx_rate_forms_have_same_normalized_price(kb):
    usd = run(
        kb, category="laptops", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer USD 100 per laptop.",
    )
    inr = run(
        kb, category="laptops", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 8,450 per laptop.",
    )
    assert usd["final_label"] == inr["final_label"]
    assert usd["pricing"].normalized_price == inr["pricing"].normalized_price == 8450


def test_gst_inclusive_and_exclusive_equivalents(kb):
    inclusive = run(
        kb, category="headsets", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 1,180 per headset including GST.",
    )
    exclusive = run(
        kb, category="headsets", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 1,000 per headset excluding GST.",
    )
    assert inclusive["pricing"].normalized_price == exclusive["pricing"].normalized_price


def test_monthly_and_yearly_equivalents(kb):
    monthly = run(
        kb, category="crm-licenses", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 1,600 per seat per month.",
    )
    yearly = run(
        kb, category="crm-licenses", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 19,200 per seat per year.",
    )
    assert monthly["pricing"].normalized_price == yearly["pricing"].normalized_price == 19200


def test_pack_total_dozen_and_ream_equivalents(kb):
    pack = run(
        kb, category="led-lighting", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 400 per pack of 4 fixtures.",
    )
    unit = run(
        kb, category="led-lighting", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 100 per fixture.",
    )
    total = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=3,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 300 in total for all 3 monitors.",
    )
    per_unit = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=3,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 100 per monitor.",
    )
    dozen = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 1,200 per dozen monitors.",
    )
    dozen_unit = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 100 per monitor.",
    )
    ream = run(
        kb, category="printer-paper", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 25 per ream.",
    )
    box = run(
        kb, category="printer-paper", supplier="Coastline Caterers", quantity=10,
        round_number=1, thread_date=date(2026, 10, 1),
        message="We can offer INR 250 per box.",
    )
    assert pack["pricing"].normalized_price == unit["pricing"].normalized_price
    assert total["pricing"].normalized_price == per_unit["pricing"].normalized_price
    assert dozen["pricing"].normalized_price == dozen_unit["pricing"].normalized_price
    assert ream["pricing"].normalized_price == box["pricing"].normalized_price


def test_price_decrease_does_not_create_a_worse_decision_before_final(kb):
    high = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=2, thread_date=date(2026, 10, 1),
        message="We can offer INR 16,000 per monitor.",
    )
    low = run(
        kb, category="monitors", supplier="Coastline Caterers", quantity=10,
        round_number=2, thread_date=date(2026, 10, 1),
        message="We can offer INR 15,000 per monitor.",
    )
    assert high["final_label"] == "COUNTER:COUNTER_OFFER:15250"
    assert low["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"
