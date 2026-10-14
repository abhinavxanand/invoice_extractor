"""Gate 3 — Validation tests (G3-01 through G3-18).

Done when: every arithmetic and format rule is covered. Pure functions, fastest tests.
Tolerance: 0.01 per line; totals tolerance 0.01 * max(1, number_of_lines).
"""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from invoice_extractor.schema import Invoice, LineItem, Party, TaxLine
from invoice_extractor.validator import validate


def _invoice(**kwargs) -> Invoice:
    defaults = {
        "vendor": Party(name="Acme Corp"),
        "invoice_number": "INV-001",
        "line_items": [],
        "total": Decimal("0"),
    }
    defaults.update(kwargs)
    return Invoice(**defaults)


class TestG3_01_PerfectInvoice:
    def test_passes(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("2"), unit_price=Decimal("100"), amount=Decimal("200")),
                LineItem(description="B", quantity=Decimal("3"), unit_price=Decimal("50"), amount=Decimal("150")),
            ],
            subtotal=Decimal("350"),
            tax_lines=[TaxLine(name="GST", rate_percent=Decimal("10"), amount=Decimal("35"))],
            total=Decimal("385"),
        )
        result = validate(inv)
        assert result.passed is True
        assert result.errors == []


class TestG3_02_LineAmountMismatch:
    def test_detects_mismatch(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("2"), unit_price=Decimal("150"), amount=Decimal("320")),
            ],
            subtotal=Decimal("320"),
            total=Decimal("320"),
        )
        result = validate(inv)
        assert not result.passed
        codes = [e.code for e in result.errors]
        assert "LINE_AMOUNT_MISMATCH" in codes
        err = next(e for e in result.errors if e.code == "LINE_AMOUNT_MISMATCH")
        assert err.expected is not None
        assert err.found is not None


class TestG3_03_LineRoundingTolerance:
    def test_passes_within_tolerance(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("3"), unit_price=Decimal("33.33"), amount=Decimal("100.00")),
            ],
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        result = validate(inv)
        assert not any(e.code == "LINE_AMOUNT_MISMATCH" for e in result.errors)


class TestG3_04_SubtotalMismatch:
    def test_detects_mismatch(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("100"), amount=Decimal("100")),
                LineItem(description="B", quantity=Decimal("1"), unit_price=Decimal("200"), amount=Decimal("200")),
            ],
            subtotal=Decimal("999"),
            total=Decimal("999"),
        )
        result = validate(inv)
        codes = [e.code for e in result.errors]
        assert "SUBTOTAL_MISMATCH" in codes


class TestG3_05_TotalMismatch:
    def test_detects_mismatch(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("100"), amount=Decimal("100")),
            ],
            subtotal=Decimal("100"),
            tax_lines=[TaxLine(name="GST", amount=Decimal("10"))],
            total=Decimal("999"),
        )
        result = validate(inv)
        codes = [e.code for e in result.errors]
        assert "TOTAL_MISMATCH" in codes


class TestG3_06_DiscountPresent:
    def test_subtotal_minus_discount_plus_tax(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("1000"), amount=Decimal("1000")),
            ],
            subtotal=Decimal("1000"),
            discount=Decimal("100"),
            tax_lines=[TaxLine(name="GST", amount=Decimal("90"))],
            total=Decimal("990"),
        )
        result = validate(inv)
        assert result.passed is True


class TestG3_07_LineUnverifiable:
    def test_warning_when_qty_missing(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", amount=Decimal("500")),
            ],
            subtotal=Decimal("500"),
            total=Decimal("500"),
        )
        result = validate(inv)
        codes = [w.code for w in result.warnings]
        assert "LINE_UNVERIFIABLE" in codes
        assert not any(e.code == "LINE_AMOUNT_MISMATCH" for e in result.errors)


class TestG3_08_NoLineItems:
    def test_warning_no_lines(self):
        inv = _invoice(
            line_items=[],
            total=Decimal("500"),
        )
        result = validate(inv)
        codes = [w.code for w in result.warnings]
        assert "NO_LINE_ITEMS" in codes


class TestG3_09_RequiredFieldsMissing:
    def test_missing_vendor_name(self):
        inv = _invoice(vendor=Party(), invoice_number="INV-001", total=Decimal("100"))
        result = validate(inv)
        codes = [e.code for e in result.errors]
        assert "REQUIRED_FIELD_MISSING" in codes

    def test_missing_invoice_number(self):
        inv = _invoice(invoice_number=None, total=Decimal("100"))
        result = validate(inv)
        codes = [e.code for e in result.errors]
        assert "REQUIRED_FIELD_MISSING" in codes

    def test_missing_total(self):
        inv = _invoice(total=None)
        result = validate(inv)
        codes = [e.code for e in result.errors]
        assert "REQUIRED_FIELD_MISSING" in codes


class TestG3_10_FutureDate:
    def test_warns_future_date(self):
        future = date.today() + timedelta(days=30)
        inv = _invoice(invoice_date=future, total=Decimal("100"))
        result = validate(inv)
        codes = [w.code for w in result.warnings]
        assert "FUTURE_DATE" in codes


class TestG3_11_DueBeforeInvoice:
    def test_warns_due_before_invoice(self):
        inv = _invoice(
            invoice_date=date(2026, 3, 15),
            due_date=date(2026, 3, 1),
            total=Decimal("100"),
        )
        result = validate(inv)
        codes = [w.code for w in result.warnings]
        assert "DUE_BEFORE_INVOICE" in codes


class TestG3_12_NegativeLine:
    def test_negative_credit_line(self):
        inv = _invoice(
            line_items=[
                LineItem(description="Item", quantity=Decimal("1"), unit_price=Decimal("100"), amount=Decimal("100")),
                LineItem(description="Credit", quantity=Decimal("1"), unit_price=Decimal("-20"), amount=Decimal("-20")),
            ],
            subtotal=Decimal("80"),
            total=Decimal("80"),
        )
        result = validate(inv)
        assert not any(e.code == "LINE_AMOUNT_MISMATCH" for e in result.errors)


class TestG3_13_ComputedTotals:
    def test_computed_independent(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("2"), unit_price=Decimal("100"), amount=Decimal("200")),
            ],
            subtotal=Decimal("999"),
            tax_lines=[TaxLine(name="GST", amount=Decimal("20"))],
            total=Decimal("999"),
        )
        result = validate(inv)
        assert result.computed.subtotal == Decimal("200.00")
        assert result.computed.tax_total == Decimal("20.00")
        assert result.computed.total == Decimal("220.00")


class TestG3_14_TaxRateMismatch:
    def test_warns_rate_mismatch(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("1000"), amount=Decimal("1000")),
            ],
            subtotal=Decimal("1000"),
            tax_lines=[TaxLine(name="GST", rate_percent=Decimal("10"), amount=Decimal("200"))],
            total=Decimal("1200"),
        )
        result = validate(inv)
        codes = [w.code for w in result.warnings]
        assert "TAX_RATE_MISMATCH" in codes


class TestG3_15_GstInvalidGstin:
    def test_invalid_gstin(self):
        inv = _invoice(
            vendor=Party(name="Acme", tax_id="INVALID"),
            total=Decimal("100"),
        )
        result = validate(inv, ruleset="gst")
        codes = [e.code for e in result.errors]
        assert "INVALID_TAX_ID" in codes


class TestG3_16_GstSplitMismatch:
    def test_cgst_sgst_mismatch(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("1000"), amount=Decimal("1000")),
            ],
            subtotal=Decimal("1000"),
            tax_lines=[
                TaxLine(name="CGST", rate_percent=Decimal("9"), amount=Decimal("90")),
                TaxLine(name="SGST", rate_percent=Decimal("9"), amount=Decimal("50")),
            ],
            total=Decimal("1140"),
        )
        result = validate(inv, ruleset="gst")
        codes = [e.code for e in result.errors]
        assert "GST_SPLIT_MISMATCH" in codes


class TestG3_17_GstTypeConflict:
    def test_igst_with_cgst(self):
        inv = _invoice(
            line_items=[
                LineItem(description="A", quantity=Decimal("1"), unit_price=Decimal("1000"), amount=Decimal("1000")),
            ],
            subtotal=Decimal("1000"),
            tax_lines=[
                TaxLine(name="CGST", amount=Decimal("90")),
                TaxLine(name="SGST", amount=Decimal("90")),
                TaxLine(name="IGST", amount=Decimal("180")),
            ],
            total=Decimal("1360"),
        )
        result = validate(inv, ruleset="gst")
        codes = [e.code for e in result.errors]
        assert "GST_TYPE_CONFLICT" in codes


class TestG3_19_FractionalQuantity:
    def test_sub_penny_quantity(self):
        """0.125 × 96.40 = 12.05 — must not mismatch."""
        inv = _invoice(
            line_items=[
                LineItem(
                    description="Fractional",
                    quantity=Decimal("0.125"),
                    unit_price=Decimal("96.40"),
                    amount=Decimal("12.05"),
                ),
            ],
            subtotal=Decimal("12.05"),
            total=Decimal("12.05"),
        )
        result = validate(inv)
        assert not any(e.code == "LINE_AMOUNT_MISMATCH" for e in result.errors), (
            f"Unexpected LINE_AMOUNT_MISMATCH: {result.errors}"
        )
        assert result.passed is True


class TestG3_20_ThreeDecimalUnitPrice:
    def test_three_decimal_unit_price(self):
        """12.345 × 4 = 49.38 — must not mismatch."""
        inv = _invoice(
            line_items=[
                LineItem(
                    description="Precise",
                    quantity=Decimal("4"),
                    unit_price=Decimal("12.345"),
                    amount=Decimal("49.38"),
                ),
            ],
            subtotal=Decimal("49.38"),
            total=Decimal("49.38"),
        )
        result = validate(inv)
        assert not any(e.code == "LINE_AMOUNT_MISMATCH" for e in result.errors), (
            f"Unexpected LINE_AMOUNT_MISMATCH: {result.errors}"
        )
        assert result.passed is True


class TestG3_18_PropertyTest:
    @given(
        num_items=st.integers(min_value=1, max_value=5),
        base_price=st.decimals(
            min_value=Decimal("1"), max_value=Decimal("10000"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
        quantity=st.integers(min_value=1, max_value=100),
        tax_rate=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("30"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=50)
    def test_consistent_invoices_always_pass(self, num_items, base_price, quantity, tax_rate):
        from decimal import ROUND_HALF_UP
        qty = Decimal(str(quantity))
        items = []
        subtotal = Decimal("0")
        for _ in range(num_items):
            amount = (qty * base_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            items.append(LineItem(
                description="Item",
                quantity=qty,
                unit_price=base_price,
                amount=amount,
            ))
            subtotal += amount

        subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax_amount = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = subtotal + tax_amount

        inv = _invoice(
            line_items=items,
            subtotal=subtotal,
            tax_lines=[TaxLine(name="GST", rate_percent=tax_rate, amount=tax_amount)] if tax_amount > 0 else [],
            total=total,
        )
        result = validate(inv)
        assert result.passed is True, f"Errors: {result.errors}, Warnings: {result.warnings}"
