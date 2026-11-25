"""Decision Agent: pure deterministic implementation of the playbook procedure."""

from __future__ import annotations

from decimal import Decimal

from procurement_desk.models import (
    Action,
    Decision,
    PricingAnalysis,
    ReasonCode,
    ResolvedPolicy,
    SecurityAnalysis,
    SupplierAnalysis,
    SupplierStatus,
    ThreadAnalysis,
    ThreadRecord,
)
from procurement_desk.pricing.concessions import (
    acceptable_price,
    approval_amount,
    exceeds_approval_limit,
)
from procurement_desk.pricing.money import decimal_to_plain, round_half_up_int


class DecisionAgent:
    """Apply the official first-match-wins ordering; no LLM is involved."""

    def decide(
        self,
        *,
        thread: ThreadRecord,
        analysis: ThreadAnalysis,
        policy: ResolvedPolicy,
        supplier: SupplierAnalysis,
        security: SecurityAnalysis,
        pricing: PricingAnalysis | None,
    ) -> Decision:
        trace: list[str] = []

        # Rule 1: missing information (highest priority).  Pricing may be absent
        # when the orchestrator took the documented early-terminal route.
        if analysis.missing_information or (
            pricing is not None and pricing.missing_information
        ):
            reason = (
                analysis.missing_reason
                or (pricing.missing_reason if pricing is not None else None)
                or "no_usable_price"
            )
            trace.append(f"rule 1 fired: missing information ({reason})")
            return self._terminal(
                action=Action.ESCALATE,
                reason=ReasonCode.MISSING_INFO,
                trace=trace,
                evidence=list(analysis.evidence)
                + (list(pricing.evidence) if pricing is not None else []),
                values={"missing_reason": reason},
            )
        trace.append("rule 1 not applicable: usable price exists")

        # Rule 2: blacklisted supplier.
        if supplier.status is SupplierStatus.BLACKLISTED:
            trace.append("rule 2 fired: supplier is blacklisted")
            return self._terminal(
                action=Action.REJECT,
                reason=ReasonCode.BLACKLISTED_SUPPLIER,
                trace=trace,
                evidence=[f"supplier status={supplier.status.value}", supplier.source_path],
                values={"supplier_status": supplier.status.value},
            )
        trace.append("rule 2 not applicable: supplier is not blacklisted")

        # Rule 3: prompt injection anywhere in the thread.
        if security.prompt_injection_detected:
            trace.append("rule 3 fired: prompt injection detected")
            return self._terminal(
                action=Action.ESCALATE,
                reason=ReasonCode.PROMPT_INJECTION,
                trace=trace,
                evidence=[finding.matched_text for finding in security.injection_findings],
                values={"injection_findings": str(len(security.injection_findings))},
            )
        trace.append("rule 3 not applicable: no prompt injection")

        # Rule 4: banned contractual term in the latest supplier message.
        if security.banned_term_detected:
            trace.append("rule 4 fired: banned contractual term detected")
            return self._terminal(
                action=Action.ESCALATE,
                reason=ReasonCode.BANNED_TERM,
                trace=trace,
                evidence=[
                    finding.matched_text for finding in security.banned_term_findings
                ],
                values={
                    "banned_term_types": ",".join(
                        sorted({f.rule_id for f in security.banned_term_findings})
                    )
                },
            )
        trace.append("rule 4 not applicable: no banned contractual term")

        # Rule 5: price decision, including probation threshold.
        if pricing is None or pricing.normalized_price is None:
            trace.append("rule 5 cannot run: normalized price unavailable")
            return self._terminal(
                action=Action.ESCALATE,
                reason=ReasonCode.MISSING_INFO,
                trace=trace,
                evidence=list(analysis.evidence),
                values={"missing_reason": "normalized_price_unavailable"},
            )
        normalized_price = pricing.normalized_price
        effective_walkaway = (
            supplier.category_cap
            if supplier.category_cap_applied and supplier.category_cap is not None
            else policy.walkaway
        )
        probation = supplier.status is SupplierStatus.PROBATION
        try:
            level = acceptable_price(
                target=policy.target,
                walkaway=effective_walkaway,
                rounds=policy.rounds,
                round_number=thread.round,
                beta=policy.beta,
                probation=probation,
            )
        except Exception as exc:
            # The graph/audit layer turns this into a controlled fallback rather
            # than inventing a decision.
            trace.append(f"rule 5 could not compute L(r): {exc}")
            raise

        values = {
            "normalized_price": decimal_to_plain(normalized_price) or "0",
            "target": decimal_to_plain(policy.target) or "0",
            "walkaway": decimal_to_plain(effective_walkaway) or "0",
            "acceptable_level": decimal_to_plain(level) or "0",
            "rounds": str(policy.rounds),
            "round": str(thread.round),
            "beta": decimal_to_plain(policy.beta) or "0",
            "probation": str(probation).lower(),
        }
        trace.append(
            f"rule 5: p={values['normalized_price']} L(r)={values['acceptable_level']} "
            f"(target={values['target']}, walkaway={values['walkaway']}, "
            f"round={thread.round}/{policy.rounds}, probation={probation})"
        )

        if normalized_price <= level:
            trace.append("rule 5: price is acceptable; proceeding to approval limit")
            approval = approval_amount(normalized_price, thread.quantity)
            values["approval_amount"] = decimal_to_plain(approval) or "0"
            values["approval_limit"] = decimal_to_plain(policy.approval_limit) or "0"
            values["quantity"] = str(thread.quantity)
            # Rule 6: approval limit.
            if exceeds_approval_limit(approval, policy.approval_limit):
                trace.append("rule 6 fired: approval amount exceeds limit")
                return self._terminal(
                    action=Action.ESCALATE,
                    reason=ReasonCode.OVER_APPROVAL_LIMIT,
                    trace=trace,
                    evidence=[
                        f"p × quantity = {values['approval_amount']}",
                        f"approval limit = {values['approval_limit']}",
                    ],
                    values=values,
                )
            trace.append("rule 6 not applicable: approval amount within limit")
            trace.append("final: ACCEPT")
            return Decision(
                action=Action.ACCEPT,
                reason=ReasonCode.ACCEPTABLE_PRICE,
                label="ACCEPT:ACCEPTABLE_PRICE:",
                precedence_trace=trace,
                evidence=[
                    f"p={values['normalized_price']} <= L(r)={values['acceptable_level']}",
                    f"approval={values['approval_amount']} <= limit={values['approval_limit']}",
                ],
                values=values,
            )

        # p > L(r)
        if thread.round >= policy.rounds:
            trace.append("rule 5 fired: p > L(r) on the final category round")
            return self._terminal(
                action=Action.REJECT,
                reason=ReasonCode.ABOVE_WALKAWAY,
                trace=trace,
                evidence=[
                    f"p={values['normalized_price']} > final L(r)={values['acceptable_level']}",
                ],
                values=values,
            )

        counter = round_half_up_int(level)
        values["counter_price"] = str(counter)
        trace.append(
            f"rule 5 fired: p > L(r) before final round; counter at {counter}"
        )
        return Decision(
            action=Action.COUNTER,
            reason=ReasonCode.COUNTER_OFFER,
            counter_price=counter,
            label=f"COUNTER:COUNTER_OFFER:{counter}",
            precedence_trace=trace,
            evidence=[
                f"p={values['normalized_price']} > L(r)={values['acceptable_level']}",
                f"counter price rounded ROUND_HALF_UP to {counter}",
            ],
            values=values,
        )

    @staticmethod
    def _terminal(
        *,
        action: Action,
        reason: ReasonCode,
        trace: list[str],
        evidence: list[str],
        values: dict[str, str],
    ) -> Decision:
        return Decision(
            action=action,
            reason=reason,
            label=f"{action.value}:{reason.value}:",
            precedence_trace=trace,
            evidence=[item for item in evidence if item],
            values=values,
        )
