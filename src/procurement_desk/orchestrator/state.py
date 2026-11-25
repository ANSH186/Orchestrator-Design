"""Typed shared state for the LangGraph procurement workflow."""

from __future__ import annotations

from typing import Literal, TypedDict

from procurement_desk.models import (
    AuditResult,
    Decision,
    ExecutionMetadata,
    PricingAnalysis,
    ResolvedPolicy,
    SecurityAnalysis,
    SupplierAnalysis,
    ThreadAnalysis,
    ThreadRecord,
)


class GraphState(TypedDict, total=False):
    thread: ThreadRecord
    analysis: ThreadAnalysis
    policy: ResolvedPolicy
    supplier: SupplierAnalysis
    security: SecurityAnalysis
    pricing: PricingAnalysis
    decision: Decision
    audit: AuditResult
    errors: list[str]
    warnings: list[str]
    retry_count: int
    recovery_attempted: bool
    fallback_used: bool
    final_label: str
    outcome_status: Literal["ok", "recovered", "audit_failed", "error", "fallback"]
    execution: ExecutionMetadata
