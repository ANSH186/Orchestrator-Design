"""Domain-specific exceptions with safe, actionable messages."""

from __future__ import annotations


class ProcurementDeskError(Exception):
    """Base exception for the application."""


class IngestionError(ProcurementDeskError):
    """Raised when supplied data or a playbook document cannot be parsed."""


class KnowledgeBaseError(ProcurementDeskError):
    """Raised when the structured knowledge base is incomplete or inconsistent."""


class PolicyResolutionError(ProcurementDeskError):
    """Raised when an applicable category/amendment cannot be resolved."""


class SupplierResolutionError(ProcurementDeskError):
    """Raised when a supplier identity cannot be resolved safely."""


class ExtractionError(ProcurementDeskError):
    """Raised when an offer cannot be interpreted without inventing facts."""


class PricingError(ProcurementDeskError):
    """Raised when a price cannot be normalized deterministically."""


class DecisionError(ProcurementDeskError):
    """Raised when the deterministic decision procedure cannot produce a label."""


class AuditError(ProcurementDeskError):
    """Raised when an independent audit fails."""


class LLMProviderError(ProcurementDeskError):
    """Raised when the configured LLM provider is unavailable or malformed."""
