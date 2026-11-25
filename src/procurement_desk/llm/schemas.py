"""Structured output schema for optional LLM offer extraction."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from procurement_desk.models import BillingPeriod, OfferBasis, StrictModel


class LLMOfferExtraction(StrictModel):
    """The only output shape the LLM is allowed to return.

    It describes observable offer facts.  It must not contain an action, a
    reason decision, a counter price, or any arithmetic result.
    """

    has_usable_price: bool
    currency: str | None = None
    quoted_amount: Decimal | None = None
    quoted_amount_text: str | None = None
    amount_basis: OfferBasis = OfferBasis.PER_UNIT
    total_quantity: int | None = None
    pack_size: int | None = None
    per_n: int | None = None
    billing_period: BillingPeriod | None = None
    gst_inclusive: bool = False

    list_discount_percent: Decimal | None = None
    previous_quote_discount_percent: Decimal | None = None
    volume_discount_percent: Decimal | None = None
    volume_threshold: int | None = None
    free_units: int | None = None
    paid_units: int | None = None

    is_correction: bool = False
    is_range: bool = False
    range_used_high: bool = False
    tier_threshold: int | None = None
    tier_branch: Literal["up_to", "larger"] | None = None

    unsupported_currency: bool = False
    unsupported_currency_code: str | None = None
    missing_reason: str | None = None
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shape(self) -> "LLMOfferExtraction":
        if self.has_usable_price:
            if self.quoted_amount is None or self.currency is None:
                raise ValueError("usable LLM offer needs amount and currency")
            if not self.evidence:
                raise ValueError("usable LLM offer must cite evidence")
            if self.unsupported_currency:
                raise ValueError("usable offer cannot use unsupported currency")
        return self
