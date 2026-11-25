from __future__ import annotations

from datetime import date
from decimal import Decimal

from procurement_desk.agents.decision_agent import DecisionAgent
from procurement_desk.models import (
    Action,
    AuditCheck,
    BillingPeriod,
    Decision,
    Message,
    MessageRole,
    OfferFacts,
    PricingAnalysis,
    ReasonCode,
    ResolvedPolicy,
    SecurityAnalysis,
    SecurityEvidence,
    SupplierAnalysis,
    SupplierStatus,
    ThreadAnalysis,
)
from tests.conftest import make_thread


def policy(
    *,
    target: str = "100",
    walkaway: str = "200",
    rounds: int = 3,
    beta: str = "1",
    approval: str = "100000",
) -> ResolvedPolicy:
    return ResolvedPolicy(
        category_slug="monitors",
        category_name="Monitors",
        thread_date=date(2026, 10, 1),
        normalized_unit="INR excl. GST per monitor",
        normalized_period=None,
        gst_rate=Decimal("0.18"),
        target=Decimal(target),
        walkaway=Decimal(walkaway),
        rounds=rounds,
        beta=Decimal(beta),
        approval_limit=Decimal(approval),
        pack_size=None,
        sub_unit_name=None,
        sub_unit_factor=None,
        base_target=Decimal(target),
        base_walkaway=Decimal(walkaway),
        base_approval_limit=Decimal(approval),
        category_source="test",
    )


def analysis(
    *,
    missing: bool = False,
    reason: str | None = None,
    offer: OfferFacts | None = None,
) -> ThreadAnalysis:
    offer = offer or OfferFacts(
        has_usable_price=True, currency="INR", quoted_amount=Decimal("100")
    )
    return ThreadAnalysis(
        thread_id="T1",
        supplier="Jupiter Devices",
        category="monitors",
        messages=[
            Message(index=0, role=MessageRole.SUPPLIER, is_latest=True, text="test")
        ],
        latest_supplier_message="test",
        offer=offer,
        missing_information=missing,
        missing_reason=reason,
        evidence=["test"],
    )


def supplier(status: SupplierStatus = SupplierStatus.APPROVED, cap: str | None = None) -> SupplierAnalysis:
    return SupplierAnalysis(
        key="jupiter-devices",
        display_name="Jupiter Devices",
        status=status,
        category_cap=Decimal(cap) if cap is not None else None,
        category_cap_applied=cap is not None,
        source_path="test",
    )


def security(
    *, injection: bool = False, banned: bool = False
) -> SecurityAnalysis:
    return SecurityAnalysis(
        prompt_injection_detected=injection,
        injection_findings=[
            SecurityEvidence(rule_id="test", category="prompt_injection", matched_text="x")
        ]
        if injection
        else [],
        banned_term_detected=banned,
        banned_term_findings=[
            SecurityEvidence(rule_id="test", category="banned_term", matched_text="x")
        ]
        if banned
        else [],
    )


def pricing(amount: str = "100", quantity: int = 10, missing: bool = False) -> PricingAnalysis:
    if missing:
        return PricingAnalysis(
            thread_id="T1",
            quantity=quantity,
            missing_information=True,
            missing_reason="no_usable_price",
        )
    value = Decimal(amount)
    return PricingAnalysis(
        thread_id="T1",
        quantity=quantity,
        normalized_price=value,
        normalized_price_inr_ex_gst=value,
        approval_amount=value * quantity,
    )


_UNSET = object()


def decide(
    *,
    thread=None,
    pol=None,
    analysis_obj=None,
    supplier_obj=None,
    security_obj=None,
    pricing_obj=_UNSET,
    round_number: int = 2,
    quantity: int = 10,
):
    thread = thread or make_thread(
        category="monitors", quantity=quantity, round_number=round_number
    )
    resolved_pricing = pricing() if pricing_obj is _UNSET else pricing_obj
    return DecisionAgent().decide(
        thread=thread,
        analysis=analysis_obj or analysis(),
        policy=pol or policy(),
        supplier=supplier_obj or supplier(),
        security=security_obj or security(),
        pricing=resolved_pricing,
    )


def test_missing_beats_blacklist():
    decision = decide(
        analysis_obj=analysis(missing=True, reason="no_usable_price"),
        supplier_obj=supplier(SupplierStatus.BLACKLISTED),
        pricing_obj=None,
    )
    assert decision.label == "ESCALATE:MISSING_INFO:"


def test_blacklist_beats_injection():
    decision = decide(
        supplier_obj=supplier(SupplierStatus.BLACKLISTED),
        security_obj=security(injection=True),
        pricing_obj=None,
    )
    assert decision.label == "REJECT:BLACKLISTED_SUPPLIER:"


def test_injection_beats_banned():
    decision = decide(
        security_obj=security(injection=True, banned=True),
        pricing_obj=None,
    )
    assert decision.label == "ESCALATE:PROMPT_INJECTION:"


def test_banned_beats_price_and_approval():
    decision = decide(
        security_obj=security(banned=True),
        pricing_obj=pricing("999", quantity=100),
    )
    assert decision.label == "ESCALATE:BANNED_TERM:"


def test_probation_still_loses_to_earlier_rules():
    decision = decide(
        analysis_obj=analysis(missing=True, reason="no_usable_price"),
        supplier_obj=supplier(SupplierStatus.PROBATION),
        pricing_obj=None,
    )
    assert decision.label == "ESCALATE:MISSING_INFO:"
    decision = decide(
        supplier_obj=supplier(SupplierStatus.PROBATION),
        security_obj=security(banned=True),
    )
    assert decision.label == "ESCALATE:BANNED_TERM:"


def test_accept_and_approval_exact_boundary():
    decision = decide(pricing_obj=pricing("100", quantity=10), pol=policy(approval="1000"))
    assert decision.action is Action.ACCEPT
    assert decision.label == "ACCEPT:ACCEPTABLE_PRICE:"


def test_over_approval_limit():
    decision = decide(pricing_obj=pricing("100.01", quantity=10), pol=policy(approval="1000"))
    assert decision.label == "ESCALATE:OVER_APPROVAL_LIMIT:"


def test_above_walkaway_on_final_round():
    decision = decide(
        round_number=3,
        pricing_obj=pricing("201", quantity=1),
        pol=policy(),
    )
    assert decision.label == "REJECT:ABOVE_WALKAWAY:"


def test_counter_before_final_round():
    decision = decide(
        round_number=2,
        pricing_obj=pricing("201", quantity=1),
        pol=policy(target="100", walkaway="200", rounds=3, beta="1"),
    )
    assert decision.label == "COUNTER:COUNTER_OFFER:150"


def test_probation_threshold_is_target_each_round():
    decision = decide(
        round_number=2,
        pol=policy(target="100", walkaway="200", rounds=3, beta="1"),
        supplier_obj=supplier(SupplierStatus.PROBATION),
        pricing_obj=pricing("150", quantity=1),
    )
    assert decision.label == "COUNTER:COUNTER_OFFER:100"
    final = decide(
        round_number=3,
        pol=policy(target="100", walkaway="200", rounds=3, beta="1"),
        supplier_obj=supplier(SupplierStatus.PROBATION),
        pricing_obj=pricing("150", quantity=1),
    )
    assert final.label == "REJECT:ABOVE_WALKAWAY:"


def test_contract_cap_replaces_walkaway_in_concession():
    decision = decide(
        round_number=3,
        pol=policy(target="100", walkaway="200", rounds=3, beta="1"),
        supplier_obj=supplier(SupplierStatus.APPROVED, cap="120"),
        pricing_obj=pricing("150", quantity=1),
    )
    assert decision.label == "REJECT:ABOVE_WALKAWAY:"
    assert decision.values["walkaway"] == "120"


def test_counter_round_half_up_exact_half():
    decision = decide(
        round_number=2,
        pol=policy(target="100", walkaway="102", rounds=3, beta="2"),
        pricing_obj=pricing("101", quantity=1),
    )
    assert decision.label == "COUNTER:COUNTER_OFFER:101"


def test_price_exactly_at_level_is_acceptable():
    decision = decide(
        round_number=2,
        pol=policy(target="100", walkaway="200", rounds=3, beta="1"),
        pricing_obj=pricing("150", quantity=1),
    )
    assert decision.label == "ACCEPT:ACCEPTABLE_PRICE:"
