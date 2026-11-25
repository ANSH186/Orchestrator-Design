"""Independent price arithmetic used only by the Audit Agent.

This module intentionally does not call PricingAgent or its normalization
functions.  It recomputes the comparable price from OfferFacts, policy and
supplier overrides using a separate implementation of the same playbook rules.
"""

from __future__ import annotations

from decimal import Decimal

from procurement_desk.models import (
    BillingPeriod,
    OfferBasis,
    OfferFacts,
    ResolvedPolicy,
    SupplierAnalysis,
)

_STANDARD_RATES = {
    "INR": Decimal("1"),
    "USD": Decimal("84.5"),
    "EUR": Decimal("91"),
    "GBP": Decimal("106"),
}


def independent_price_with_quantity(
    offer: OfferFacts,
    policy: ResolvedPolicy,
    supplier: SupplierAnalysis,
    *,
    quantity: int,
) -> tuple[Decimal, Decimal] | None:
    """Full independent recomputation including volume/free/approval."""

    if not offer.has_usable_price or offer.unsupported_currency:
        return None
    previous = offer.previous_quote_discount_percent is not None
    if previous:
        amount = offer.previous_quote_amount
        currency = offer.previous_quote_currency
        gst_inclusive = offer.previous_quote_gst_inclusive
        period = offer.previous_quote_billing_period
        basis = offer.previous_quote_basis
        if amount is None or currency is None:
            return None
        amount = _apply_basis(
            amount,
            basis,
            offer.previous_quote_total_quantity,
            offer.previous_quote_pack_size,
            offer.previous_quote_per_n,
            policy,
        )
        if amount is None:
            return None
        if offer.previous_quote_discount_percent is not None:
            amount = amount * (
                Decimal("1") - offer.previous_quote_discount_percent / Decimal("100")
            )
    else:
        amount = offer.quoted_amount
        currency = offer.currency
        gst_inclusive = offer.gst_inclusive
        period = offer.billing_period
        basis = offer.amount_basis
        if amount is None or currency is None:
            return None
        if offer.list_discount_percent is not None:
            amount = amount * (
                Decimal("1") - offer.list_discount_percent / Decimal("100")
            )

    if offer.volume_discount_percent is not None:
        if offer.volume_threshold is None:
            return None
        if quantity >= offer.volume_threshold:
            amount = amount * (
                Decimal("1") - offer.volume_discount_percent / Decimal("100")
            )

    if offer.free_units is not None:
        if offer.paid_units is None or offer.paid_units <= 0:
            return None
        free_factor = Decimal(offer.paid_units) / Decimal(
            offer.paid_units + offer.free_units
        )
        amount = amount * free_factor

    if not previous:
        amount = _apply_basis(
            amount,
            basis,
            offer.total_quantity,
            offer.pack_size,
            offer.per_n,
            policy,
        )
        if amount is None:
            return None

    rate = _resolve_rate(currency, supplier)
    if rate is None:
        return None
    amount = amount * rate
    if gst_inclusive:
        amount = amount / (Decimal("1") + policy.gst_rate)
    amount = _normalize_period(amount, period, policy.normalized_period)
    if amount is None or amount < 0:
        return None
    return amount, amount * Decimal(quantity)


def _apply_basis(
    amount: Decimal,
    basis: OfferBasis,
    total_quantity: int | None,
    pack_size: int | None,
    per_n: int | None,
    policy: ResolvedPolicy,
) -> Decimal | None:
    if basis in {OfferBasis.PER_UNIT, OfferBasis.PREVIOUS_QUOTE}:
        return amount
    if basis is OfferBasis.TOTAL:
        if total_quantity is None or total_quantity <= 0:
            return None
        return amount / Decimal(total_quantity)
    if basis is OfferBasis.PER_DOZEN:
        return amount / Decimal("12")
    if basis is OfferBasis.PER_PACK:
        size = pack_size or policy.pack_size
        if size is None or size <= 0:
            return None
        return amount / Decimal(size)
    if basis is OfferBasis.PER_N:
        if per_n is None or per_n <= 0:
            return None
        return amount / Decimal(per_n)
    if basis is OfferBasis.PER_SUB_UNIT:
        factor = policy.sub_unit_factor
        if factor is None or factor <= 0:
            return None
        return amount * factor
    return None


def _resolve_rate(currency: str, supplier: SupplierAnalysis) -> Decimal | None:
    code = currency.upper()
    if code in supplier.currency_rates:
        rate = supplier.currency_rates[code]
        return rate if rate > 0 else None
    return _STANDARD_RATES.get(code)


def _normalize_period(
    amount: Decimal,
    offered: BillingPeriod | None,
    normalized: BillingPeriod | None,
) -> Decimal | None:
    if normalized is None:
        return amount
    if offered is None:
        return None
    if offered == normalized:
        return amount
    if offered is BillingPeriod.MONTH and normalized is BillingPeriod.YEAR:
        return amount * Decimal("12")
    if offered is BillingPeriod.YEAR and normalized is BillingPeriod.MONTH:
        return amount / Decimal("12")
    return None
