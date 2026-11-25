from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.agents.thread_analyst import ThreadAnalyst, find_price_mentions
from procurement_desk.models import (
    BillingPeriod,
    ExtractionMethod,
    OfferBasis,
    ThreadAnalysis,
)
from tests.conftest import make_thread


def analyze(kb, thread):
    return ThreadAnalyst(kb).analyze(thread)


def price(kb, thread, analysis: ThreadAnalysis):
    policy = PolicyAgent(kb).resolve(thread)
    supplier = SupplierAgent(kb).resolve(thread)
    return PricingAgent().normalize(thread, analysis, policy, supplier)


def test_find_price_mentions_indian_notation_and_words():
    mentions = find_price_mentions("We can do ₹58.3k per laptop.")
    assert mentions[0].amount == Decimal("58300")
    mentions = find_price_mentions("The price is one lakh seven thousand three hundred rupees per server.")
    assert mentions[0].amount == Decimal("107300")
    mentions = find_price_mentions("Between Rs. 1,506 and ₹1,638 per fixture.")
    assert [m.amount for m in mentions] == [Decimal("1506"), Decimal("1638")]
    assert find_price_mentions("This all 25 guards phrase is not a currency") == []


def test_plain_and_gst_extraction(kb):
    thread = make_thread(
        category="headsets",
        quantity=150,
        thread_date=date(2026, 10, 7),
        message="For the 150 headsets you requested, our final price is INR 4,049 per headset including GST.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.quoted_amount == Decimal("4049")
    assert analysis.offer.gst_inclusive is True
    assert analysis.offer.amount_basis is OfferBasis.PER_UNIT
    assert analysis.missing_information is False


def test_total_quote_extraction(kb):
    thread = make_thread(
        category="laptops",
        quantity=60,
        thread_date=date(2026, 11, 17),
        message="We are pleased to quote ₹44,07,800 in total for all 60 laptops.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.amount_basis is OfferBasis.TOTAL
    assert analysis.offer.total_quantity == 60
    assert price(kb, thread, analysis).normalized_price == Decimal("4407800") / Decimal("60")


def test_range_uses_high_end(kb):
    thread = make_thread(
        category="led-lighting",
        quantity=310,
        thread_date=date(2026, 9, 19),
        message=(
            "For the 310 fixtures you requested, the best we can offer is between "
            "Rs. 1,506 and ₹1,638 per fixture depending on final specs."
        ),
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.quoted_amount == Decimal("1638")
    assert analysis.offer.is_range is True
    assert analysis.offer.range_used_high is True


def test_tier_branch_selection(kb):
    message = (
        "For the 20 phones you requested, we are pleased to quote INR 28,518 per phone "
        "for orders of up to 20 phones, and ₹26,904 per phone for larger orders."
    )
    small = make_thread(category="mobile-phones", quantity=20, message=message)
    large = make_thread(category="mobile-phones", quantity=25, message=message)
    small_analysis = analyze(kb, small)
    large_analysis = analyze(kb, large)
    assert small_analysis.offer.quoted_amount == Decimal("28518")
    assert small_analysis.offer.tier_branch == "up_to"
    assert large_analysis.offer.quoted_amount == Decimal("26904")
    assert large_analysis.offer.tier_branch == "larger"


def test_volume_threshold_whether_applied(kb):
    message = (
        "For the 50 chairs you requested, our final price is INR 10,582 per chair, "
        "with a further 10% off for orders of 50 chairs or more."
    )
    at_threshold = make_thread(category="office-chairs", quantity=50, message=message)
    below_threshold = make_thread(category="office-chairs", quantity=49, message=message)
    a1 = analyze(kb, at_threshold)
    a2 = analyze(kb, below_threshold)
    assert a1.offer.volume_discount_percent == Decimal("10")
    assert a1.offer.volume_threshold == 50
    assert price(kb, at_threshold, a1).normalized_price == Decimal("10582") * Decimal("0.9")
    assert price(kb, below_threshold, a2).normalized_price == Decimal("10582")


def test_list_discount(kb):
    thread = make_thread(
        category="catering",
        quantity=25,
        thread_date=date(2026, 11, 24),
        message=(
            "For the 25 meals you requested, we are pleased to quote a 10% discount "
            "on our list price of INR 410 per meal."
        ),
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.list_discount_percent == Decimal("10")
    assert price(kb, thread, analysis).normalized_price == Decimal("369")


def test_previous_quote_uses_supplier_not_acme(kb):
    thread = make_thread(
        category="office-chairs",
        quantity=300,
        supplier="Monsoon Foods",
        thread_date=date(2026, 9, 21),
        message=(
            "[Earlier message — Monsoon Foods, 2026-09-19]\n"
            "Our quote is ₹11,460 per chair.\n\n"
            "[Earlier message — Acme Procurement]\n"
            "We can offer ₹9,000 per chair.\n\n"
            "[Latest message — Monsoon Foods, 2026-09-21]\n"
            "For the 300 chairs you requested, our final price is a further 10% off our previous quote."
        ),
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.previous_quote_amount == Decimal("11460")
    assert analysis.offer.previous_quote_source_index == 0
    result = price(kb, thread, analysis)
    assert result.normalized_price == Decimal("11460") * Decimal("0.9")


def test_correction_replaces_previous_quote(kb):
    thread = make_thread(
        category="headsets",
        quantity=20,
        supplier="Ivory Events Catering",
        thread_date=date(2026, 12, 5),
        message=(
            "[Earlier message — Ivory Events Catering, 2026-12-02]\n"
            "We can do INR 3,483 per headset.\n\n"
            "[Earlier message — Acme Procurement]\n"
            "We can offer ₹3,500 per headset.\n\n"
            "[Latest message — Ivory Events Catering, 2026-12-05]\n"
            "CORRECTION — the price in my previous email should read INR 3,870 per headset, not ₹3,483."
        ),
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.is_correction is True
    assert analysis.offer.quoted_amount == Decimal("3870")
    assert analysis.offer.correction_replaced_amount == Decimal("3483")
    assert price(kb, thread, analysis).normalized_price == Decimal("3870")


def test_free_units_factor(kb):
    thread = make_thread(
        category="courier",
        quantity=30,
        message="We can do ₹170 per shipment, plus 1 free shipment for every 5 you pay for.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.free_units == 1
    assert analysis.offer.paid_units == 5
    assert price(kb, thread, analysis).normalized_price == Decimal("170") * Decimal("5") / Decimal("6")


def test_dozen_pack_per_n_and_ream_extraction(kb):
    dozen = make_thread(
        category="monitors",
        quantity=20,
        message="We can do Rs. 1,83,019 per dozen monitors.",
    )
    pack = make_thread(
        category="led-lighting",
        quantity=50,
        message="We can do ₹9,913 per pack of 4 fixtures.",
    )
    per_n = make_thread(
        category="led-lighting",
        quantity=200,
        message="We can do ₹1,92,980 per 100 fixtures.",
    )
    ream = make_thread(
        category="printer-paper",
        quantity=12,
        message="We can do ₹257 per ream.",
    )
    assert analyze(kb, dozen).offer.amount_basis is OfferBasis.PER_DOZEN
    assert analyze(kb, pack).offer.amount_basis is OfferBasis.PER_PACK
    assert analyze(kb, pack).offer.pack_size == 4
    assert analyze(kb, per_n).offer.amount_basis is OfferBasis.PER_N
    assert analyze(kb, per_n).offer.per_n == 100
    assert analyze(kb, ream).offer.amount_basis is OfferBasis.PER_SUB_UNIT
    assert price(kb, ream, analyze(kb, ream)).normalized_price == Decimal("2570")


def test_month_to_year_and_year_to_month(kb):
    crm = make_thread(
        category="crm-licenses",
        quantity=10,
        message="We can do ₹1,600 per seat per month.",
    )
    cleaning = make_thread(
        category="cleaning",
        quantity=10,
        message="We can do ₹12,00,000 per site per year.",
    )
    crm_analysis = analyze(kb, crm)
    cleaning_analysis = analyze(kb, cleaning)
    assert crm_analysis.offer.billing_period is BillingPeriod.MONTH
    assert price(kb, crm, crm_analysis).normalized_price == Decimal("19200")
    assert cleaning_analysis.offer.billing_period is BillingPeriod.YEAR
    assert price(kb, cleaning, cleaning_analysis).normalized_price == Decimal("100000")


def test_unsupported_currency_is_missing(kb):
    thread = make_thread(
        category="headsets",
        quantity=10,
        message="We can offer AED 462 per headset.",
    )
    analysis = analyze(kb, thread)
    assert analysis.missing_information is True
    assert analysis.missing_reason == "unsupported_currency"
    assert analysis.offer.unsupported_currency is True


def test_no_price_is_missing(kb):
    thread = make_thread(
        category="headsets",
        quantity=10,
        message="We can definitely give you a competitive price on the headsets. Let's get on a call.",
    )
    analysis = analyze(kb, thread)
    assert analysis.missing_information is True
    assert analysis.missing_reason == "no_usable_price"


def test_subscription_period_missing(kb):
    thread = make_thread(
        category="design-software",
        quantity=100,
        round_number=4,
        message="We can offer ₹4,200 per seat for this order.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.has_usable_price is True
    assert analysis.offer.billing_period is None
    assert analysis.missing_information is True
    assert analysis.missing_reason == "subscription_period_missing"


def test_k_notation_offer(kb):
    thread = make_thread(
        category="laptops",
        quantity=200,
        message="For the 200 laptops you requested, our final price is ₹58.3k per laptop.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.quoted_amount == Decimal("58300")
    assert price(kb, thread, analysis).normalized_price == Decimal("58300")


def test_word_amount_offer(kb):
    thread = make_thread(
        category="headsets",
        quantity=5,
        message="For the 5 headsets you requested, our final price is three thousand seven hundred rupees per headset.",
    )
    analysis = analyze(kb, thread)
    assert analysis.offer.quoted_amount == Decimal("3700")


def test_extraction_method_is_deterministic_without_provider(kb):
    thread = make_thread(category="laptops", message="We can do INR 62,000 per laptop.")
    analysis = analyze(kb, thread)
    assert analysis.extraction_method is ExtractionMethod.DETERMINISTIC
