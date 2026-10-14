from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, field_serializer, model_validator

_CURRENCY_ALIASES: dict[str, str] = {
    "rupees": "INR",
    "rupee": "INR",
    "rs": "INR",
    "rs.": "INR",
    "inr": "INR",
    "dollars": "USD",
    "dollar": "USD",
    "usd": "USD",
    "euros": "EUR",
    "euro": "EUR",
    "eur": "EUR",
    "pounds": "GBP",
    "pound": "GBP",
    "gbp": "GBP",
}

_CURRENCY_SYMBOLS: dict[str, str] = {
    "₹": "",
    "$": "",
    "€": "",
    "£": "",
    "¥": "",
}


def _parse_money(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        for sym in _CURRENCY_SYMBOLS:
            s = s.replace(sym, "")
        s = s.strip()
        s = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", s)
        s = re.sub(r"(?<=\d),(?=\d{2}(?:\D|$))", "", s)
        try:
            return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError(f"Cannot parse money value: {value!r}") from exc
    raise ValueError(f"Cannot parse money value: {value!r}")


Money = Annotated[Decimal | None, BeforeValidator(_parse_money)]


def _parse_decimal_flex(value: Any) -> Decimal | None:
    """Parse a decimal value preserving full precision (no 2dp quantization)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        for sym in _CURRENCY_SYMBOLS:
            s = s.replace(sym, "")
        s = s.strip()
        s = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", s)
        s = re.sub(r"(?<=\d),(?=\d{2}(?:\D|$))", "", s)
        try:
            return Decimal(s)
        except InvalidOperation as exc:
            raise ValueError(f"Cannot parse decimal value: {value!r}") from exc
    raise ValueError(f"Cannot parse decimal value: {value!r}")


FlexDecimal = Annotated[Decimal | None, BeforeValidator(_parse_decimal_flex)]


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip().lower()
    if key in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[key]
    return value.strip().upper()


class LineItem(BaseModel):
    description: str
    hsn_sac: str | None = None
    quantity: FlexDecimal = None
    unit: str | None = None
    unit_price: FlexDecimal = None
    amount: Money = None

    @field_serializer("amount")
    @classmethod
    def _serialize_money(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @field_serializer("quantity", "unit_price")
    @classmethod
    def _serialize_flex(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v)


class TaxLine(BaseModel):
    name: str
    rate_percent: Money = None
    amount: Money = None

    @field_serializer("rate_percent", "amount")
    @classmethod
    def _serialize_decimal(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Party(BaseModel):
    name: str | None = None
    tax_id: str | None = None
    address: str | None = None


class Invoice(BaseModel):
    vendor: Party
    buyer: Party | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    currency: str | None = None
    line_items: list[LineItem] = []
    subtotal: Money = None
    tax_lines: list[TaxLine] = []
    discount: Money = None
    total: Money = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_currency_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and "currency" in data:
            data["currency"] = _normalize_currency(data["currency"])
        return data

    @field_serializer("subtotal", "discount", "total")
    @classmethod
    def _serialize_decimal(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class NormalizedDoc(BaseModel):
    mode: Literal["text", "vision"]
    text: str | None = None
    images: list[bytes] | None = None
    source_format: str
    page_count: int


class ValidationIssue(BaseModel):
    code: str
    field: str | None = None
    message: str
    expected: str | None = None
    found: str | None = None


class ComputedTotals(BaseModel):
    subtotal: Money = None
    tax_total: Money = None
    total: Money = None

    @field_serializer("subtotal", "tax_total", "total")
    @classmethod
    def _serialize_decimal(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class ValidationResult(BaseModel):
    passed: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    computed: ComputedTotals


class Meta(BaseModel):
    source_format: str | None = None
    mode: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    file_hash: str | None = None
    cache_key: str | None = None
    timings: dict[str, float] = {}
    error: str | None = None


class ExtractionResult(BaseModel):
    job_id: str
    status: Literal["auto_approved", "needs_review", "failed"]
    invoice: Invoice | None = None
    validation: ValidationResult | None = None
    meta: Meta
