from __future__ import annotations

from decimal import Decimal

from procurement_desk.models import AmendmentField, BillingPeriod, SupplierStatus


def test_playbook_completeness(kb):
    assert len(kb.categories) == 15
    assert len(kb.suppliers) == 40
    assert len(kb.amendments) == 9
    assert len(kb.precedents) == 8
    assert len(kb.policies) == 7
    assert len(kb.documents) == 80
    assert len(kb.source_hash) == 64


def test_category_values(kb):
    catering = kb.categories["catering"]
    assert catering.target == Decimal("280")
    assert catering.walkaway == Decimal("340")
    assert catering.gst_rate == Decimal("0.05")
    assert catering.rounds == 3
    assert catering.beta == Decimal("1")
    assert catering.approval_limit == Decimal("600000")
    assert catering.normalized_period is None

    cloud = kb.categories["cloud-servers"]
    assert cloud.target == Decimal("96000")
    assert cloud.walkaway == Decimal("115000")
    assert cloud.rounds == 5
    assert cloud.beta == Decimal("3")
    assert cloud.normalized_period is BillingPeriod.YEAR
    assert cloud.approval_limit == Decimal("6000000")

    cleaning = kb.categories["cleaning"]
    assert cleaning.gst_rate == Decimal("0.18")
    assert cleaning.normalized_period is BillingPeriod.MONTH
    assert cleaning.rounds == 4
    assert cleaning.beta == Decimal("2")

    paper = kb.categories["printer-paper"]
    assert paper.gst_rate == Decimal("0.12")
    assert paper.sub_unit_name == "reams"
    assert paper.sub_unit_factor == Decimal("10")

    led = kb.categories["led-lighting"]
    assert led.pack_size == 4


def test_all_category_units_are_classes(kb):
    assert all(c.source_path.endswith(".md") for c in kb.categories.values())
    assert sum(c.gst_rate == Decimal("0.05") for c in kb.categories.values()) == 1
    assert sum(c.gst_rate == Decimal("0.12") for c in kb.categories.values()) == 1
    assert sum(c.gst_rate == Decimal("0.18") for c in kb.categories.values()) == 13


def test_supplier_status_counts(kb):
    assert kb.status_counts() == {"APPROVED": 33, "BLACKLISTED": 3, "PROBATION": 4}
    assert kb.suppliers["orbit-electronics"].status is SupplierStatus.BLACKLISTED
    assert kb.suppliers["lumen-workspace"].status is SupplierStatus.BLACKLISTED
    assert kb.suppliers["greenleaf-facility-care"].status is SupplierStatus.BLACKLISTED
    assert kb.suppliers["banyan-guarding"].status is SupplierStatus.PROBATION
    assert kb.suppliers["jade-express"].status is SupplierStatus.PROBATION
    assert kb.suppliers["vertex-mobile"].status is SupplierStatus.PROBATION
    assert kb.suppliers["zephyr-saas"].status is SupplierStatus.PROBATION


def test_supplier_overrides(kb):
    assert kb.suppliers["arvind-office-supplies"].currency_rates == {
        "GBP": Decimal("104.5")
    }
    assert kb.suppliers["aster-cleaning-co"].currency_rates == {"USD": Decimal("84")}
    assert kb.suppliers["falcon-security-services"].currency_rates == {
        "GBP": Decimal("105.5")
    }
    assert kb.suppliers["kestrel-learning"].currency_rates == {"EUR": Decimal("90.5")}
    assert kb.suppliers["helix-crm"].category_caps == {"catering": Decimal("400")}
    assert kb.suppliers["ivory-events-catering"].category_caps == {
        "headsets": Decimal("4400")
    }
    assert kb.suppliers["jupiter-devices"].category_caps == {
        "monitors": Decimal("17600")
    }
    assert kb.suppliers["kite-electricals"].category_caps == {
        "office-chairs": Decimal("11400")
    }
    assert kb.suppliers["monsoon-foods"].category_caps == {
        "headsets": Decimal("4500")
    }
    assert kb.suppliers["xenon-displays"].category_caps == {
        "led-lighting": Decimal("2300")
    }
    assert kb.contract_override_counts() == {
        "currency_rate_suppliers": 4,
        "price_cap_suppliers": 6,
    }


def test_amendments(kb):
    by_id = {a.amendment_id: a for a in kb.amendments}
    assert by_id["AMD-01"].effective_from.isoformat() == "2026-09-22"
    assert by_id["AMD-01"].field is AmendmentField.WALKAWAY
    assert by_id["AMD-01"].amount == Decimal("210")
    assert by_id["AMD-04"].field is AmendmentField.TARGET
    assert by_id["AMD-04"].amount == Decimal("270")
    assert by_id["AMD-06"].field is AmendmentField.APPROVAL_LIMIT
    assert by_id["AMD-06"].amount == Decimal("320000")
    assert by_id["AMD-07"].effective_from.isoformat() == "2026-12-05"
    assert by_id["AMD-08"].effective_from.isoformat() == "2026-12-04"
    assert {a.category_slug for a in kb.amendments} == {
        "courier",
        "cloud-servers",
        "mobile-phones",
        "catering",
        "printer-paper",
        "headsets",
        "led-lighting",
        "monitors",
    }


def test_precedents(kb):
    ids = {p.precedent_id for p in kb.precedents}
    assert ids == {f"P-0{n}" for n in range(1, 9)}
    assert all(p.body for p in kb.precedents)
    assert all(p.source_path.endswith(".md") for p in kb.precedents)


def test_supplier_lookup_is_controlled(kb):
    assert kb.resolve_supplier("Garnet Print & Paper") is not None
    assert kb.resolve_supplier("garnet print & paper") is not None
    assert kb.resolve_supplier("Garnet") is None
    assert kb.resolve_supplier("Print & Paper") is None
    assert kb.resolve_supplier("Unknown Vendor") is None
