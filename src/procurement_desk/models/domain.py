"""Validated domain models shared by agents, orchestrator, and output layer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Action(str, Enum):
    ACCEPT = "ACCEPT"
    COUNTER = "COUNTER"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class ReasonCode(str, Enum):
    ACCEPTABLE_PRICE = "ACCEPTABLE_PRICE"
    COUNTER_OFFER = "COUNTER_OFFER"
    ABOVE_WALKAWAY = "ABOVE_WALKAWAY"
    BLACKLISTED_SUPPLIER = "BLACKLISTED_SUPPLIER"
    MISSING_INFO = "MISSING_INFO"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    BANNED_TERM = "BANNED_TERM"
    OVER_APPROVAL_LIMIT = "OVER_APPROVAL_LIMIT"


class SupplierStatus(str, Enum):
    APPROVED = "APPROVED"
    BLACKLISTED = "BLACKLISTED"
    PROBATION = "PROBATION"
    UNKNOWN = "UNKNOWN"


class BillingPeriod(str, Enum):
    MONTH = "month"
    YEAR = "year"


class OfferBasis(str, Enum):
    PER_UNIT = "per_unit"
    TOTAL = "total"
    PER_DOZEN = "per_dozen"
    PER_PACK = "per_pack"
    PER_N = "per_n"
    PER_SUB_UNIT = "per_sub_unit"
    PREVIOUS_QUOTE = "previous_quote"


class ExtractionMethod(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    DETERMINISTIC_AFTER_LLM_FAILURE = "deterministic_after_llm_failure"
    FALLBACK = "fallback"


class AmendmentField(str, Enum):
    TARGET = "target"
    WALKAWAY = "walkaway"
    APPROVAL_LIMIT = "approval_limit"


class MessageRole(str, Enum):
    SUPPLIER = "supplier"
    ACME = "acme"


class ThreadRecord(StrictModel):
    thread_id: str = Field(min_length=1)
    date: date
    supplier: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    round: int = Field(ge=1)
    our_last_counter: Decimal | None = None
    supplier_message: str = Field(min_length=1)

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return date.fromisoformat(value.strip())
        return value

    @field_validator("our_last_counter", mode="before")
    @classmethod
    def _decimal_or_none(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        # pandas/numpy NaN is a float; reject non-finite values.
        if isinstance(value, float):
            if value != value:  # NaN
                return None
        return value


class Message(StrictModel):
    index: int = Field(ge=0)
    role: MessageRole
    supplier_name: str | None = None
    message_date: date | None = None
    is_latest: bool = False
    text: str


class OfferFacts(StrictModel):
    """Structured facts about the supplier's latest usable offer.

    The model deliberately contains no final decision.  It describes what the
    supplier said and how the amount is scoped so the deterministic pricing
    engine can normalize it.
    """

    has_usable_price: bool = False
    currency: str | None = None
    quoted_amount: Decimal | None = None
    amount_basis: OfferBasis = OfferBasis.PER_UNIT
    total_quantity: int | None = None
    pack_size: int | None = None
    per_n: int | None = None
    sub_unit_name: str | None = None
    billing_period: BillingPeriod | None = None
    gst_inclusive: bool = False

    list_discount_percent: Decimal | None = None
    previous_quote_discount_percent: Decimal | None = None
    previous_quote_amount: Decimal | None = None
    previous_quote_currency: str | None = None
    previous_quote_gst_inclusive: bool = False
    previous_quote_billing_period: BillingPeriod | None = None
    previous_quote_source_index: int | None = None
    previous_quote_basis: OfferBasis = OfferBasis.PER_UNIT
    previous_quote_total_quantity: int | None = None
    previous_quote_pack_size: int | None = None
    previous_quote_per_n: int | None = None

    volume_discount_percent: Decimal | None = None
    volume_threshold: int | None = None
    tier_threshold: int | None = None
    tier_branch: Literal["up_to", "larger"] | None = None

    free_units: int | None = None
    paid_units: int | None = None

    is_correction: bool = False
    correction_replaced_amount: Decimal | None = None
    is_range: bool = False
    range_used_high: bool = False

    unsupported_currency: bool = False
    unsupported_currency_code: str | None = None
    missing_reason: str | None = None

    quoted_amount_text: str | None = None
    quoted_unit_text: str | None = None
    offer_sentence: str | None = None
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent_required_fields(self) -> "OfferFacts":
        if self.has_usable_price:
            if self.quoted_amount is None or self.currency is None:
                raise ValueError("usable offer requires quoted_amount and currency")
            if self.unsupported_currency:
                raise ValueError("unsupported currency cannot be a usable offer")
        if self.amount_basis == OfferBasis.TOTAL and self.total_quantity is None:
            raise ValueError("total quote requires total_quantity")
        if self.amount_basis == OfferBasis.PER_PACK and self.pack_size is None:
            raise ValueError("per-pack quote requires pack_size")
        if self.amount_basis == OfferBasis.PER_N and self.per_n is None:
            raise ValueError("per-N quote requires per_n")
        if self.previous_quote_discount_percent is not None:
            if self.previous_quote_amount is None or self.previous_quote_currency is None:
                raise ValueError("previous-quote discount requires a previous quote")
        if self.free_units is not None and self.paid_units is None:
            raise ValueError("free units require paid_units")
        return self


class ThreadAnalysis(StrictModel):
    thread_id: str
    supplier: str
    category: str
    messages: list[Message]
    latest_supplier_message: str
    offer: OfferFacts
    contract_statements: list[str] = Field(default_factory=list)
    requires_billing_period: bool = False
    missing_information: bool = False
    missing_reason: str | None = None
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC
    warnings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _missing_matches_offer(self) -> "ThreadAnalysis":
        if self.missing_information and not self.missing_reason:
            raise ValueError("missing information must include a reason")
        return self


class CategoryPolicy(StrictModel):
    slug: str
    name: str
    normalized_unit: str
    normalized_period: BillingPeriod | None = None
    gst_rate: Decimal
    target: Decimal
    walkaway: Decimal
    rounds: int = Field(ge=2)
    beta: Decimal
    approval_limit: Decimal
    pack_size: int | None = None
    sub_unit_name: str | None = None
    sub_unit_factor: Decimal | None = None
    source_path: str
    raw_text: str

    @model_validator(mode="after")
    def _pack_conversion_consistency(self) -> "CategoryPolicy":
        if (self.sub_unit_name is None) != (self.sub_unit_factor is None):
            raise ValueError("sub_unit_name and sub_unit_factor must be supplied together")
        return self


class Amendment(StrictModel):
    amendment_id: str
    category_slug: str
    category_name: str
    effective_from: date
    field: AmendmentField
    amount: Decimal
    source_path: str
    raw_text: str


class Precedent(StrictModel):
    precedent_id: str
    category_name: str | None = None
    title: str
    body: str
    source_path: str


class PolicyDocument(StrictModel):
    name: str
    title: str
    body: str
    source_path: str


class AppliedAmendment(StrictModel):
    amendment_id: str
    field: AmendmentField
    amount: Decimal
    effective_from: date
    source_path: str


class ResolvedPolicy(StrictModel):
    category_slug: str
    category_name: str
    thread_date: date
    normalized_unit: str
    normalized_period: BillingPeriod | None
    gst_rate: Decimal
    target: Decimal
    walkaway: Decimal
    rounds: int
    beta: Decimal
    approval_limit: Decimal
    pack_size: int | None
    sub_unit_name: str | None
    sub_unit_factor: Decimal | None
    base_target: Decimal
    base_walkaway: Decimal
    base_approval_limit: Decimal
    applied_amendments: list[AppliedAmendment] = Field(default_factory=list)
    category_source: str
    provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SupplierProfile(StrictModel):
    key: str
    display_name: str
    status: SupplierStatus
    currency_rates: dict[str, Decimal] = Field(default_factory=dict)
    category_caps: dict[str, Decimal] = Field(default_factory=dict)
    notes: str | None = None
    source_path: str
    raw_text: str


class SupplierAnalysis(StrictModel):
    key: str
    display_name: str
    status: SupplierStatus
    category_cap: Decimal | None = None
    category_cap_applied: bool = False
    currency_rates: dict[str, Decimal] = Field(default_factory=dict)
    applied_overrides: list[str] = Field(default_factory=list)
    source_path: str
    warnings: list[str] = Field(default_factory=list)


class SecurityEvidence(StrictModel):
    rule_id: str
    category: str
    matched_text: str
    message_index: int | None = None
    message_role: MessageRole | None = None
    detail: str | None = None


class SecurityAnalysis(StrictModel):
    prompt_injection_detected: bool = False
    injection_findings: list[SecurityEvidence] = Field(default_factory=list)
    banned_term_detected: bool = False
    banned_term_findings: list[SecurityEvidence] = Field(default_factory=list)
    scanned_thread: bool = True
    latest_message_only_for_banned_terms: bool = True
    method: str = "deterministic"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _findings_match_flags(self) -> "SecurityAnalysis":
        if self.prompt_injection_detected and not self.injection_findings:
            raise ValueError("injection flag requires evidence")
        if self.banned_term_detected and not self.banned_term_findings:
            raise ValueError("banned-term flag requires evidence")
        return self


class PricingStep(StrictModel):
    step: str
    operation: str
    before: str | None = None
    after: str | None = None
    detail: str | None = None


class PricingAnalysis(StrictModel):
    thread_id: str
    quoted_amount: Decimal | None = None
    quoted_currency: str | None = None
    quoted_basis: OfferBasis = OfferBasis.PER_UNIT
    exchange_rate: Decimal | None = None
    exchange_rate_source: str | None = None
    gst_rate: Decimal | None = None
    gst_inclusive: bool = False
    billing_period_offered: BillingPeriod | None = None
    normalized_period: BillingPeriod | None = None
    normalized_price: Decimal | None = None
    normalized_price_inr_ex_gst: Decimal | None = None
    approval_amount: Decimal | None = None
    quantity: int
    missing_information: bool = False
    missing_reason: str | None = None
    trace: list[PricingStep] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_version: str = "1.0"

    @model_validator(mode="after")
    def _price_consistency(self) -> "PricingAnalysis":
        if not self.missing_information and self.normalized_price is None:
            raise ValueError("successful pricing must have a normalized price")
        if self.normalized_price is not None and self.normalized_price < 0:
            raise ValueError("normalized price cannot be negative")
        return self


class Decision(StrictModel):
    action: Action
    reason: ReasonCode
    counter_price: int | None = None
    label: str
    precedence_trace: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    values: dict[str, str] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def _label_consistency(self) -> "Decision":
        if self.action == Action.COUNTER:
            if self.reason != ReasonCode.COUNTER_OFFER:
                raise ValueError("COUNTER requires COUNTER_OFFER reason")
            if self.counter_price is None or self.counter_price < 0:
                raise ValueError("COUNTER requires a non-negative counter price")
            expected = f"COUNTER:COUNTER_OFFER:{self.counter_price}"
        else:
            if self.counter_price is not None:
                raise ValueError("only COUNTER may carry a counter price")
            expected = f"{self.action.value}:{self.reason.value}:"
        if self.label != expected:
            raise ValueError(f"label must be exactly {expected!r}, got {self.label!r}")
        return self


class AuditCheck(StrictModel):
    name: str
    passed: bool
    detail: str | None = None
    expected: str | None = None
    actual: str | None = None


class AuditResult(StrictModel):
    passed: bool
    checks: list[AuditCheck] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    recalculated_label: str | None = None
    recalculated_price: Decimal | None = None
    audit_version: str = "1.0"

    @model_validator(mode="after")
    def _failures_consistent(self) -> "AuditResult":
        if not self.passed and not self.failures:
            raise ValueError("failed audit must enumerate failures")
        return self


class ExecutionMetadata(StrictModel):
    run_id: str
    started_at: datetime
    duration_ms: float = 0.0
    llm_mode: str = "none"
    extractor_version: str = "1.0"
    policy_version: str = "1.0"
    graph_version: str = "1.0"
    recovery_attempted: bool = False
    fallback_used: bool = False


class ThreadOutcome(StrictModel):
    thread_id: str
    label: str
    action: Action
    reason: ReasonCode
    counter_price: int | None = None
    status: Literal["ok", "recovered", "audit_failed", "error", "fallback"]
    error: str | None = None
    audit_passed: bool = False
    execution: ExecutionMetadata


class ThreadDiagnostics(StrictModel):
    """Complete internal evidence bundle for one thread."""

    thread: ThreadRecord
    analysis: ThreadAnalysis | None = None
    policy: ResolvedPolicy | None = None
    supplier: SupplierAnalysis | None = None
    security: SecurityAnalysis | None = None
    pricing: PricingAnalysis | None = None
    decision: Decision | None = None
    audit: AuditResult | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
