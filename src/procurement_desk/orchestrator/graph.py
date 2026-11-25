"""LangGraph orchestration for the multi-agent procurement desk."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph

from procurement_desk.agents.audit_agent import AuditAgent
from procurement_desk.agents.decision_agent import DecisionAgent
from procurement_desk.agents.policy_agent import PolicyAgent
from procurement_desk.agents.pricing_agent import PricingAgent
from procurement_desk.agents.security_agent import SecurityAgent
from procurement_desk.agents.supplier_agent import SupplierAgent
from procurement_desk.agents.thread_analyst import ThreadAnalyst
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import (
    Action,
    AuditResult,
    Decision,
    ExecutionMetadata,
    PricingAnalysis,
    ReasonCode,
    SupplierStatus,
    ThreadRecord,
)
from procurement_desk.orchestrator.state import GraphState

GRAPH_VERSION = "1.0"
EXTRACTOR_VERSION = "1.0"
POLICY_VERSION = "1.0"
SAFE_FALLBACK_LABEL = "ESCALATE:MISSING_INFO:"
FALLBACK_LABEL_RE = re.compile(
    r"^(?P<action>ACCEPT|COUNTER|REJECT|ESCALATE):(?P<reason>[A-Z_]+):(?P<counter>\d*)$"
)


class ProcurementGraph:
    """Coordinate agents; all business decisions remain in their own agents."""

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        llm_provider=None,
        thread_analyst: ThreadAnalyst | None = None,
        run_id: str = "run",
        llm_mode: str = "none",
    ) -> None:
        self.kb = kb
        self.run_id = run_id
        self.llm_mode = llm_mode
        self.analyst = thread_analyst or ThreadAnalyst(kb, llm_provider=llm_provider)
        self.policy_agent = PolicyAgent(kb)
        self.supplier_agent = SupplierAgent(kb)
        self.security_agent = SecurityAgent()
        self.pricing_agent = PricingAgent()
        self.decision_agent = DecisionAgent()
        self.audit_agent = AuditAgent(kb)
        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def initial_state(self, thread: ThreadRecord) -> GraphState:
        started = datetime.now(timezone.utc)
        return GraphState(
            thread=thread,
            errors=[],
            warnings=[],
            retry_count=0,
            recovery_attempted=False,
            fallback_used=False,
            execution=ExecutionMetadata(
                run_id=self.run_id,
                started_at=started,
                llm_mode=self.llm_mode,
                extractor_version=EXTRACTOR_VERSION,
                policy_version=POLICY_VERSION,
                graph_version=GRAPH_VERSION,
            ),
        )

    def run(self, thread: ThreadRecord) -> GraphState:
        return self.graph.invoke(self.initial_state(thread))

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def _build_graph(self):
        workflow = StateGraph(GraphState)
        workflow.add_node("analyze_thread", self._node_analyze_thread)
        workflow.add_node("resolve_policy", self._node_resolve_policy)
        workflow.add_node("resolve_supplier", self._node_resolve_supplier)
        workflow.add_node("security", self._node_security)
        workflow.add_node("price", self._node_price)
        workflow.add_node("decide", self._node_decide)
        workflow.add_node("audit", self._node_audit)
        workflow.add_node("recover", self._node_recover)
        workflow.add_node("fallback", self._node_fallback)
        workflow.add_node("finalize", self._node_finalize)

        workflow.add_edge(START, "analyze_thread")
        workflow.add_edge("analyze_thread", "resolve_policy")
        workflow.add_edge("resolve_policy", "resolve_supplier")
        workflow.add_edge("resolve_supplier", "security")
        workflow.add_conditional_edges(
            "security",
            self._route_after_security,
            {"decide": "decide", "price": "price"},
        )
        workflow.add_edge("price", "decide")
        workflow.add_edge("decide", "audit")
        workflow.add_conditional_edges(
            "audit",
            self._route_after_audit,
            {
                "finalize": "finalize",
                "recover": "recover",
                "fallback": "fallback",
            },
        )
        workflow.add_edge("recover", "audit")
        workflow.add_edge("fallback", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    def _node_analyze_thread(self, state: GraphState) -> dict[str, Any]:
        thread = state["thread"]
        try:
            analysis = self.analyst.analyze(thread)
            return {"analysis": analysis, "outcome_status": "ok"}
        except Exception as exc:  # pragma: no cover - supplied data resolves
            return self._append_error(state, f"thread_analyst: {exc}")

    def _node_resolve_policy(self, state: GraphState) -> dict[str, Any]:
        thread = state["thread"]
        try:
            policy = self.policy_agent.resolve(thread)
            return {"policy": policy}
        except Exception as exc:  # pragma: no cover
            return self._append_error(state, f"policy_agent: {exc}")

    def _node_resolve_supplier(self, state: GraphState) -> dict[str, Any]:
        thread = state["thread"]
        try:
            supplier = self.supplier_agent.resolve(thread)
            return {"supplier": supplier}
        except Exception as exc:  # pragma: no cover
            return self._append_error(state, f"supplier_agent: {exc}")

    def _node_security(self, state: GraphState) -> dict[str, Any]:
        try:
            security = self.security_agent.analyze(state["thread"], state["analysis"])
            return {"security": security}
        except Exception as exc:  # pragma: no cover
            return self._append_error(state, f"security_agent: {exc}")

    def _route_after_security(self, state: GraphState) -> str:
        if not all(key in state for key in ("analysis", "supplier", "security")):
            return "decide"
        analysis = state["analysis"]
        supplier = state["supplier"]
        security = state["security"]
        if analysis.missing_information:
            return "decide"
        if supplier.status is SupplierStatus.BLACKLISTED:
            return "decide"
        if security.prompt_injection_detected or security.banned_term_detected:
            return "decide"
        return "price"

    def _node_price(self, state: GraphState) -> dict[str, Any]:
        try:
            pricing = self.pricing_agent.normalize(
                state["thread"],
                state["analysis"],
                state["policy"],
                state["supplier"],
            )
            return {"pricing": pricing}
        except Exception as exc:
            # Keep the workflow alive with an explicit missing-information result.
            error = f"pricing_agent: {exc}"
            pricing = PricingAnalysis(
                thread_id=state["thread"].thread_id,
                quantity=state["thread"].quantity,
                normalized_price=None,
                missing_information=True,
                missing_reason="pricing_error",
                warnings=[error],
            )
            updated = self._append_error(state, error)
            updated["pricing"] = pricing
            return updated

    def _node_decide(self, state: GraphState) -> dict[str, Any]:
        required = ("analysis", "policy", "supplier", "security")
        if not all(key in state for key in required):
            decision = self._fallback_decision(
                "; ".join(state.get("errors", [])) or "workflow state incomplete"
            )
            return {"decision": decision, "fallback_used": True, "outcome_status": "fallback"}
        try:
            decision = self.decision_agent.decide(
                thread=state["thread"],
                analysis=state["analysis"],
                policy=state["policy"],
                supplier=state["supplier"],
                security=state["security"],
                pricing=state.get("pricing"),
            )
            return {"decision": decision}
        except Exception as exc:  # pragma: no cover
            updated = self._append_error(state, f"decision_agent: {exc}")
            updated["decision"] = self._fallback_decision(str(exc))
            updated["fallback_used"] = True
            updated["outcome_status"] = "fallback"
            return updated

    def _node_audit(self, state: GraphState) -> dict[str, Any]:
        if not state.get("decision"):
            audit = AuditResult(passed=False, failures=["missing decision"])
            return {"audit": audit}
        try:
            audit = self.audit_agent.audit(
                thread=state["thread"],
                analysis=state["analysis"],
                policy=state["policy"],
                supplier=state["supplier"],
                security=state["security"],
                pricing=state.get("pricing"),
                decision=state["decision"],
            )
        except Exception as exc:  # pragma: no cover
            audit = AuditResult(passed=False, failures=[f"audit_agent_error: {exc}"])
        if audit.passed:
            status = "recovered" if state.get("recovery_attempted") else "ok"
            return {"audit": audit, "outcome_status": status}
        updated = self._append_error(
            state, "audit failed: " + "; ".join(audit.failures)
        )
        updated["audit"] = audit
        return updated

    def _route_after_audit(self, state: GraphState) -> str:
        audit = state.get("audit")
        if audit is not None and audit.passed:
            return "finalize"
        if not state.get("recovery_attempted"):
            return "recover"
        return "fallback"

    def _node_recover(self, state: GraphState) -> dict[str, Any]:
        """Strict deterministic rerun from the original thread, never from the LLM."""
        thread = state["thread"]
        retry_count = int(state.get("retry_count", 0)) + 1
        try:
            analysis = ThreadAnalyst(self.kb).analyze(thread)
            policy = self.policy_agent.resolve(thread)
            supplier = self.supplier_agent.resolve(thread)
            security = self.security_agent.analyze(thread, analysis)
            pricing = self.pricing_agent.normalize(thread, analysis, policy, supplier)
            decision = self.decision_agent.decide(
                thread=thread,
                analysis=analysis,
                policy=policy,
                supplier=supplier,
                security=security,
                pricing=pricing,
            )
            return {
                "analysis": analysis,
                "policy": policy,
                "supplier": supplier,
                "security": security,
                "pricing": pricing,
                "decision": decision,
                "retry_count": retry_count,
                "recovery_attempted": True,
            }
        except Exception as exc:
            updated = self._append_error(state, f"deterministic_recovery: {exc}")
            updated["retry_count"] = retry_count
            updated["recovery_attempted"] = True
            return updated

    def _node_fallback(self, state: GraphState) -> dict[str, Any]:
        audit = state.get("audit")
        label = SAFE_FALLBACK_LABEL
        if audit is not None and audit.recalculated_label:
            candidate = audit.recalculated_label
            if FALLBACK_LABEL_RE.fullmatch(candidate):
                label = candidate
        existing_errors = state.get("errors", [])
        failures = "; ".join(audit.failures) if audit is not None else "unknown audit failure"
        errors = list(existing_errors) + [f"audit fallback used: {failures}"]
        return {
            "decision": self._decision_from_label(label, error=failures),
            "errors": errors,
            "fallback_used": True,
            "outcome_status": "fallback",
        }

    def _node_finalize(self, state: GraphState) -> dict[str, Any]:
        decision = state.get("decision")
        if decision is None:
            decision = self._fallback_decision("no decision produced")
        execution = state.get("execution") or ExecutionMetadata(
            run_id=self.run_id, started_at=datetime.now(timezone.utc)
        )
        duration_ms = (
            datetime.now(timezone.utc) - execution.started_at
        ).total_seconds() * 1000.0
        updated_execution = execution.model_copy(
            update={
                "duration_ms": round(duration_ms, 3),
                "recovery_attempted": bool(state.get("recovery_attempted")),
                "fallback_used": bool(state.get("fallback_used")),
            }
        )
        status = state.get("outcome_status") or (
            "fallback" if state.get("fallback_used") else "ok"
        )
        return {
            "decision": decision,
            "final_label": decision.label,
            "execution": updated_execution,
            "outcome_status": status,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _append_error(state: GraphState, message: str) -> dict[str, Any]:
        errors = list(state.get("errors", []))
        errors.append(message)
        return {"errors": errors}

    @staticmethod
    def _fallback_decision(error: str) -> Decision:
        return Decision(
            action=Action.ESCALATE,
            reason=ReasonCode.MISSING_INFO,
            label=SAFE_FALLBACK_LABEL,
            error=error,
            precedence_trace=["controlled fallback: safe missing-information escalation"],
            values={"fallback": "true"},
        )

    @staticmethod
    def _decision_from_label(label: str, *, error: str | None = None) -> Decision:
        match = FALLBACK_LABEL_RE.fullmatch(label)
        if not match:
            return ProcurementGraph._fallback_decision(error or "invalid fallback label")
        action = Action(match.group("action"))
        reason = ReasonCode(match.group("reason"))
        counter_text = match.group("counter")
        counter = int(counter_text) if counter_text else None
        if action is not Action.COUNTER:
            counter = None
        if action is Action.COUNTER and counter is None:
            return ProcurementGraph._fallback_decision(error or "invalid COUNTER fallback")
        return Decision(
            action=action,
            reason=reason,
            counter_price=counter,
            label=label,
            error=error,
            precedence_trace=["controlled fallback from independent audit recalculation"],
            values={"fallback": "true"},
        )
