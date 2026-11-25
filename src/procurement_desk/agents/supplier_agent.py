"""Supplier Agent: controlled identity, status, FX overrides, and price caps."""

from __future__ import annotations

from procurement_desk.exceptions import SupplierResolutionError
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import SupplierAnalysis, ThreadRecord


class SupplierAgent:
    """Resolve supplier-specific facts without conflating status and contracts."""

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def resolve(self, thread: ThreadRecord) -> SupplierAnalysis:
        supplier = self.kb.resolve_supplier(thread.supplier)
        if supplier is None:
            raise SupplierResolutionError(f"unknown supplier: {thread.supplier!r}")

        category_cap = supplier.category_caps.get(thread.category)
        applied: list[str] = []
        if category_cap is not None:
            applied.append(
                f"category_price_cap:{thread.category}={category_cap}"
            )
        for currency, rate in sorted(supplier.currency_rates.items()):
            applied.append(f"currency_contract_rate:{currency}={rate}")

        warnings: list[str] = []
        if supplier.status.value == "BLACKLISTED":
            warnings.append("supplier is blacklisted; status precedence applies")
        if supplier.category_caps and category_cap is None:
            warnings.append(
                "supplier has contract cap(s) for other categories only; not applied here"
            )
        if supplier.currency_rates:
            warnings.append(
                "supplier contract FX override applies only when the offer uses that currency"
            )

        return SupplierAnalysis(
            key=supplier.key,
            display_name=supplier.display_name,
            status=supplier.status,
            category_cap=category_cap,
            category_cap_applied=category_cap is not None,
            currency_rates=dict(supplier.currency_rates),
            applied_overrides=applied,
            source_path=supplier.source_path,
            warnings=warnings,
        )
