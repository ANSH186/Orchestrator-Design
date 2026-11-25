"""Deterministic concession-schedule and approval-limit mathematics."""

from __future__ import annotations

from decimal import Decimal

from procurement_desk.exceptions import PricingError

ZERO = Decimal("0")
ONE = Decimal("1")
TWELVE = Decimal("12")


def acceptable_price(
    *,
    target: Decimal,
    walkaway: Decimal,
    rounds: int,
    round_number: int,
    beta: Decimal,
    probation: bool = False,
) -> Decimal:
    """Return L(r), the acceptable normalized price for this offer round.

    L(r) = T + (W - T) * ((r - 1) / (R - 1)) ** beta
    Round 1 is exactly T; the final round is exactly W.  A probation supplier
    receives no concession, so L(r) = T in every round.
    """

    if target < 0 or walkaway < 0:
        raise PricingError("target and walk-away must be non-negative")
    if rounds < 2:
        raise PricingError("category rounds must be at least 2")
    if not 1 <= round_number <= rounds:
        raise PricingError(
            f"round {round_number} is outside 1..{rounds} for this category"
        )
    if probation:
        return target
    if round_number == 1:
        return target
    if round_number == rounds:
        return walkaway
    if beta != beta.to_integral_value():
        raise PricingError("non-integer concession exponents are not supported by the playbook")
    ratio = Decimal(round_number - 1) / Decimal(rounds - 1)
    exponent = int(beta)
    if exponent == 0:
        weight = ONE
    else:
        weight = ratio**exponent
    return target + (walkaway - target) * weight


def approval_amount(normalized_price: Decimal, quantity: int) -> Decimal:
    """p × quantity.  ``p`` is already in the category's normalized period."""

    if quantity <= 0:
        raise PricingError("quantity must be positive")
    if normalized_price < 0:
        raise PricingError("normalized price must be non-negative")
    return normalized_price * Decimal(quantity)


def exceeds_approval_limit(amount: Decimal, approval_limit: Decimal) -> bool:
    """The playbook allows acceptance at the limit; only strictly above escalates."""

    return amount > approval_limit
