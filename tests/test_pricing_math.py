from __future__ import annotations

from decimal import Decimal

import pytest

from procurement_desk.exceptions import PricingError
from procurement_desk.models import BillingPeriod
from procurement_desk.pricing.concessions import (
    acceptable_price,
    approval_amount,
    exceeds_approval_limit,
)
from procurement_desk.pricing.currency import (
    normalize_billing_period,
    resolve_exchange_rate,
)
from procurement_desk.pricing.money import (
    fraction,
    parse_percentage,
    round_half_up_int,
    to_decimal,
    words_to_int,
)


def test_words_to_int():
    cases = {
        "two hundred sixty-six": 266,
        "two thousand six hundred": 2600,
        "seventeen thousand seven hundred": 17700,
        "one lakh seven thousand three hundred": 107300,
        "one lakh thirty-six thousand seven hundred": 136700,
        "ninety-six thousand two hundred": 96200,
        "eighty-seven thousand five hundred": 87500,
    }
    for text, expected in cases.items():
        assert words_to_int(text) == expected


def test_simple_decimals_and_percentages():
    assert to_decimal("1,50,790") == Decimal("150790")
    assert parse_percentage("12.5%") == Decimal("12.5")
    assert fraction("12.5%") == Decimal("0.125")


def test_round_half_up():
    assert round_half_up_int(Decimal("15250.5")) == 15251
    assert round_half_up_int(Decimal("15250.49")) == 15250
    assert round_half_up_int(Decimal("0.5")) == 1
    assert round_half_up_int(Decimal("62888.888888")) == 62889


def test_concession_round_anchors():
    assert acceptable_price(
        target=Decimal("1800"),
        walkaway=Decimal("2200"),
        rounds=3,
        round_number=1,
        beta=Decimal("1"),
    ) == Decimal("1800")
    assert acceptable_price(
        target=Decimal("1800"),
        walkaway=Decimal("2200"),
        rounds=3,
        round_number=3,
        beta=Decimal("1"),
    ) == Decimal("2200")


def test_concession_examples_from_samples():
    laptops = acceptable_price(
        target=Decimal("62000"),
        walkaway=Decimal("70000"),
        rounds=4,
        round_number=2,
        beta=Decimal("2"),
    )
    assert laptops == Decimal("62000") + Decimal("8000") / Decimal("9")
    assert round_half_up_int(laptops) == 62889

    monitors = acceptable_price(
        target=Decimal("14000"),
        walkaway=Decimal("16500"),
        rounds=3,
        round_number=2,
        beta=Decimal("1"),
    )
    assert monitors == Decimal("15250")

    training = acceptable_price(
        target=Decimal("6000"),
        walkaway=Decimal("7500"),
        rounds=3,
        round_number=2,
        beta=Decimal("1"),
    )
    assert training == Decimal("6750")


def test_probation_uses_target_every_round():
    for round_number in (1, 2, 3, 4):
        assert acceptable_price(
            target=Decimal("18000"),
            walkaway=Decimal("22000"),
            rounds=4,
            round_number=round_number,
            beta=Decimal("2"),
            probation=True,
        ) == Decimal("18000")


def test_invalid_round_and_beta():
    with pytest.raises(PricingError):
        acceptable_price(
            target=Decimal("1"),
            walkaway=Decimal("2"),
            rounds=3,
            round_number=4,
            beta=Decimal("1"),
        )
    with pytest.raises(PricingError):
        acceptable_price(
            target=Decimal("1"),
            walkaway=Decimal("2"),
            rounds=3,
            round_number=2,
            beta=Decimal("1.5"),
        )


def test_approval_limit_is_inclusive():
    assert approval_amount(Decimal("100"), 10) == Decimal("1000")
    assert exceeds_approval_limit(Decimal("1000"), Decimal("1000")) is False
    assert exceeds_approval_limit(Decimal("1000.01"), Decimal("1000")) is True


def test_exchange_rate_standard_and_supplier_override():
    assert resolve_exchange_rate("USD") == (Decimal("84.5"), "standard_rate:USD")
    assert resolve_exchange_rate("EUR") == (Decimal("91"), "standard_rate:EUR")
    assert resolve_exchange_rate("GBP") == (Decimal("106"), "standard_rate:GBP")
    assert resolve_exchange_rate("INR") == (Decimal("1"), "base_currency")
    assert resolve_exchange_rate("GBP", {"GBP": Decimal("104.5")}) == (
        Decimal("104.5"),
        "supplier_contract_rate:GBP",
    )
    assert resolve_exchange_rate("USD", {"GBP": Decimal("104.5")}) == (
        Decimal("84.5"),
        "standard_rate:USD",
    )
    assert resolve_exchange_rate("JPY") == (None, "unsupported_currency")


def test_billing_period_conversions():
    amount, steps = normalize_billing_period(
        Decimal("1600"), BillingPeriod.MONTH, BillingPeriod.YEAR, required=True
    )
    assert amount == Decimal("19200")
    assert steps == ["monthly → yearly: multiply by 12"]

    amount, steps = normalize_billing_period(
        Decimal("12000"), BillingPeriod.YEAR, BillingPeriod.MONTH, required=True
    )
    assert amount == Decimal("1000")
    assert steps == ["yearly → monthly: divide by 12"]

    amount, steps = normalize_billing_period(
        Decimal("5000"), BillingPeriod.MONTH, BillingPeriod.MONTH, required=True
    )
    assert amount == Decimal("5000")

    with pytest.raises(PricingError, match="missing_billing_period"):
        normalize_billing_period(
            Decimal("5000"), None, BillingPeriod.YEAR, required=True
        )

    amount, _ = normalize_billing_period(
        Decimal("5000"), None, None, required=False
    )
    assert amount == Decimal("5000")
