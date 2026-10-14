from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from invoice_extractor.schema import (
    ComputedTotals,
    Invoice,
    ValidationIssue,
    ValidationResult,
)

_ZERO = Decimal("0.00")
_LINE_TOLERANCE = Decimal("0.01")
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$")


def _q(v: Decimal | None) -> Decimal:
    if v is None:
        return _ZERO
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate(invoice: Invoice, *, ruleset: str | None = None) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not invoice.vendor.name:
        errors.append(ValidationIssue(
            code="REQUIRED_FIELD_MISSING", field="vendor.name",
            message="Vendor name is required",
        ))
    if invoice.invoice_number is None:
        errors.append(ValidationIssue(
            code="REQUIRED_FIELD_MISSING", field="invoice_number",
            message="Invoice number is required",
        ))
    if invoice.total is None:
        errors.append(ValidationIssue(
            code="REQUIRED_FIELD_MISSING", field="total",
            message="Total is required",
        ))

    if invoice.invoice_date and invoice.invoice_date > date.today():
        warnings.append(ValidationIssue(
            code="FUTURE_DATE", field="invoice_date",
            message="Invoice date is in the future",
        ))

    if invoice.invoice_date and invoice.due_date and invoice.due_date < invoice.invoice_date:
        warnings.append(ValidationIssue(
            code="DUE_BEFORE_INVOICE", field="due_date",
            message="Due date is before invoice date",
        ))

    computed_subtotal = _ZERO
    num_lines = len(invoice.line_items)

    if num_lines == 0:
        warnings.append(ValidationIssue(
            code="NO_LINE_ITEMS", field="line_items",
            message="No line items found",
        ))
    else:
        for i, item in enumerate(invoice.line_items):
            has_all = item.quantity is not None and item.unit_price is not None
            if has_all and item.amount is not None:
                expected = _q(item.quantity * item.unit_price)
                found = _q(item.amount)
                if abs(expected - found) > _LINE_TOLERANCE:
                    errors.append(ValidationIssue(
                        code="LINE_AMOUNT_MISMATCH",
                        field=f"line_items[{i}]",
                        message=f"Line {i}: qty * unit_price != amount",
                        expected=str(expected),
                        found=str(found),
                    ))
            elif item.amount is not None and (item.quantity is None or item.unit_price is None):
                warnings.append(ValidationIssue(
                    code="LINE_UNVERIFIABLE",
                    field=f"line_items[{i}]",
                    message=f"Line {i}: missing qty or unit_price, cannot verify amount",
                ))

            if item.amount is not None:
                computed_subtotal += _q(item.amount)

    computed_subtotal = _q(computed_subtotal)
    totals_tolerance = _LINE_TOLERANCE * max(1, num_lines)

    if (
        invoice.subtotal is not None
        and num_lines > 0
        and abs(computed_subtotal - _q(invoice.subtotal)) > totals_tolerance
    ):
        errors.append(ValidationIssue(
            code="SUBTOTAL_MISMATCH",
            field="subtotal",
            message="Sum of line amounts != subtotal",
            expected=str(computed_subtotal),
            found=str(_q(invoice.subtotal)),
        ))

    computed_tax_total = _ZERO
    for tax in invoice.tax_lines:
        if tax.amount is not None:
            computed_tax_total += _q(tax.amount)
    computed_tax_total = _q(computed_tax_total)

    base_for_tax = _q(invoice.subtotal) if invoice.subtotal is not None else computed_subtotal
    for tax in invoice.tax_lines:
        if tax.rate_percent is not None and tax.amount is not None and base_for_tax > _ZERO:
            expected_tax = _q(base_for_tax * _q(tax.rate_percent) / Decimal("100"))
            found_tax = _q(tax.amount)
            if abs(expected_tax - found_tax) > _LINE_TOLERANCE:
                warnings.append(ValidationIssue(
                    code="TAX_RATE_MISMATCH",
                    field="tax_lines",
                    message=f"Tax {tax.name}: rate * base != amount",
                    expected=str(expected_tax),
                    found=str(found_tax),
                ))

    discount = _q(invoice.discount) if invoice.discount is not None else _ZERO
    computed_total = _q(computed_subtotal - discount + computed_tax_total)

    effective_subtotal = _q(invoice.subtotal) if invoice.subtotal is not None else computed_subtotal
    check_total = _q(effective_subtotal - discount + computed_tax_total)

    if invoice.total is not None and abs(check_total - _q(invoice.total)) > totals_tolerance:
        errors.append(ValidationIssue(
            code="TOTAL_MISMATCH",
            field="total",
            message="subtotal - discount + tax != total",
            expected=str(computed_total),
            found=str(_q(invoice.total)),
        ))

    if ruleset == "gst":
        _validate_gst(invoice, errors, warnings)

    has_errors = len(errors) > 0
    return ValidationResult(
        passed=not has_errors,
        errors=errors,
        warnings=warnings,
        computed=ComputedTotals(
            subtotal=computed_subtotal,
            tax_total=computed_tax_total,
            total=computed_total,
        ),
    )


def _validate_gst(
    invoice: Invoice,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    for party_name, party in [("vendor", invoice.vendor), ("buyer", invoice.buyer)]:
        if party and party.tax_id and not _GSTIN_RE.match(party.tax_id):
            errors.append(ValidationIssue(
                code="INVALID_TAX_ID",
                field=f"{party_name}.tax_id",
                message=f"Invalid GSTIN format: {party.tax_id}",
            ))

    cgst = [t for t in invoice.tax_lines if t.name.upper() == "CGST"]
    sgst = [t for t in invoice.tax_lines if t.name.upper() == "SGST"]
    igst = [t for t in invoice.tax_lines if t.name.upper() == "IGST"]

    if igst and (cgst or sgst):
        errors.append(ValidationIssue(
            code="GST_TYPE_CONFLICT",
            field="tax_lines",
            message="IGST cannot appear together with CGST/SGST",
        ))

    if cgst and sgst:
        cgst_total = sum(_q(t.amount) for t in cgst if t.amount is not None)
        sgst_total = sum(_q(t.amount) for t in sgst if t.amount is not None)
        if cgst_total != sgst_total:
            errors.append(ValidationIssue(
                code="GST_SPLIT_MISMATCH",
                field="tax_lines",
                message=f"CGST ({cgst_total}) != SGST ({sgst_total})",
                expected=str(cgst_total),
                found=str(sgst_total),
            ))
