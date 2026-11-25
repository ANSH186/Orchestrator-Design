from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.exceptions import PolicyResolutionError, SupplierResolutionError
from procurement_desk.models import BillingPeriod, SupplierStatus
from tests.conftest import make_thread


def resolve(kb, category: str, thread_date: str, supplier: str = "Coastline Caterers"):
    agent = PolicyAgent(kb)
    return agent.resolve(
        make_thread(category=category, thread_date=date.fromisoformat(thread_date), supplier=supplier)
    )


def test_base_policy_before_any_amendment(kb):
    policy = resolve(kb, "courier", "2026-09-21")
    assert policy.walkaway == Decimal("200")
    assert policy.target == Decimal("160")
    assert policy.approval_limit == Decimal("500000")
    assert policy.normalized_period is None
    assert policy.applied_amendments == []


def test_courier_amendment_boundaries(kb):
    assert resolve(kb, "courier", "2026-09-21").walkaway == Decimal("200")
    on_date = resolve(kb, "courier", "2026-09-22")
    assert on_date.walkaway == Decimal("210")
    assert [a.amendment_id for a in on_date.applied_amendments] == ["AMD-01"]
    assert resolve(kb, "courier", "2026-12-20").walkaway == Decimal("210")


def test_catering_target_amendment_boundaries(kb):
    assert resolve(kb, "catering", "2026-09-19").target == Decimal("280")
    on_date = resolve(kb, "catering", "2026-09-20")
    assert on_date.target == Decimal("270")
    assert on_date.walkaway == Decimal("340")
    assert [a.amendment_id for a in on_date.applied_amendments] == ["AMD-04"]


def test_cloud_walkaway_amendment(kb):
    assert resolve(kb, "cloud-servers", "2026-11-10").walkaway == Decimal("115000")
    assert resolve(kb, "cloud-servers", "2026-11-11").walkaway == Decimal("119990")


def test_mobile_walkaway_amendment(kb):
    assert resolve(kb, "mobile-phones", "2026-11-24").walkaway == Decimal("28000")
    assert resolve(kb, "mobile-phones", "2026-11-25").walkaway == Decimal("29780")


def test_printer_walkaway_amendment(kb):
    assert resolve(kb, "printer-paper", "2026-11-05").walkaway == Decimal("2600")
    assert resolve(kb, "printer-paper", "2026-11-06").walkaway == Decimal("2780")


def test_headsets_approval_amendment(kb):
    before = resolve(kb, "headsets", "2026-11-08")
    assert before.approval_limit == Decimal("400000")
    assert before.target == Decimal("3500")
    on_date = resolve(kb, "headsets", "2026-11-09")
    assert on_date.approval_limit == Decimal("320000")
    assert on_date.target == Decimal("3500")


def test_monitors_approval_amendment(kb):
    assert resolve(kb, "monitors", "2026-12-13").approval_limit == Decimal("1200000")
    assert resolve(kb, "monitors", "2026-12-14").approval_limit == Decimal("960000")


def test_led_amendments_apply_by_effective_date_not_filename(kb):
    before = resolve(kb, "led-lighting", "2026-12-03")
    assert before.walkaway == Decimal("2200")
    first = resolve(kb, "led-lighting", "2026-12-04")
    assert first.walkaway == Decimal("2330")
    assert [a.amendment_id for a in first.applied_amendments] == ["AMD-08"]
    second = resolve(kb, "led-lighting", "2026-12-05")
    assert second.walkaway == Decimal("2360")
    assert [a.amendment_id for a in second.applied_amendments] == ["AMD-08", "AMD-07"]
    assert resolve(kb, "led-lighting", "2026-12-20").walkaway == Decimal("2360")


def test_policy_does_not_apply_supplier_cap(kb):
    policy = PolicyAgent(kb).resolve(
        make_thread(
            category="catering",
            supplier="Helix CRM",
            thread_date=date(2026, 12, 10),
        )
    )
    assert policy.walkaway == Decimal("340")
    assert policy.target == Decimal("270")


def test_supplier_status_and_caps_are_separate(kb):
    agent = SupplierAgent(kb)
    helix = agent.resolve(
        make_thread(category="catering", supplier="Helix CRM", thread_date=date(2026, 12, 10))
    )
    assert helix.status is SupplierStatus.APPROVED
    assert helix.category_cap == Decimal("400")
    assert helix.category_cap_applied is True

    helix_other = agent.resolve(
        make_thread(category="headsets", supplier="Helix CRM", thread_date=date(2026, 12, 10))
    )
    assert helix_other.category_cap is None
    assert helix_other.category_cap_applied is False


@pytest.mark.parametrize(
    ("supplier", "status"),
    [
        ("GreenLeaf Facility Care", SupplierStatus.BLACKLISTED),
        ("Lumen Workspace", SupplierStatus.BLACKLISTED),
        ("Orbit Electronics", SupplierStatus.BLACKLISTED),
        ("Banyan Guarding", SupplierStatus.PROBATION),
        ("Jade Express", SupplierStatus.PROBATION),
        ("Vertex Mobile", SupplierStatus.PROBATION),
        ("Zephyr SaaS", SupplierStatus.PROBATION),
        ("Coastline Caterers", SupplierStatus.APPROVED),
    ],
)
def test_supplier_statuses(kb, supplier, status):
    result = SupplierAgent(kb).resolve(
        make_thread(category="laptops", supplier=supplier, thread_date=date(2026, 10, 1))
    )
    assert result.status is status


def test_currency_overrides_only_for_matching_supplier(kb):
    agent = SupplierAgent(kb)
    arvind = agent.resolve(
        make_thread(category="laptops", supplier="Arvind Office Supplies", thread_date=date(2026, 10, 1))
    )
    assert arvind.currency_rates == {"GBP": Decimal("104.5")}
    other = agent.resolve(
        make_thread(category="laptops", supplier="Coastline Caterers", thread_date=date(2026, 10, 1))
    )
    assert other.currency_rates == {}


def test_category_cap_isolation(kb):
    agent = SupplierAgent(kb)
    xenon_led = agent.resolve(
        make_thread(category="led-lighting", supplier="Xenon Displays", thread_date=date(2026, 12, 10))
    )
    assert xenon_led.category_cap == Decimal("2300")
    xenon_other = agent.resolve(
        make_thread(category="monitors", supplier="Xenon Displays", thread_date=date(2026, 12, 10))
    )
    assert xenon_other.category_cap is None


def test_unknown_category_and_supplier_fail_loudly(kb):
    with pytest.raises(PolicyResolutionError):
        PolicyAgent(kb).resolve(
            make_thread(category="does-not-exist", thread_date=date(2026, 10, 1))
        )
    with pytest.raises(SupplierResolutionError):
        SupplierAgent(kb).resolve(
            make_thread(supplier="Unknown Vendor", thread_date=date(2026, 10, 1))
        )
