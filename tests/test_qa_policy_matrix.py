"""QA Phase 5: independent policy, amendment, and supplier matrix tests."""
from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.exceptions import (
    IngestionError,
    KnowledgeBaseError,
    PolicyResolutionError,
    SupplierResolutionError,
)
from procurement_desk.kb import build_knowledge_base
from procurement_desk.models import BillingPeriod, SupplierStatus
from procurement_desk.orchestrator import ProcurementGraph
from tests.conftest import make_thread

EXPECTED_CATEGORIES = {
    "catering": ("280", "340", "0.05", 3, "1", "600000", None, None, None, None),
    "cleaning": ("85000", "100000", "0.18", 4, "2", "900000", BillingPeriod.MONTH, None, None, None),
    "cloud-servers": ("96000", "115000", "0.18", 5, "3", "6000000", BillingPeriod.YEAR, None, None, None),
    "courier": ("160", "200", "0.18", 4, "2", "500000", None, None, None, None),
    "crm-licenses": ("18000", "22000", "0.18", 4, "2", "2500000", BillingPeriod.YEAR, None, None, None),
    "design-software": ("30000", "36000", "0.18", 4, "2", "1500000", BillingPeriod.YEAR, None, None, None),
    "headsets": ("3500", "4200", "0.18", 3, "1", "400000", None, None, None, None),
    "laptops": ("62000", "70000", "0.18", 4, "2", "4000000", None, None, None, None),
    "led-lighting": ("1800", "2200", "0.18", 3, "1", "350000", None, 4, None, None),
    "mobile-phones": ("24000", "28000", "0.18", 4, "2", "2000000", None, None, None, None),
    "monitors": ("14000", "16500", "0.18", 3, "1", "1200000", None, None, None, None),
    "office-chairs": ("9000", "11000", "0.18", 3, "1", "700000", None, None, None, None),
    "printer-paper": ("2200", "2600", "0.12", 3, "1", "250000", None, None, "reams", "10"),
    "security-guards": ("21000", "25000", "0.18", 4, "2", "1000000", BillingPeriod.MONTH, None, None, None),
    "training": ("6000", "7500", "0.18", 3, "1", "900000", None, None, None, None),
}

BLACKLISTED = {
    "GreenLeaf Facility Care",
    "Lumen Workspace",
    "Orbit Electronics",
}
PROBATION = {
    "Banyan Guarding",
    "Jade Express",
    "Vertex Mobile",
    "Zephyr SaaS",
}


def test_all_15_categories_base_values(kb):
    assert set(kb.categories) == set(EXPECTED_CATEGORIES)
    agent = PolicyAgent(kb)
    for slug, expected in EXPECTED_CATEGORIES.items():
        thread = make_thread(category=slug, thread_date=date(2026, 1, 1))
        policy = agent.resolve(thread)
        target, walkaway, gst, rounds, beta, approval, period, pack, sub_name, sub_factor = expected
        assert policy.target == Decimal(target)
        assert policy.walkaway == Decimal(walkaway)
        assert policy.gst_rate == Decimal(gst)
        assert policy.rounds == rounds
        assert policy.beta == Decimal(beta)
        assert policy.approval_limit == Decimal(approval)
        assert policy.normalized_period == period
        assert policy.pack_size == pack
        assert policy.sub_unit_name == sub_name
        assert policy.sub_unit_factor == (Decimal(sub_factor) if sub_factor else None)


def test_amendment_boundaries_all_categories(kb):
    agent = PolicyAgent(kb)

    cases = [
        ("courier", "2026-09-21", "2026-09-22", "walkaway", "200", "210"),
        ("cloud-servers", "2026-11-10", "2026-11-11", "walkaway", "115000", "119990"),
        ("mobile-phones", "2026-11-24", "2026-11-25", "walkaway", "28000", "29780"),
        ("catering", "2026-09-19", "2026-09-20", "target", "280", "270"),
        ("printer-paper", "2026-11-05", "2026-11-06", "walkaway", "2600", "2780"),
        ("headsets", "2026-11-08", "2026-11-09", "approval_limit", "400000", "320000"),
        ("monitors", "2026-12-13", "2026-12-14", "approval_limit", "1200000", "960000"),
        ("led-lighting", "2026-12-03", "2026-12-04", "walkaway", "2200", "2330"),
        ("led-lighting", "2026-12-04", "2026-12-05", "walkaway", "2330", "2360"),
    ]
    for category, before, on_date, field, before_value, on_value in cases:
        p_before = agent.resolve(make_thread(category=category, thread_date=date.fromisoformat(before)))
        p_on = agent.resolve(make_thread(category=category, thread_date=date.fromisoformat(on_date)))
        assert getattr(p_before, field) == Decimal(before_value), (category, before, field)
        assert getattr(p_on, field) == Decimal(on_value), (category, on_date, field)
        assert getattr(p_on, field) != getattr(p_before, field)


def test_led_multiple_amendments_later_date_wins(kb):
    agent = PolicyAgent(kb)
    policy = agent.resolve(make_thread(category="led-lighting", thread_date=date(2026, 12, 20)))
    assert policy.walkaway == Decimal("2360")
    assert [a.amendment_id for a in policy.applied_amendments] == ["AMD-08", "AMD-07"]


def test_all_40_supplier_statuses(kb):
    assert len(kb.suppliers) == 40
    agent = SupplierAgent(kb)
    for supplier in kb.suppliers.values():
        result = agent.resolve(make_thread(supplier=supplier.display_name, category="training"))
        if supplier.display_name in BLACKLISTED:
            assert result.status is SupplierStatus.BLACKLISTED
        elif supplier.display_name in PROBATION:
            assert result.status is SupplierStatus.PROBATION
        else:
            assert result.status is SupplierStatus.APPROVED


def test_supplier_cap_only_for_matching_category(kb):
    agent = SupplierAgent(kb)
    categories = sorted(kb.categories)
    for supplier in kb.suppliers.values():
        for cap_category, cap_value in supplier.category_caps.items():
            matching = agent.resolve(make_thread(supplier=supplier.display_name, category=cap_category))
            assert matching.category_cap == cap_value
            assert matching.category_cap_applied is True
            other = next(c for c in categories if c != cap_category)
            non_matching = agent.resolve(make_thread(supplier=supplier.display_name, category=other))
            assert non_matching.category_cap is None
            assert non_matching.category_cap_applied is False


def test_supplier_currency_override_scope(kb):
    agent = SupplierAgent(kb)
    for supplier in kb.suppliers.values():
        result = agent.resolve(make_thread(supplier=supplier.display_name, category="training"))
        assert result.currency_rates == supplier.currency_rates
        for currency in result.currency_rates:
            assert currency in {"USD", "EUR", "GBP"}


def test_probation_and_blacklist_behaviour_all_statuses(kb):
    graph = ProcurementGraph(kb, run_id="qa-status")
    for supplier in kb.suppliers.values():
        thread = make_thread(
            supplier=supplier.display_name,
            category="training",
            quantity=10,
            round_number=1,
            message="We can do INR 100 per participant.",
            thread_date=date(2026, 10, 1),
        )
        state = graph.run(thread)
        if supplier.display_name in BLACKLISTED:
            assert state["final_label"] == "REJECT:BLACKLISTED_SUPPLIER:"
        else:
            assert state["final_label"] == "ACCEPT:ACCEPTABLE_PRICE:"

    for supplier_name in sorted(PROBATION):
        thread = make_thread(
            supplier=supplier_name,
            category="training",
            quantity=10,
            round_number=1,
            message="We can do INR 7,000 per participant.",
            thread_date=date(2026, 10, 1),
        )
        state = graph.run(thread)
        assert state["final_label"] == "COUNTER:COUNTER_OFFER:6000"


def test_unknown_category_and_supplier_graph_fallbacks(kb):
    graph = ProcurementGraph(kb, run_id="qa-unknown")
    unknown_category = make_thread(category="industrial-widgets", message="We can do INR 100 per widget.")
    state = graph.run(unknown_category)
    assert state["final_label"] == "ESCALATE:MISSING_INFO:"
    assert state["outcome_status"] == "fallback"
    unknown_supplier = make_thread(supplier="Unknown Vendor", message="We can do INR 100 per laptop.")
    state2 = graph.run(unknown_supplier)
    assert state2["final_label"] == "ESCALATE:MISSING_INFO:"
    assert state2["outcome_status"] == "fallback"


def test_missing_policy_document_fails_loudly(playbook_dir: Path, tmp_path: Path):
    copied = tmp_path / "playbook" / "playbook"
    shutil.copytree(playbook_dir, copied)
    (copied / "policies" / "approval-limits.md").unlink()
    with pytest.raises(KnowledgeBaseError):
        build_knowledge_base(copied)


def test_missing_category_field_fails_loudly(playbook_dir: Path, tmp_path: Path):
    copied = tmp_path / "playbook" / "playbook"
    shutil.copytree(playbook_dir, copied)
    path = copied / "categories" / "monitors.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(line for line in text.splitlines() if "Target price" not in line),
        encoding="utf-8",
    )
    with pytest.raises(IngestionError):
        build_knowledge_base(copied)


def test_conflicting_category_values_are_preserved_with_warning(playbook_dir: Path, tmp_path: Path):
    copied = tmp_path / "playbook" / "playbook"
    shutil.copytree(playbook_dir, copied)
    path = copied / "categories" / "monitors.md"
    text = path.read_text(encoding="utf-8").replace("₹14,000", "₹20,000")
    path.write_text(text, encoding="utf-8")
    kb = build_knowledge_base(copied)
    policy = PolicyAgent(kb).resolve(make_thread(category="monitors", thread_date=date(2026, 10, 1)))
    assert policy.target == Decimal("20000")
    assert policy.walkaway == Decimal("16500")
    assert any("exceeds effective walk-away" in warning for warning in policy.warnings)


def test_unknown_supplier_and_category_resolution_errors(kb):
    with pytest.raises(PolicyResolutionError):
        PolicyAgent(kb).resolve(make_thread(category="unknown-category"))
    with pytest.raises(SupplierResolutionError):
        SupplierAgent(kb).resolve(make_thread(supplier="Unknown Vendor"))
