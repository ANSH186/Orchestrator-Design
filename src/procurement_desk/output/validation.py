"""Submission validation surface (implementation lives in submission.py)."""

from procurement_desk.output.submission import (
    SubmissionValidationResult,
    label_is_valid,
    validate_submission,
)

__all__ = ["SubmissionValidationResult", "label_is_valid", "validate_submission"]
