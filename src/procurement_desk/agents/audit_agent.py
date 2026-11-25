"""Audit Agent: independently recompute critical values and validate the label.

The audit does not trust the Decision Agent's state.  It resolves the policy and
supplier again from the raw knowledge base, re-extracts the supplier's offer from
the original thread, re-prices it, re-detects security findings, and applies a
separate decision-invariant check.
"""

from __future__ import annotations

import re
from decimal import Decimal

from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.agents.thread_analyst import ThreadAnalyst
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import (
    Action,
    AmendmentField,
    AppliedAmendment,
    AuditCheck,
    AuditResult,
    Decision,
    ExtractionMethod,
    PricingAnalysis,
    ReasonCode,
    ResolvedPolicy,
    SecurityAnalysis,
    SupplierAnalysis,
    SupplierStatus,
    ThreadAnalysis,
    ThreadRecord,
)
from procurement_desk.llm.provider import validate_llm_offer
from procurement_desk.pricing.concessions import (
    acceptable_price,
    approval_amount,
    exceeds_approval_limit,
)
from procurement_desk.pricing.audit_recalc import independent_price_with_quantity
from procurement_desk.pricing.money import decimal_to_plain, round_half_up_int
from procurement_desk.security.banned_terms import detect_banned_terms
from procurement_desk.security.injection import detect_injection

LABEL_RE = re.compile(
    r"^(?:"
    r"ACCEPT:ACCEPTABLE_PRICE:|"
    r"REJECT:BLACKLISTED_SUPPLIER:|"
    r"REJECT:ABOVE_WALKAWAY:|"
    r"ESCALATE:MISSING_INFO:|"
    r"ESCALATE:PROMPT_INJECTION:|"
    r"ESCALATE:BANNED_TERM:|"
    r"ESCALATE:OVER_APPROVAL_LIMIT:|"
    r"COUNTER:COUNTER_OFFER:\d+"
    r")$"
)


class AuditAgent:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def audit(
        self,
        *,
        thread: ThreadRecord,
        analysis: ThreadAnalysis,
        policy: ResolvedPolicy,
        supplier: SupplierAnalysis,
        security: SecurityAnalysis,
        pricing: PricingAnalysis | None,
        decision: Decision,
    ) -> AuditResult:
        checks: list[AuditCheck] = []
        failures: list[str] = []

        def check(
            name: str,
            passed: bool,
            *,
            detail: str | None = None,
            expected: object | None = None,
            actual: object | None = None,
        ) -> None:
            checks.append(
                AuditCheck(
                    name=name,
                    passed=passed,
                    detail=detail,
                    expected=None if expected is None else str(expected),
                    actual=None if actual is None else str(actual),
                )
            )
            if not passed:
                failures.append(name if not detail else f"{name}: {detail}")

        # 1. Identity and basic thread invariants.
        check(
            "thread_id_consistency",
            analysis.thread_id == thread.thread_id
            and (pricing is None or pricing.thread_id == thread.thread_id)
            and decision.label.startswith(("ACCEPT", "COUNTER", "REJECT", "ESCALATE")),
            expected=thread.thread_id,
            actual=f"{analysis.thread_id}/"
            + (pricing.thread_id if pricing is not None else "pricing-skipped"),
        )
        check(
            "quantity_and_round",
            thread.quantity > 0 and 1 <= thread.round <= policy.rounds,
            expected=f"quantity>0 and 1<=round<={policy.rounds}",
            actual=f"quantity={thread.quantity}, round={thread.round}",
        )

        # 2. Independent policy resolution.
        expected_policy = self._resolve_policy_independently(thread)
        check(
            "category_resolution",
            expected_policy.category_slug == policy.category_slug == thread.category,
            expected=expected_policy.category_slug,
            actual=policy.category_slug,
        )
        check(
            "effective_policy_values",
            self._policy_values_equal(expected_policy, policy),
            detail="base + dated amendments must reproduce effective values",
            expected=self._policy_signature(expected_policy),
            actual=self._policy_signature(policy),
        )
        check(
            "amendment_resolution",
            [(a.amendment_id, a.field.value, a.amount) for a in expected_policy.applied_amendments]
            == [(a.amendment_id, a.field.value, a.amount) for a in policy.applied_amendments],
            detail="effective-date ordering and replacement",
            expected=[a.amendment_id for a in expected_policy.applied_amendments],
            actual=[a.amendment_id for a in policy.applied_amendments],
        )

        # 3. Independent supplier resolution.
        expected_supplier = self._resolve_supplier_independently(thread)
        check(
            "supplier_resolution",
            expected_supplier.display_name == supplier.display_name == thread.supplier,
            expected=expected_supplier.display_name,
            actual=supplier.display_name,
        )
        check(
            "supplier_status_and_overrides",
            expected_supplier.status == supplier.status
            and expected_supplier.category_cap == supplier.category_cap
            and expected_supplier.currency_rates == supplier.currency_rates,
            detail="status and category/currency overrides must be isolated",
            expected=(
                expected_supplier.status.value,
                expected_supplier.category_cap,
                expected_supplier.currency_rates,
            ),
            actual=(supplier.status.value, supplier.category_cap, supplier.currency_rates),
        )

        # 4. Independent offer re-extraction.
        expected_analysis = ThreadAnalyst(self.kb).analyze(thread)
        adopted_analysis = expected_analysis
        llm_offer_used = False
        if (
            analysis.extraction_method is ExtractionMethod.LLM
            and analysis.offer.has_usable_price
            and not expected_analysis.offer.has_usable_price
        ):
            grounded, reason = validate_llm_offer(
                analysis.offer, analysis.latest_supplier_message
            )
            check(
                "llm_extraction_grounding",
                grounded,
                detail=reason,
                expected="grounded in the latest supplier text",
                actual="grounded" if grounded else "not grounded",
            )
            if grounded:
                adopted_analysis = analysis
                llm_offer_used = True
        else:
            check(
                "llm_extraction_grounding",
                True,
                detail="not applicable: deterministic extraction was used",
            )
        check(
            "latest_supplier_message",
            self._normalise_ws(expected_analysis.latest_supplier_message)
            == self._normalise_ws(analysis.latest_supplier_message),
            detail="the latest supplier segment must be identified correctly",
        )
        if llm_offer_used:
            check(
                "latest_offer_facts",
                True,
                detail="LLM facts accepted only after source-grounding check",
            )
        else:
            offer_equal, offer_detail = self._offer_equal(expected_analysis, analysis)
            check(
                "latest_offer_facts",
                offer_equal,
                detail=offer_detail,
                expected=expected_analysis.offer.model_dump(mode="json"),
                actual=analysis.offer.model_dump(mode="json"),
            )
        check(
            "missing_information",
            adopted_analysis.missing_information == analysis.missing_information
            and adopted_analysis.missing_reason == analysis.missing_reason,
            expected=(
                f"{adopted_analysis.missing_information}/"
                f"{adopted_analysis.missing_reason}"
            ),
            actual=f"{analysis.missing_information}/{analysis.missing_reason}",
        )

        # 5. Independent security detection.
        expected_injection = detect_injection(expected_analysis.messages)
        expected_banned = detect_banned_terms(expected_analysis.latest_supplier_message)
        check(
            "prompt_injection_scope",
            bool(expected_injection) == security.prompt_injection_detected,
            detail="injection is checked anywhere in the full thread",
            expected=bool(expected_injection),
            actual=security.prompt_injection_detected,
        )
        check(
            "banned_term_scope",
            bool(expected_banned) == security.banned_term_detected,
            detail="banned terms are checked only in the latest supplier message",
            expected=bool(expected_banned),
            actual=security.banned_term_detected,
        )

        # 6. Independent pricing.
        expected_pricing = PricingAgent().normalize(
            thread, adopted_analysis, expected_policy, expected_supplier
        )
        expected_is_early_terminal = (
            adopted_analysis.missing_information
            or expected_supplier.status is SupplierStatus.BLACKLISTED
            or bool(expected_injection)
            or bool(expected_banned)
        )
        if pricing is None:
            check(
                "pricing_execution",
                expected_is_early_terminal,
                detail=(
                    "pricing may be skipped only when an earlier precedence rule fires"
                ),
                expected="early terminal" if expected_is_early_terminal else "pricing required",
                actual="pricing absent",
            )
            check(
                "exchange_rate_resolution",
                True,
                detail="not applicable: early terminal path skipped pricing",
            )
            check(
                "gst_and_period_normalization",
                True,
                detail="not applicable: early terminal path skipped pricing",
            )
            check(
                "normalized_price_recalculation",
                True,
                detail="not applicable: early terminal path skipped pricing",
            )
            check(
                "approval_amount_recalculation",
                True,
                detail="not applicable: early terminal path skipped pricing",
            )
        else:
            check(
                "exchange_rate_resolution",
                pricing.exchange_rate == expected_pricing.exchange_rate,
                expected=expected_pricing.exchange_rate,
                actual=pricing.exchange_rate,
            )
            check(
                "gst_and_period_normalization",
                expected_pricing.missing_information
                or (
                    pricing.gst_rate == expected_policy.gst_rate
                    and pricing.gst_inclusive == adopted_analysis.offer.gst_inclusive
                    and pricing.billing_period_offered
                    == adopted_analysis.offer.billing_period
                ),
                expected=(
                    expected_policy.gst_rate,
                    adopted_analysis.offer.gst_inclusive,
                    adopted_analysis.offer.billing_period,
                ),
                actual=(
                    pricing.gst_rate,
                    pricing.gst_inclusive,
                    pricing.billing_period_offered,
                ),
            )
            check(
                "normalized_price_recalculation",
                pricing.normalized_price == expected_pricing.normalized_price,
                detail="re-run deterministic Decimal normalization",
                expected=decimal_to_plain(expected_pricing.normalized_price),
                actual=decimal_to_plain(pricing.normalized_price),
            )
            check(
                "approval_amount_recalculation",
                pricing.approval_amount == expected_pricing.approval_amount,
                expected=decimal_to_plain(expected_pricing.approval_amount),
                actual=decimal_to_plain(pricing.approval_amount),
            )
            if not expected_pricing.missing_information:
                independent = independent_price_with_quantity(
                    adopted_analysis.offer,
                    expected_policy,
                    expected_supplier,
                    quantity=thread.quantity,
                )
                expectation = (
                    (decimal_to_plain(independent[0]) if independent else None),
                    (decimal_to_plain(independent[1]) if independent else None),
                )
                check(
                    "independent_price_arithmetic",
                    independent is not None
                    and pricing.normalized_price == independent[0]
                    and pricing.approval_amount == independent[1],
                    detail=(
                        "separate arithmetic implementation, not PricingAgent"
                    ),
                    expected=expectation,
                    actual=(
                        decimal_to_plain(pricing.normalized_price),
                        decimal_to_plain(pricing.approval_amount),
                    ),
                )

        # 7. Independent decision invariants.
        expected_action, expected_reason, expected_counter, expected_label = (
            self._audit_expected_decision(
                thread=thread,
                expected_analysis=adopted_analysis,
                expected_policy=expected_policy,
                expected_supplier=expected_supplier,
                injection=bool(expected_injection),
                banned=bool(expected_banned),
                expected_pricing=expected_pricing,
            )
        )
        check(
            "decision_precedence",
            (decision.action, decision.reason, decision.counter_price)
            == (expected_action, expected_reason, expected_counter),
            detail="missing → blacklist → injection → banned → price → approval",
            expected=(expected_action.value, expected_reason.value, expected_counter),
            actual=(decision.action.value, decision.reason.value, decision.counter_price),
        )
        check(
            "counter_rounding",
            expected_action != Action.COUNTER
            or decision.counter_price
            == round_half_up_int(
                self._expected_level(
                    thread, expected_policy, expected_supplier, adopted_analysis
                )
            ),
            detail="ROUND_HALF_UP with exact halves up",
            expected=(
                round_half_up_int(
                    self._expected_level(
                        thread, expected_policy, expected_supplier, adopted_analysis
                    )
                )
                if expected_action == Action.COUNTER
                else None
            ),
            actual=decision.counter_price,
        )
        check(
            "final_label_equals_recalculated",
            decision.label == expected_label,
            expected=expected_label,
            actual=decision.label,
        )
        check(
            "label_format",
            bool(LABEL_RE.fullmatch(decision.label)),
            detail="ACTION:REASON: with integer counter only for COUNTER",
            actual=decision.label,
        )
        check(
            "thread_id_in_label_context",
            decision.label and decision.label.split(":", 2)[0] in {
                "ACCEPT",
                "COUNTER",
                "REJECT",
                "ESCALATE",
            },
            actual=decision.label.split(":", 2)[0] if decision.label else None,
        )

        return AuditResult(
            passed=not failures,
            checks=checks,
            failures=failures,
            recalculated_label=expected_label,
            recalculated_price=expected_pricing.normalized_price,
        )

    def _resolve_policy_independently(self, thread: ThreadRecord) -> ResolvedPolicy:
        category = self.kb.resolve_category(thread.category)
        if category is None:
            raise ValueError(f"audit: unknown category {thread.category!r}")
        target = category.target
        walkaway = category.walkaway
        approval = category.approval_limit
        applied = []
        applicable = [
            a
            for a in self.kb.amendments
            if a.category_slug == category.slug and a.effective_from <= thread.date
        ]
        applicable.sort(key=lambda a: (a.effective_from, a.amendment_id))
        for amendment in applicable:
            if amendment.field is AmendmentField.TARGET:
                target = amendment.amount
            elif amendment.field is AmendmentField.WALKAWAY:
                walkaway = amendment.amount
            elif amendment.field is AmendmentField.APPROVAL_LIMIT:
                approval = amendment.amount
            applied.append(
                AppliedAmendment(
                    amendment_id=amendment.amendment_id,
                    field=amendment.field,
                    amount=amendment.amount,
                    effective_from=amendment.effective_from,
                    source_path=amendment.source_path,
                )
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
            approval_limit=approval,
            pack_size=category.pack_size,
            sub_unit_name=category.sub_unit_name,
            sub_unit_factor=category.sub_unit_factor,
            base_target=category.target,
            base_walkaway=category.walkaway,
            base_approval_limit=category.approval_limit,
            applied_amendments=applied,
            category_source=category.source_path,
            provenance=["audit: independent effective-date resolution"],
        )

    def _resolve_supplier_independently(self, thread: ThreadRecord) -> SupplierAnalysis:
        supplier = self.kb.resolve_supplier(thread.supplier)
        if supplier is None:
            raise ValueError(f"audit: unknown supplier {thread.supplier!r}")
        return SupplierAnalysis(
            key=supplier.key,
            display_name=supplier.display_name,
            status=supplier.status,
            category_cap=supplier.category_caps.get(thread.category),
            category_cap_applied=thread.category in supplier.category_caps,
            currency_rates=dict(supplier.currency_rates),
            applied_overrides=[],
            source_path=supplier.source_path,
        )

    def _audit_expected_decision(
        self,
        *,
        thread: ThreadRecord,
        expected_analysis: ThreadAnalysis,
        expected_policy: ResolvedPolicy,
        expected_supplier: SupplierAnalysis,
        injection: bool,
        banned: bool,
        expected_pricing: PricingAnalysis,
    ) -> tuple[Action, ReasonCode, int | None, str]:
        if expected_analysis.missing_information or expected_pricing.missing_information:
            return (
                Action.ESCALATE,
                ReasonCode.MISSING_INFO,
                None,
                "ESCALATE:MISSING_INFO:",
            )
        if expected_supplier.status is SupplierStatus.BLACKLISTED:
            return (
                Action.REJECT,
                ReasonCode.BLACKLISTED_SUPPLIER,
                None,
                "REJECT:BLACKLISTED_SUPPLIER:",
            )
        if injection:
            return (
                Action.ESCALATE,
                ReasonCode.PROMPT_INJECTION,
                None,
                "ESCALATE:PROMPT_INJECTION:",
            )
        if banned:
            return (
                Action.ESCALATE,
                ReasonCode.BANNED_TERM,
                None,
                "ESCALATE:BANNED_TERM:",
            )
        price = expected_pricing.normalized_price
        if price is None:
            return (
                Action.ESCALATE,
                ReasonCode.MISSING_INFO,
                None,
                "ESCALATE:MISSING_INFO:",
            )
        level = self._expected_level(
            thread, expected_policy, expected_supplier, expected_analysis
        )
        if price <= level:
            amount = approval_amount(price, thread.quantity)
            if exceeds_approval_limit(amount, expected_policy.approval_limit):
                return (
                    Action.ESCALATE,
                    ReasonCode.OVER_APPROVAL_LIMIT,
                    None,
                    "ESCALATE:OVER_APPROVAL_LIMIT:",
                )
            return (
                Action.ACCEPT,
                ReasonCode.ACCEPTABLE_PRICE,
                None,
                "ACCEPT:ACCEPTABLE_PRICE:",
            )
        if thread.round >= expected_policy.rounds:
            return (
                Action.REJECT,
                ReasonCode.ABOVE_WALKAWAY,
                None,
                "REJECT:ABOVE_WALKAWAY:",
            )
        counter = round_half_up_int(level)
        return (
            Action.COUNTER,
            ReasonCode.COUNTER_OFFER,
            counter,
            f"COUNTER:COUNTER_OFFER:{counter}",
        )

    def _expected_level(
        self,
        thread: ThreadRecord,
        policy: ResolvedPolicy,
        supplier: SupplierAnalysis,
        analysis: ThreadAnalysis,
    ) -> Decimal:
        walkaway = (
            supplier.category_cap
            if supplier.category_cap_applied and supplier.category_cap is not None
            else policy.walkaway
        )
        return acceptable_price(
            target=policy.target,
            walkaway=walkaway,
            rounds=policy.rounds,
            round_number=thread.round,
            beta=policy.beta,
            probation=supplier.status is SupplierStatus.PROBATION,
        )

    @staticmethod
    def _policy_values_equal(a: ResolvedPolicy, b: ResolvedPolicy) -> bool:
        fields = (
            "category_slug",
            "normalized_unit",
            "normalized_period",
            "gst_rate",
            "target",
            "walkaway",
            "rounds",
            "beta",
            "approval_limit",
            "pack_size",
            "sub_unit_name",
            "sub_unit_factor",
        )
        return all(getattr(a, field) == getattr(b, field) for field in fields)

    @staticmethod
    def _policy_signature(policy: ResolvedPolicy) -> tuple:
        return (
            policy.target,
            policy.walkaway,
            policy.approval_limit,
            policy.rounds,
            policy.beta,
            policy.gst_rate,
            policy.normalized_period,
        )

    def _offer_equal(self, a: ThreadAnalysis, b: ThreadAnalysis) -> tuple[bool, str]:
        fields = (
            "has_usable_price",
            "currency",
            "quoted_amount",
            "amount_basis",
            "total_quantity",
            "pack_size",
            "per_n",
            "sub_unit_name",
            "billing_period",
            "gst_inclusive",
            "list_discount_percent",
            "volume_discount_percent",
            "volume_threshold",
            "free_units",
            "paid_units",
            "tier_threshold",
            "tier_branch",
            "is_correction",
            "is_range",
            "range_used_high",
            "unsupported_currency",
            "missing_reason",
        )
        differences = [
            field
            for field in fields
            if getattr(a.offer, field) != getattr(b.offer, field)
        ]
        if a.offer.previous_quote_discount_percent is not None or b.offer.previous_quote_discount_percent is not None:
            for field in (
                "previous_quote_discount_percent",
                "previous_quote_amount",
                "previous_quote_currency",
                "previous_quote_billing_period",
            ):
                if getattr(a.offer, field) != getattr(b.offer, field):
                    differences.append(field)
        detail = "offer facts match" if not differences else f"differing fields: {differences}"
        return not differences, detail

    @staticmethod
    def _normalise_ws(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
