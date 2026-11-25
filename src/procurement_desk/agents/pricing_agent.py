"""Pricing Agent: deterministic Decimal normalization into the comparable unit."""

from __future__ import annotations

from decimal import Decimal

from procurement_desk.exceptions import PricingError
from procurement_desk.models import (
    BillingPeriod,
    OfferBasis,
    OfferFacts,
    PricingAnalysis,
    PricingStep,
    ResolvedPolicy,
    SupplierAnalysis,
    ThreadAnalysis,
    ThreadRecord,
)
from procurement_desk.pricing.concessions import approval_amount
from procurement_desk.pricing.currency import (
    normalize_billing_period,
    resolve_exchange_rate,
)
from procurement_desk.pricing.money import (
    ONE,
    ZERO,
    decimal_to_plain,
    fraction,
    safe_divide,
)

CALCULATION_VERSION = "1.0"


class PricingAgent:
    """Normalize structured offer facts; never infers missing facts."""

    def normalize(
        self,
        thread: ThreadRecord,
        analysis: ThreadAnalysis,
        policy: ResolvedPolicy,
        supplier: SupplierAnalysis,
    ) -> PricingAnalysis:
        offer = analysis.offer
        trace: list[PricingStep] = []
        transformations: list[str] = []
        warnings: list[str] = list(analysis.warnings)

        if analysis.missing_information or not offer.has_usable_price:
            reason = analysis.missing_reason or offer.missing_reason or "no_usable_price"
            return self._missing(
                thread,
                offer,
                policy,
                reason,
                trace,
                warnings,
                evidence=list(analysis.evidence),
            )
        if offer.unsupported_currency:
            return self._missing(
                thread,
                offer,
                policy,
                "unsupported_currency",
                trace,
                warnings,
                evidence=list(analysis.evidence),
            )

        amount: Decimal
        currency: str
        gst_inclusive: bool
        offered_period: BillingPeriod | None
        basis: OfferBasis
        previous_basis_applied = False

        if offer.previous_quote_discount_percent is not None:
            if (
                offer.previous_quote_amount is None
                or offer.previous_quote_currency is None
            ):
                return self._missing(
                    thread,
                    offer,
                    policy,
                    "previous_quote_missing",
                    trace,
                    warnings,
                    evidence=list(analysis.evidence),
                )
            amount = offer.previous_quote_amount
            currency = offer.previous_quote_currency
            gst_inclusive = offer.previous_quote_gst_inclusive
            offered_period = offer.previous_quote_billing_period
            basis = offer.previous_quote_basis
            trace.append(
                PricingStep(
                    step="previous_quote",
                    operation="start from supplier's own previous quote",
                    before=None,
                    after=decimal_to_plain(amount),
                    detail=(
                        f"{currency} {decimal_to_plain(amount)}; "
                        f"source message index {offer.previous_quote_source_index}"
                    ),
                )
            )
            amount = self._apply_basis(
                amount,
                basis,
                offer.previous_quote_total_quantity,
                offer.previous_quote_pack_size,
                offer.previous_quote_per_n,
                policy,
                trace,
                prefix="previous_quote_",
            )
            previous_basis_applied = True
            discount = offer.previous_quote_discount_percent
            factor = ONE - fraction(discount)
            before = amount
            amount = amount * factor
            trace.append(
                PricingStep(
                    step="previous_quote_discount",
                    operation=f"apply {decimal_to_plain(discount)}% off previous quote",
                    before=decimal_to_plain(before),
                    after=decimal_to_plain(amount),
                    detail="applied to the supplier's own quote, never Acme's counter",
                )
            )
            transformations.append(f"previous_quote_discount:{decimal_to_plain(discount)}%")
        else:
            if offer.quoted_amount is None or offer.currency is None:
                return self._missing(
                    thread,
                    offer,
                    policy,
                    "no_usable_price",
                    trace,
                    warnings,
                    evidence=list(analysis.evidence),
                )
            amount = offer.quoted_amount
            currency = offer.currency
            gst_inclusive = offer.gst_inclusive
            offered_period = offer.billing_period
            basis = offer.amount_basis
            trace.append(
                PricingStep(
                    step="quoted_amount",
                    operation="start from supplier's latest offer",
                    before=None,
                    after=decimal_to_plain(amount),
                    detail=f"{currency}; basis={basis.value}",
                )
            )

        if amount < 0:
            raise PricingError("quoted amount cannot be negative")

        if offer.list_discount_percent is not None:
            factor = ONE - fraction(offer.list_discount_percent)
            before = amount
            amount = amount * factor
            trace.append(
                PricingStep(
                    step="list_discount",
                    operation=(
                        f"apply {decimal_to_plain(offer.list_discount_percent)}% "
                        "discount to list price"
                    ),
                    before=decimal_to_plain(before),
                    after=decimal_to_plain(amount),
                )
            )
            transformations.append(
                f"list_discount:{decimal_to_plain(offer.list_discount_percent)}%"
            )

        if offer.volume_discount_percent is not None:
            if offer.volume_threshold is None:
                raise PricingError("volume discount without a quantity threshold")
            if thread.quantity >= offer.volume_threshold:
                factor = ONE - fraction(offer.volume_discount_percent)
                before = amount
                amount = amount * factor
                trace.append(
                    PricingStep(
                        step="volume_discount",
                        operation=(
                            f"apply {decimal_to_plain(offer.volume_discount_percent)}% "
                            f"for quantity >= {offer.volume_threshold}"
                        ),
                        before=decimal_to_plain(before),
                        after=decimal_to_plain(amount),
                    )
                )
                transformations.append(
                    f"volume_discount:{decimal_to_plain(offer.volume_discount_percent)}%"
                )
            else:
                trace.append(
                    PricingStep(
                        step="volume_discount",
                        operation="threshold not met; discount not applied",
                        before=decimal_to_plain(amount),
                        after=decimal_to_plain(amount),
                        detail=(
                            f"quantity {thread.quantity} < threshold "
                            f"{offer.volume_threshold}"
                        ),
                    )
                )
                warnings.append("volume discount threshold not met; base price used")

        if offer.free_units is not None:
            if offer.paid_units is None or offer.paid_units <= 0:
                raise PricingError("free-unit offer requires positive paid units")
            if offer.free_units < 0:
                raise PricingError("free units cannot be negative")
            denominator = offer.paid_units + offer.free_units
            factor = Decimal(offer.paid_units) / Decimal(denominator)
            before = amount
            amount = amount * factor
            trace.append(
                PricingStep(
                    step="free_units",
                    operation=(
                        f"effective price factor {offer.paid_units}/"
                        f"{denominator}"
                    ),
                    before=decimal_to_plain(before),
                    after=decimal_to_plain(amount),
                    detail=(
                        f"{offer.free_units} free for every {offer.paid_units} paid"
                    ),
                )
            )
            transformations.append(
                f"free_units:{offer.paid_units}paid+{offer.free_units}free"
            )

        if not previous_basis_applied:
            amount = self._apply_basis(
                amount,
                basis,
                offer.total_quantity,
                offer.pack_size,
                offer.per_n,
                policy,
                trace,
                prefix="",
            )

        exchange_rate, rate_source = resolve_exchange_rate(currency, supplier.currency_rates)
        if exchange_rate is None:
            return self._missing(
                thread,
                offer,
                policy,
                "unsupported_currency",
                trace,
                warnings,
                evidence=list(analysis.evidence),
            )
        amount_inr = amount * exchange_rate
        trace.append(
            PricingStep(
                step="currency_conversion",
                operation=f"convert {currency} to INR at {decimal_to_plain(exchange_rate)}",
                before=decimal_to_plain(amount),
                after=decimal_to_plain(amount_inr),
                detail=rate_source,
            )
        )
        transformations.append(f"fx:{currency}->INR@{decimal_to_plain(exchange_rate)}")

        if gst_inclusive:
            divisor = ONE + policy.gst_rate
            before = amount_inr
            amount_inr = amount_inr / divisor
            trace.append(
                PricingStep(
                    step="gst_removal",
                    operation=(
                        f"remove GST at {decimal_to_plain(policy.gst_rate * Decimal('100'))}%"
                    ),
                    before=decimal_to_plain(before),
                    after=decimal_to_plain(amount_inr),
                    detail=f"divide by 1 + {decimal_to_plain(policy.gst_rate)}",
                )
            )
            transformations.append(
                f"gst_inclusive:{decimal_to_plain(policy.gst_rate * Decimal('100'))}%"
            )
        else:
            trace.append(
                PricingStep(
                    step="gst_removal",
                    operation="no GST removal (quote is GST-exclusive or GST not stated)",
                    before=decimal_to_plain(amount_inr),
                    after=decimal_to_plain(amount_inr),
                )
            )

        required_period = policy.normalized_period is not None
        try:
            normalized_amount, period_steps = normalize_billing_period(
                amount_inr,
                offered_period,
                policy.normalized_period,
                required=required_period,
            )
        except PricingError as exc:
            if str(exc) == "missing_billing_period":
                return self._missing(
                    thread,
                    offer,
                    policy,
                    "subscription_period_missing",
                    trace,
                    warnings,
                    evidence=list(analysis.evidence),
                )
            raise
        for period_step in period_steps:
            trace.append(
                PricingStep(
                    step="billing_period",
                    operation=period_step,
                    before=decimal_to_plain(amount_inr),
                    after=decimal_to_plain(normalized_amount),
                    detail=(
                        f"offered={offered_period.value if offered_period else None}; "
                        f"normalized={policy.normalized_period.value if policy.normalized_period else None}"
                    ),
                )
            )
            transformations.append(period_step)

        if normalized_amount < 0:
            raise PricingError("normalized price cannot be negative")
        approval = approval_amount(normalized_amount, thread.quantity)
        trace.append(
            PricingStep(
                step="approval_amount",
                operation=f"normalized price × quantity ({thread.quantity})",
                before=decimal_to_plain(normalized_amount),
                after=decimal_to_plain(approval),
                detail="INR excl. GST, one normalized billing period",
            )
        )

        return PricingAnalysis(
            thread_id=thread.thread_id,
            quoted_amount=offer.quoted_amount,
            quoted_currency=offer.currency,
            quoted_basis=offer.amount_basis,
            exchange_rate=exchange_rate,
            exchange_rate_source=rate_source,
            gst_rate=policy.gst_rate,
            gst_inclusive=gst_inclusive,
            billing_period_offered=offered_period,
            normalized_period=policy.normalized_period,
            normalized_price=normalized_amount,
            normalized_price_inr_ex_gst=normalized_amount,
            approval_amount=approval,
            quantity=thread.quantity,
            missing_information=False,
            missing_reason=None,
            trace=trace,
            transformations=transformations,
            evidence=list(analysis.evidence),
            warnings=warnings,
            calculation_version=CALCULATION_VERSION,
        )

    def _apply_basis(
        self,
        amount: Decimal,
        basis: OfferBasis,
        total_quantity: int | None,
        pack_size: int | None,
        per_n: int | None,
        policy: ResolvedPolicy,
        trace: list[PricingStep],
        *,
        prefix: str,
    ) -> Decimal:
        if basis == OfferBasis.PER_UNIT:
            return amount
        if basis == OfferBasis.PREVIOUS_QUOTE:
            return amount
        if basis == OfferBasis.TOTAL:
            if total_quantity is None or total_quantity <= 0:
                raise PricingError("total quote without a positive quantity")
            result = safe_divide(amount, Decimal(total_quantity), "total-to-unit")
            trace.append(
                PricingStep(
                    step=f"{prefix}total_to_unit",
                    operation=f"divide total by {total_quantity} units",
                    before=decimal_to_plain(amount),
                    after=decimal_to_plain(result),
                )
            )
            return result
        if basis == OfferBasis.PER_DOZEN:
            result = amount / Decimal("12")
            trace.append(
                PricingStep(
                    step=f"{prefix}dozen",
                    operation="divide per-dozen price by 12",
                    before=decimal_to_plain(amount),
                    after=decimal_to_plain(result),
                )
            )
            return result
        if basis == OfferBasis.PER_PACK:
            size = pack_size or policy.pack_size
            if size is None or size <= 0:
                raise PricingError("per-pack quote without a pack size")
            result = safe_divide(amount, Decimal(size), "pack-to-unit")
            trace.append(
                PricingStep(
                    step=f"{prefix}pack_to_unit",
                    operation=f"divide pack price by {size} units per pack",
                    before=decimal_to_plain(amount),
                    after=decimal_to_plain(result),
                )
            )
            return result
        if basis == OfferBasis.PER_N:
            if per_n is None or per_n <= 0:
                raise PricingError("per-N quote without a positive N")
            result = safe_divide(amount, Decimal(per_n), "per-n-to-unit")
            trace.append(
                PricingStep(
                    step=f"{prefix}per_n_to_unit",
                    operation=f"divide price by {per_n} units",
                    before=decimal_to_plain(amount),
                    after=decimal_to_plain(result),
                )
            )
            return result
        if basis == OfferBasis.PER_SUB_UNIT:
            factor = policy.sub_unit_factor
            if factor is None or factor <= 0:
                raise PricingError("per-sub-unit quote without a conversion factor")
            result = amount * factor
            trace.append(
                PricingStep(
                    step=f"{prefix}sub_unit_to_unit",
                    operation=(
                        f"multiply per-{policy.sub_unit_name} price by {factor} "
                        f"{policy.sub_unit_name} per {policy.normalized_unit.split('per')[-1].strip()}"
                    ),
                    before=decimal_to_plain(amount),
                    after=decimal_to_plain(result),
                )
            )
            return result
        raise PricingError(f"unsupported offer basis {basis}")

    def _missing(
        self,
        thread: ThreadRecord,
        offer: OfferFacts,
        policy: ResolvedPolicy,
        reason: str,
        trace: list[PricingStep],
        warnings: list[str],
        *,
        evidence: list[str],
    ) -> PricingAnalysis:
        trace = list(trace)
        trace.append(
            PricingStep(
                step="missing_information",
                operation="stop pricing and preserve explicit unknown",
                detail=reason,
            )
        )
        return PricingAnalysis(
            thread_id=thread.thread_id,
            quoted_amount=offer.quoted_amount,
            quoted_currency=offer.currency,
            quoted_basis=offer.amount_basis,
            gst_inclusive=offer.gst_inclusive,
            billing_period_offered=offer.billing_period,
            normalized_period=policy.normalized_period,
            normalized_price=None,
            approval_amount=None,
            quantity=thread.quantity,
            missing_information=True,
            missing_reason=reason,
            trace=trace,
            transformations=[],
            evidence=evidence,
            warnings=warnings,
            calculation_version=CALCULATION_VERSION,
        )
