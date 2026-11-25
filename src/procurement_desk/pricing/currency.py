"""Currency conversion and billing-period normalization."""

from __future__ import annotations

from decimal import Decimal

from procurement_desk.exceptions import PricingError
from procurement_desk.models import BillingPeriod
from procurement_desk.pricing.money import STANDARD_FX_TO_INR, SUPPORTED_CURRENCIES

ZERO = Decimal("0")
TWELVE = Decimal("12")


def resolve_exchange_rate(
    currency: str,
    supplier_rates: dict[str, Decimal] | None = None,
) -> tuple[Decimal | None, str]:
    """Resolve INR per currency unit, preferring a supplier contract rate.

    Returns ``(None, 'unsupported_currency')`` for anything outside INR/USD/EUR/GBP.
    """

    code = currency.strip().upper()
    if code == "INR":
        return Decimal("1"), "base_currency"
    if code not in SUPPORTED_CURRENCIES:
        return None, "unsupported_currency"
    if supplier_rates and code in supplier_rates:
        rate = supplier_rates[code]
        if rate <= 0:
            raise PricingError(f"non-positive supplier FX rate for {code}")
        return rate, f"supplier_contract_rate:{code}"
    rate = STANDARD_FX_TO_INR.get(code)
    if rate is None:
        return None, "unsupported_currency"
    return rate, f"standard_rate:{code}"


def normalize_billing_period(
    amount: Decimal,
    offered_period: BillingPeriod | None,
    normalized_period: BillingPeriod | None,
    *,
    required: bool,
) -> tuple[Decimal, list[str]]:
    """Convert a per-unit amount to the category's normalized billing period.

    The playbook only defines monthly ↔ yearly conversion (×/÷ 12).  A missing
    period is missing information for a subscription category, but harmless for
    one-time categories.
    """

    transforms: list[str] = []
    if normalized_period is None:
        if offered_period is not None:
            # A one-time category quoted with a period is unusual; the playbook
            # only gives monthly↔yearly conversion for subscriptions.  Treating
            # it as a period mismatch would invent a rule, so preserve the
            # amount and record the observation.
            transforms.append(
                "category has no normalized billing period; quoted period recorded but not converted"
            )
        return amount, transforms

    if offered_period is None:
        if required:
            raise PricingError("missing_billing_period")
        transforms.append("no billing period offered; normalized period not required")
        return amount, transforms

    if offered_period == normalized_period:
        transforms.append(
            f"billing period already normalized ({normalized_period.value})"
        )
        return amount, transforms

    if offered_period == BillingPeriod.MONTH and normalized_period == BillingPeriod.YEAR:
        result = amount * TWELVE
        transforms.append("monthly → yearly: multiply by 12")
        return result, transforms
    if offered_period == BillingPeriod.YEAR and normalized_period == BillingPeriod.MONTH:
        result = amount / TWELVE
        transforms.append("yearly → monthly: divide by 12")
        return result, transforms

    raise PricingError(
        f"unsupported billing-period conversion {offered_period} → {normalized_period}"
    )
