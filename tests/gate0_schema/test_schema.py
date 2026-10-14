"""Gate 0 — Schema tests (G0-01 through G0-09).

Done when: models exist, round-trip to JSON cleanly, and reject bad input.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_extractor.schema import (
    Invoice,
    LineItem,
    Party,
)


def _full_invoice_dict() -> dict:
    return {
        "vendor": {"name": "Acme Corp", "tax_id": "29ABCDE1234F1Z5", "address": "123 Main St"},
        "buyer": {"name": "Buyer Inc", "tax_id": "07XYZAB5678C1D2", "address": "456 Oak Ave"},
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-01-15",
        "due_date": "2026-02-15",
        "po_number": "PO-9876",
        "currency": "INR",
        "line_items": [
            {
                "description": "Widget A",
                "hsn_sac": "8471",
                "quantity": "10",
                "unit": "pcs",
                "unit_price": "100.00",
                "amount": "1000.00",
            },
            {
                "description": "Widget B",
                "hsn_sac": "8472",
                "quantity": "5",
                "unit": "pcs",
                "unit_price": "36.00",
                "amount": "180.00",
            },
        ],
        "subtotal": "1180.00",
        "tax_lines": [
            {"name": "CGST", "rate_percent": "9", "amount": "106.20"},
            {"name": "SGST", "rate_percent": "9", "amount": "106.20"},
        ],
        "discount": "0.00",
        "total": "1392.40",
    }


class TestG0_01_FullInvoice:
    def test_build_from_valid_dict(self):
        inv = Invoice(**_full_invoice_dict())
        assert inv.vendor.name == "Acme Corp"
        assert inv.invoice_number == "INV-2026-001"
        assert inv.invoice_date == date(2026, 1, 15)
        assert len(inv.line_items) == 2
        assert inv.line_items[0].amount == Decimal("1000.00")
        assert inv.total == Decimal("1392.40")


class TestG0_02_MoneyParsing:
    def test_comma_formatted(self):
        item = LineItem(description="Test", amount="1,180.00")
        assert item.amount == Decimal("1180.00")

    def test_currency_symbol_prefix(self):
        item = LineItem(description="Test", amount="₹1180")
        assert item.amount == Decimal("1180.00")

    def test_integer(self):
        item = LineItem(description="Test", amount=1180)
        assert item.amount == Decimal("1180.00")

    def test_string_decimal(self):
        item = LineItem(description="Test", amount="1180.00")
        assert item.amount == Decimal("1180.00")


class TestG0_03_FloatExactness:
    def test_float_sum_stored_exact(self):
        item = LineItem(description="Test", amount=0.1 + 0.2)
        assert item.amount == Decimal("0.30")
        assert str(item.amount) != "0.30000000000000004"


class TestG0_04_JsonDump:
    def test_money_fields_are_strings_with_2dp(self):
        inv = Invoice(**_full_invoice_dict())
        data = inv.model_dump(mode="json")
        assert data["total"] == "1392.40"
        assert data["subtotal"] == "1180.00"
        assert data["line_items"][0]["amount"] == "1000.00"
        assert data["tax_lines"][0]["amount"] == "106.20"
        assert data["discount"] == "0.00"


class TestG0_05_JsonRoundTrip:
    def test_dump_load_equal(self):
        inv = Invoice(**_full_invoice_dict())
        json_str = inv.model_dump_json()
        inv2 = Invoice.model_validate_json(json_str)
        assert inv == inv2


class TestG0_06_AllOptionalMissing:
    def test_minimal_invoice(self):
        inv = Invoice(vendor=Party())
        assert inv.vendor.name is None
        assert inv.buyer is None
        assert inv.invoice_number is None
        assert inv.invoice_date is None
        assert inv.due_date is None
        assert inv.po_number is None
        assert inv.currency is None
        assert inv.line_items == []
        assert inv.subtotal is None
        assert inv.tax_lines == []
        assert inv.discount is None
        assert inv.total is None


class TestG0_07_InvalidDate:
    def test_impossible_date_rejected(self):
        d = _full_invoice_dict()
        d["invoice_date"] = "31/02/2026"
        with pytest.raises(ValidationError):
            Invoice(**d)


class TestG0_08_CurrencyNormalization:
    def test_rupees_normalized_to_inr(self):
        d = _full_invoice_dict()
        d["currency"] = "rupees"
        inv = Invoice(**d)
        assert inv.currency == "INR"

    def test_usd_passthrough(self):
        d = _full_invoice_dict()
        d["currency"] = "USD"
        inv = Invoice(**d)
        assert inv.currency == "USD"

    def test_iso_code_preserved(self):
        d = _full_invoice_dict()
        d["currency"] = "EUR"
        inv = Invoice(**d)
        assert inv.currency == "EUR"


class TestG0_09_JsonSchema:
    def test_produces_valid_schema(self):
        schema = Invoice.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "vendor" in schema["properties"]
        assert "line_items" in schema["properties"]
        assert "total" in schema["properties"]
