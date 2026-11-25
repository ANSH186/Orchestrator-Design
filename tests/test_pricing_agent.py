from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.models import (
    BillingPeriod,
    Message,
    MessageRole,
    OfferBasis,
    OfferFacts,
    ThreadAnalysis,
)
from tests.conftest import make_thread


def build_analysis(offer: OfferFacts, message: str = "test offer") -> ThreadAnalysis:
    return ThreadAnalysis(
        thread_id="T99999",
        supplier="Test Supplier",
        category="laptops",
        messages=[
            Message(
                index=0,
                role=MessageRole.SUPPLIER,
                supplier_name="Test Supplier",
                is_latest=True,
                text=message,
            )
        ],
        latest_supplier_message=message,
        offer=offer,
        missing_information=offer.missing_reason is not None,
        missing_reason=offer.missing_reason,
        evidence=[message],
    )


def normalize(kb, thread, offer):
    policy = PolicyAgent(kb).resolve(thread)
    supplier = SupplierAgent(kb).resolve(thread)
    analysis = build_analysis(offer)
    return PricingAgent().normalize(thread, analysis, policy, supplier)


def test_plain_inr_offer(kb):
    thread = make_thread(category="laptops")
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("62000"),
            amount_basis=OfferBasis.PER_UNIT,
        ),
    )
    assert result.normalized_price == Decimal("62000")
    assert result.approval_amount == Decimal("620000")


def test_gst_removal_uses_category_rate(kb):
    thread = make_thread(category="headsets", quantity=150)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("4049"),
            gst_inclusive=True,
        ),
    )
    assert result.normalized_price == Decimal("4049") / Decimal("1.18")
    assert result.gst_rate == Decimal("0.18")
    assert any("gst" in step.step for step in result.trace)

    paper_thread = make_thread(category="printer-paper", quantity=10)
    paper = normalize(
        kb,
        paper_thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("2240"),
            gst_inclusive=True,
        ),
    )
    assert paper.normalized_price == Decimal("2240") / Decimal("1.12")


def test_standard_usd_and_supplier_eur_override(kb):
    usd_thread = make_thread(category="laptops", supplier="Coastline Caterers")
    usd = normalize(
        kb,
        usd_thread,
        OfferFacts(
            has_usable_price=True,
            currency="USD",
            quoted_amount=Decimal("821.60"),
        ),
    )
    assert usd.normalized_price == Decimal("821.60") * Decimal("84.5")
    assert usd.exchange_rate_source == "standard_rate:USD"

    eur_thread = make_thread(category="training", supplier="Kestrel Learning")
    eur = normalize(
        kb,
        eur_thread,
        OfferFacts(
            has_usable_price=True,
            currency="EUR",
            quoted_amount=Decimal("79.75"),
        ),
    )
    assert eur.normalized_price == Decimal("79.75") * Decimal("90.5")
    assert eur.exchange_rate_source == "supplier_contract_rate:EUR"


def test_total_quote(kb):
    thread = make_thread(category="laptops", quantity=60)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("4407800"),
            amount_basis=OfferBasis.TOTAL,
            total_quantity=60,
        ),
    )
    assert result.normalized_price == Decimal("4407800") / Decimal("60")


def test_dozen_pack_per_n_and_ream(kb):
    dozen_thread = make_thread(category="monitors", quantity=20)
    dozen = normalize(
        kb,
        dozen_thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("183019"),
            amount_basis=OfferBasis.PER_DOZEN,
        ),
    )
    assert dozen.normalized_price == Decimal("183019") / Decimal("12")

    pack_thread = make_thread(category="led-lighting", quantity=50)
    pack = normalize(
        kb,
        pack_thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("9913"),
            amount_basis=OfferBasis.PER_PACK,
            pack_size=4,
        ),
    )
    assert pack.normalized_price == Decimal("9913") / Decimal("4")

    per_n_thread = make_thread(category="led-lighting", quantity=200)
    per_n = normalize(
        kb,
        per_n_thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("192980"),
            amount_basis=OfferBasis.PER_N,
            per_n=100,
        ),
    )
    assert per_n.normalized_price == Decimal("192980") / Decimal("100")

    ream_thread = make_thread(category="printer-paper", quantity=12)
    ream = normalize(
        kb,
        ream_thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("257"),
            amount_basis=OfferBasis.PER_SUB_UNIT,
            sub_unit_name="ream",
        ),
    )
    assert ream.normalized_price == Decimal("257") * Decimal("10")


def test_list_discount_and_month_to_year(kb):
    thread = make_thread(category="crm-licenses", quantity=50, supplier="Coastline Caterers")
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("50000"),
            billing_period=BillingPeriod.MONTH,
            list_discount_percent=Decimal("10"),
        ),
    )
    assert result.normalized_price == Decimal("50000") * Decimal("0.9") * Decimal("12")


def test_previous_quote_discount_uses_supplier_quote(kb):
    thread = make_thread(category="monitors", quantity=10)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("18540"),
            previous_quote_amount=Decimal("18540"),
            previous_quote_currency="INR",
            previous_quote_discount_percent=Decimal("3"),
            previous_quote_source_index=0,
        ),
    )
    assert result.normalized_price == Decimal("18540") * Decimal("0.97")


def test_tier_selection_is_supplied_by_extractor(kb):
    thread = make_thread(category="mobile-phones", quantity=25)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("26904"),
            tier_threshold=20,
            tier_branch="larger",
        ),
    )
    assert result.normalized_price == Decimal("26904")


def test_volume_discount_threshold_applied_or_not(kb):
    high_qty = make_thread(category="office-chairs", quantity=300)
    applied = normalize(
        kb,
        high_qty,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("10000"),
            volume_discount_percent=Decimal("10"),
            volume_threshold=50,
        ),
    )
    assert applied.normalized_price == Decimal("9000")

    low_qty = make_thread(category="office-chairs", quantity=5)
    not_applied = normalize(
        kb,
        low_qty,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("10000"),
            volume_discount_percent=Decimal("10"),
            volume_threshold=50,
        ),
    )
    assert not_applied.normalized_price == Decimal("10000")


def test_free_units(kb):
    thread = make_thread(category="headsets", quantity=20)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("3711"),
            free_units=1,
            paid_units=12,
        ),
    )
    assert result.normalized_price == Decimal("3711") * Decimal("12") / Decimal("13")


def test_correction_replacement_amount_is_used(kb):
    thread = make_thread(category="headsets", quantity=20, supplier="Ivory Events Catering")
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("3870"),
            is_correction=True,
            correction_replaced_amount=Decimal("3483"),
        ),
    )
    assert result.normalized_price == Decimal("3870")


def test_range_high_is_supplied_as_amount(kb):
    thread = make_thread(category="led-lighting", quantity=310)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("1638"),
            is_range=True,
            range_used_high=True,
        ),
    )
    assert result.normalized_price == Decimal("1638")


def test_year_to_month(kb):
    thread = make_thread(category="cleaning", quantity=20)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("1200000"),
            billing_period=BillingPeriod.YEAR,
        ),
    )
    assert result.normalized_price == Decimal("1200000") / Decimal("12")


def test_subscription_missing_period_is_missing(kb):
    thread = make_thread(category="design-software", quantity=100, round_number=4)
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("4200"),
            billing_period=None,
        ),
    )
    assert result.missing_information is True
    assert result.missing_reason == "subscription_period_missing"
    assert result.normalized_price is None


def test_unsupported_currency_and_no_price_are_missing(kb):
    thread = make_thread(category="headsets")
    unsupported = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=False,
            unsupported_currency=True,
            unsupported_currency_code="JPY",
            missing_reason="unsupported_currency",
        ),
    )
    assert unsupported.missing_reason == "unsupported_currency"

    no_price = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=False,
            missing_reason="no_usable_price",
        ),
    )
    assert no_price.missing_reason == "no_usable_price"


def test_probation_does_not_change_normalized_price(kb):
    thread = make_thread(category="crm-licenses", quantity=150, round_number=2, supplier="Jade Express")
    result = normalize(
        kb,
        thread,
        OfferFacts(
            has_usable_price=True,
            currency="INR",
            quoted_amount=Decimal("22277"),
            billing_period=BillingPeriod.YEAR,
        ),
    )
    assert result.normalized_price == Decimal("22277")
