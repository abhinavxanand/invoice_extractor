from __future__ import annotations

from typing import Literal

from invoice_extractor.schema import ValidationResult


def route(validation: ValidationResult) -> Literal["auto_approved", "needs_review"]:
    if validation.passed:
        return "auto_approved"
    return "needs_review"
