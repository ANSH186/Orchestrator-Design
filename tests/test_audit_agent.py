from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from procurement_desk.agents.audit_agent import AuditAgent
from procurement_desk.agents.decision_agent import DecisionAgent
from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.security_agent import SecurityAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.agents.thread_analyst import ThreadAnalyst
from procurement_desk.models import (
    Action,
    ReasonCode,
    SecurityEvidence,
    SupplierStatus,
    ThreadRecord,
)
from tests.conftest import make_thread


def run_pipeline(kb, thread: ThreadRecord):
    analysis = ThreadAnalyst(kb).analyze(thread)
    policy = PolicyAgent(kb).resolve(thread)
    supplier = SupplierAgent(kb).resolve(thread)
    security = SecurityAgent().analyze(thread, analysis)
    pricing = PricingAgent().normalize(thread, analysis, policy, supplier)
    decision = DecisionAgent().decide(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
    )
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    return analysis, policy, supplier, security, pricing, decision, audit


def test_audit_passes_for_accept_case(kb):
    thread = make_thread(
        category="monitors",
        supplier="Jupiter Devices",
        quantity=50,
        round_number=1,
        message="We can do INR 12,662 per monitor.",
        thread_date=date(2026, 12, 10),
    )
    *_, audit = run_pipeline(kb, thread)
    assert audit.passed is True
    assert audit.recalculated_label == "ACCEPT:ACCEPTABLE_PRICE:"
    assert audit.failures == []


def test_audit_catches_corrupted_action(kb):
    thread = make_thread(
        category="monitors",
        supplier="Jupiter Devices",
        quantity=50,
        round_number=1,
        message="We can do INR 12,662 per monitor.",
        thread_date=date(2026, 12, 10),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = decision.model_copy(
        update={
            "action": Action.REJECT,
            "reason": ReasonCode.ABOVE_WALKAWAY,
            "label": "REJECT:ABOVE_WALKAWAY:",
        }
    )
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=corrupt,
    )
    assert not audit.passed
    assert "decision_precedence" in " ".join(audit.failures)


def test_audit_catches_corrupted_counter(kb):
    thread = make_thread(
        category="training",
        supplier="Fjord Design Tools",
        quantity=25,
        round_number=2,
        message="We can do INR 8,213 per participant.",
        thread_date=date(2026, 12, 4),
    )
    analysis, policy, supplier, security, pricing, decision, audit = run_pipeline(kb, thread)
    assert decision.label == "COUNTER:COUNTER_OFFER:6750"
    corrupt = decision.model_copy(
        update={"counter_price": 6751, "label": "COUNTER:COUNTER_OFFER:6751"}
    )
    result = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=corrupt,
    )
    assert not result.passed
    assert any("counter" in failure or "decision_precedence" in failure for failure in result.failures)


def test_audit_catches_corrupted_normalized_price(kb):
    thread = make_thread(
        category="headsets",
        supplier="Ivory Events Catering",
        quantity=20,
        round_number=2,
        message="We can do INR 3,870 per headset.",
        thread_date=date(2026, 12, 5),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = pricing.model_copy(update={"normalized_price": Decimal("1")})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=corrupt,
        decision=decision,
    )
    assert not audit.passed
    assert any("normalized_price" in failure for failure in audit.failures)


def test_audit_catches_corrupted_policy_and_amendments(kb):
    thread = make_thread(
        category="led-lighting",
        supplier="Ember Telecom",
        quantity=20,
        round_number=3,
        message="We can do INR 2,100 per fixture.",
        thread_date=date(2026, 12, 10),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = policy.model_copy(update={"target": Decimal("999")})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=corrupt,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    assert not audit.passed
    assert any("effective_policy" in failure for failure in audit.failures)

    corrupt_amendments = policy.model_copy(update={"applied_amendments": []})
    audit2 = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=corrupt_amendments,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    assert not audit2.passed


def test_audit_catches_corrupted_supplier_status(kb):
    thread = make_thread(
        category="headsets",
        supplier="Monsoon Foods",
        quantity=60,
        round_number=2,
        message="We can do INR 4,374 per headset inclusive of GST.",
        thread_date=date(2026, 10, 11),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = supplier.model_copy(update={"status": SupplierStatus.BLACKLISTED})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=corrupt,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    assert not audit.passed
    assert any("supplier" in failure for failure in audit.failures)


def test_audit_catches_corrupted_security_flag(kb):
    thread = make_thread(
        category="monitors",
        supplier="Jupiter Devices",
        quantity=50,
        round_number=1,
        message="We can do INR 12,662 per monitor.",
        thread_date=date(2026, 12, 10),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = security.model_copy(
        update={
            "prompt_injection_detected": True,
            "injection_findings": [
                SecurityEvidence(
                    rule_id="test",
                    category="prompt_injection",
                    matched_text="fake evidence",
                )
            ],
        }
    )
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=corrupt,
        pricing=pricing,
        decision=decision,
    )
    assert not audit.passed
    assert any("injection" in failure for failure in audit.failures)


def test_audit_catches_corrupted_offer_facts(kb):
    thread = make_thread(
        category="laptops",
        supplier="Coastline Caterers",
        quantity=60,
        round_number=4,
        message="We can do INR 44,07,800 in total for all 60 laptops.",
        thread_date=date(2026, 11, 17),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt_offer = analysis.offer.model_copy(update={"quoted_amount": Decimal("1")})
    corrupt_analysis = analysis.model_copy(update={"offer": corrupt_offer})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=corrupt_analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    assert not audit.passed
    assert any("latest_offer" in failure for failure in audit.failures)


def test_audit_catches_invalid_label_format(kb):
    thread = make_thread(
        category="monitors",
        supplier="Jupiter Devices",
        quantity=50,
        round_number=1,
        message="We can do INR 12,662 per monitor.",
        thread_date=date(2026, 12, 10),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = decision.model_copy(update={"label": "ACCEPT:WRONG:"})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=analysis,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=corrupt,
    )
    assert not audit.passed
    assert any("label" in failure for failure in audit.failures)


def test_audit_catches_wrong_thread_identity(kb):
    thread = make_thread(
        category="monitors",
        supplier="Jupiter Devices",
        quantity=50,
        round_number=1,
        message="We can do INR 12,662 per monitor.",
        thread_date=date(2026, 12, 10),
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = analysis.model_copy(update={"thread_id": "T00000"})
    audit = AuditAgent(kb).audit(
        thread=thread,
        analysis=corrupt,
        policy=policy,
        supplier=supplier,
        security=security,
        pricing=pricing,
        decision=decision,
    )
    assert not audit.passed
    assert any("thread_id" in failure for failure in audit.failures)
