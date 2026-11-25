"""Policy Agent: resolve the effective category policy for a thread date."""

from __future__ import annotations

from procurement_desk.exceptions import PolicyResolutionError
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import (
    AmendmentField,
    AppliedAmendment,
    ResolvedPolicy,
    ThreadRecord,
)

POLICY_VERSION = "1.0"


class PolicyAgent:
    """Resolves a category's base values plus all applicable dated amendments.

    The agent never applies supplier contract caps; that is the Supplier Agent's
    responsibility.  Keeping the two layers separate makes override precedence
    auditable.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def resolve(self, thread: ThreadRecord) -> ResolvedPolicy:
        category = self.kb.resolve_category(thread.category)
        if category is None:
            raise PolicyResolutionError(f"unknown category: {thread.category!r}")

        applicable = [
            amendment
            for amendment in self.kb.amendments_for(category.slug)
            if amendment.effective_from <= thread.date
        ]
        # amendments_for already sorts by effective date then amendment ID.
        target = category.target
        walkaway = category.walkaway
        approval_limit = category.approval_limit
        applied: list[AppliedAmendment] = []
        warnings: list[str] = []
        provenance = [
            f"category:{category.source_path}",
            "amendment rule: effective_from <= thread date (inclusive)",
        ]

        for amendment in applicable:
            if amendment.field == AmendmentField.TARGET:
                target = amendment.amount
            elif amendment.field == AmendmentField.WALKAWAY:
                walkaway = amendment.amount
            elif amendment.field == AmendmentField.APPROVAL_LIMIT:
                approval_limit = amendment.amount
            else:  # pragma: no cover - enum exhaustiveness
                raise PolicyResolutionError(
                    f"unsupported amendment field {amendment.field}"
                )
            applied.append(
                AppliedAmendment(
                    amendment_id=amendment.amendment_id,
                    field=amendment.field,
                    amount=amendment.amount,
                    effective_from=amendment.effective_from,
                    source_path=amendment.source_path,
                )
            )
            provenance.append(
                f"amendment:{amendment.amendment_id}@{amendment.effective_from.isoformat()}"
                f" field={amendment.field.value} value={amendment.amount}"
            )

        if target > walkaway:
            warnings.append(
                f"effective target {target} exceeds effective walk-away {walkaway}; "
                "source documents were preserved rather than silently repaired"
            )
        if category.rounds < 2:
            raise PolicyResolutionError(
                f"category {category.slug} has invalid R={category.rounds}"
            )

        return ResolvedPolicy(
            category_slug=category.slug,
            category_name=category.name,
            thread_date=thread.date,
            normalized_unit=category.normalized_unit,
            normalized_period=category.normalized_period,
            gst_rate=category.gst_rate,
            target=target,
            walkaway=walkaway,
            rounds=category.rounds,
            beta=category.beta,
            approval_limit=approval_limit,
            pack_size=category.pack_size,
            sub_unit_name=category.sub_unit_name,
            sub_unit_factor=category.sub_unit_factor,
            base_target=category.target,
            base_walkaway=category.walkaway,
            base_approval_limit=category.approval_limit,
            applied_amendments=applied,
            category_source=category.source_path,
            provenance=provenance,
            warnings=warnings,
        )
