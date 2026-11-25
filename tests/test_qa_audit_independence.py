"""QA regression: the audit must not simply inherit PricingAgent arithmetic."""
from __future__ import annotations

from datetime import date

from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.audit_agent import AuditAgent
from procurement_desk.models import Decision
from procurement_desk.orchestrator import ProcurementGraph
from tests.conftest import make_thread
from tests.test_audit_agent import run_pipeline


def test_independent_audit_catches_systematic_pricing_double(kb, monkeypatch):
    original = PricingAgent.normalize

    def doubled(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if result.normalized_price is not None:
            result = result.model_copy(
                update={
                    "normalized_price": result.normalized_price * 2,
                    "normalized_price_inr_ex_gst": result.normalized_price * 2,
                    "approval_amount": (result.approval_amount or 0) * 2,
                }
            )
        return result

    monkeypatch.setattr(PricingAgent, "normalize", doubled)
    thread = make_thread(
        category="monitors",
        supplier="Coastline Caterers",
        quantity=50,
        round_number=1,
        thread_date=date(2026, 12, 10),
        message="We can do INR 12,662 per monitor.",
    )
    state = ProcurementGraph(kb, run_id="audit-independence").run(thread)
    assert state["outcome_status"] == "fallback"
    assert state["audit"].passed is False
    assert any("independent_price_arithmetic" in failure for failure in state["audit"].failures)
    monkeypatch.setattr(PricingAgent, "normalize", original)


def test_independent_audit_passes_ordinary_pricing(kb):
    thread = make_thread(
        category="monitors",
        supplier="Coastline Caterers",
        quantity=50,
        round_number=1,
        thread_date=date(2026, 12, 10),
        message="We can do INR 12,662 per monitor.",
    )
    state = ProcurementGraph(kb, run_id="audit-normal").run(thread)
    assert state["audit"].passed is True
    assert any(
        check.name == "independent_price_arithmetic" and check.passed
        for check in state["audit"].checks
    )


def test_audit_label_equality_check_is_independent(kb):
    thread = make_thread(
        category="monitors",
        supplier="Coastline Caterers",
        quantity=50,
        round_number=1,
        thread_date=date(2026, 12, 10),
        message="We can do INR 12,662 per monitor.",
    )
    analysis, policy, supplier, security, pricing, decision, _ = run_pipeline(kb, thread)
    corrupt = Decision.model_construct(
        action=decision.action,
        reason=decision.reason,
        counter_price=decision.counter_price,
        label="REJECT:ABOVE_WALKAWAY:",
        precedence_trace=decision.precedence_trace,
        evidence=decision.evidence,
        values=decision.values,
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
    assert any("final_label" in failure for failure in audit.failures)
