"""Streamlit UI for the invoice extraction pipeline."""

from __future__ import annotations

import hmac
import json
import os
import re
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

# ── Load st.secrets into os.environ (Cloud) ──────────────────────────────────
try:
    for key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "PROMPT_VERSION", "APP_PASSWORD"):
        if key not in os.environ:
            val = st.secrets.get(key)
            if val is not None:
                os.environ[key] = str(val)
except FileNotFoundError:
    pass

# ── Access gate ──────────────────────────────────────────────────────────────

_APP_PASSWORD = os.environ.get("APP_PASSWORD")

def _check_access():
    if _APP_PASSWORD:
        if st.session_state.get("authenticated"):
            return
        pw = st.text_input("Password", type="password", key="pw_input")
        if not pw:
            st.stop()
        if hmac.compare_digest(pw, _APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
            st.stop()
    else:
        if os.environ.get("APP_ENV") == "local":
            return
        st.error("App not configured. Set APP_PASSWORD or APP_ENV=local.")
        st.stop()

_check_access()

# ── Imports (after gate, so they only load for authenticated users) ──────────

import pandas as pd

from invoice_extractor.errors import ExtractionFailed, InvoiceExtractorError
from invoice_extractor.extractor import PROMPT_VERSION, extract
from invoice_extractor.ingestion import compute_cache_key, compute_file_hash, generate_job_id
from invoice_extractor.llm.factory import get_provider
from invoice_extractor.loaders.router import normalize
from invoice_extractor.router import route
from invoice_extractor.schema import (
    ExtractionResult,
    Invoice,
    Meta,
    NormalizedDoc,
    ValidationResult,
)
from invoice_extractor.validator import validate

SUPPORTED = ["pdf", "docx", "doc", "txt", "png", "jpg", "jpeg"]

_STORAGE_DIR = Path(
    os.environ.get("STORAGE_DIR")
    or os.path.join(tempfile.gettempdir(), "invoice_extractor")
)

st.set_page_config(layout="wide", page_title="Invoice Extractor")

st.markdown(
    """<style>
.block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
[data-testid="stMetricValue"] { font-size: 1.1rem; }
span.muted { color: #9CA3AF; font-style: italic; }
.compact-card p { margin: 0 0 0.1rem 0; font-size: 0.85rem; line-height: 1.3; }
.compact-card .card-title { font-size: 0.9rem; font-weight: 600; margin-bottom: 0.3rem; }
</style>""",
    unsafe_allow_html=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _m(text: str) -> str:
    return f'<span class="muted">{text}</span>'


def _group_indian(integer: str) -> str:
    if len(integer) <= 3:
        return integer
    last3 = integer[-3:]
    rest = integer[:-3]
    parts: list[str] = []
    while rest:
        parts.append(rest[-2:] if len(rest) >= 2 else rest)
        rest = rest[:-2]
    parts.reverse()
    return ",".join(parts) + "," + last3


def _fmt(amount: Decimal | None, currency: str | None = None) -> str:
    if amount is None:
        return "—"
    sym = "₹" if (currency or "INR") == "INR" else f"{currency} " if currency else ""
    s = f"{abs(amount):.2f}"
    integer, decimal = s.split(".")
    sign = "-" if amount < 0 else ""
    return f"{sign}{sym}{_group_indian(integer)}.{decimal}"


def _fmt_qty(val: Decimal | None) -> str:
    if val is None:
        return ""
    normed = val.normalize()
    return f"{normed:f}"


def _fmt_money_plain(amount: Decimal | None) -> str:
    if amount is None:
        return ""
    s = f"{abs(amount):.2f}"
    integer, decimal = s.split(".")
    sign = "-" if amount < 0 else ""
    return f"{sign}{_group_indian(integer)}.{decimal}"


def _bad_lines(val: ValidationResult | None) -> set[int]:
    bad: set[int] = set()
    if val:
        for issue in val.errors:
            if issue.field and (m := re.match(r"line_items\[(\d+)\]", issue.field)):
                bad.add(int(m.group(1)))
    return bad


# ── Processing ────────────────────────────────────────────────────────────────


def process_invoice(file_bytes: bytes, filename: str, status) -> tuple[ExtractionResult, NormalizedDoc | None]:
    with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    timings: dict[str, float] = {}
    job_id = generate_job_id()
    provider = get_provider()
    pv = PROMPT_VERSION
    meta = Meta(prompt_version=pv)

    try:
        t0 = time.monotonic()
        file_hash = compute_file_hash(tmp_path)
        timings["hash"] = time.monotonic() - t0
        meta.file_hash = file_hash
        meta.cache_key = compute_cache_key(file_hash, provider.model_name, pv)

        status.update(label="Normalizing document…")
        t0 = time.monotonic()
        try:
            doc = normalize(tmp_path)
        except InvoiceExtractorError as exc:
            timings["normalize"] = time.monotonic() - t0
            meta.timings, meta.error = timings, str(exc)
            status.update(label="Failed", state="error")
            return ExtractionResult(job_id=job_id, status="failed", meta=meta), None
        timings["normalize"] = time.monotonic() - t0
        meta.source_format, meta.mode, meta.model = doc.source_format, doc.mode, provider.model_name

        status.update(label="Extracting with LLM…")
        t0 = time.monotonic()
        try:
            invoice = extract(doc, provider=provider, prompt_version=pv)
        except ExtractionFailed as exc:
            timings["extract"] = time.monotonic() - t0
            meta.timings, meta.error = timings, str(exc)
            status.update(label="Extraction failed", state="error")
            return ExtractionResult(job_id=job_id, status="needs_review", meta=meta), doc
        timings["extract"] = time.monotonic() - t0

        status.update(label="Validating…")
        t0 = time.monotonic()
        validation = validate(invoice)
        timings["validate"] = time.monotonic() - t0

        meta.timings = timings
        result = ExtractionResult(
            job_id=job_id, status=route(validation),
            invoice=invoice, validation=validation, meta=meta,
        )
        return result, doc

    except Exception as exc:
        meta.timings, meta.error = timings, str(exc)
        status.update(label="Unexpected error", state="error")
        return ExtractionResult(job_id=job_id, status="failed", meta=meta), None
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Render functions ──────────────────────────────────────────────────────────


def render_header():
    st.title("Invoice Extractor")
    st.caption("Demo — use sample invoices only. Do not upload real or confidential documents.")
    c1, c2 = st.columns([6, 1], vertical_alignment="bottom")
    with c1:
        uploaded = st.file_uploader("Upload", type=SUPPORTED, label_visibility="collapsed")
    with c2:
        go = st.button("Extract", type="primary", use_container_width=True)
    return uploaded, go


def render_preview(file_bytes: bytes, filename: str, doc: NormalizedDoc | None):
    ext = Path(filename).suffix.lower()
    with st.container(height=800):
        if ext == ".pdf":
            import fitz

            pdf = fitz.open(stream=file_bytes, filetype="pdf")
            for i, page in enumerate(pdf):
                pix = page.get_pixmap(dpi=150)
                st.image(pix.tobytes("png"), caption=f"Page {i + 1}", use_container_width=True)
            pdf.close()
        elif ext in (".png", ".jpg", ".jpeg"):
            st.image(file_bytes, use_container_width=True)
        elif doc and doc.text:
            st.code(doc.text, language=None)
        else:
            st.info("Preview not available for this format.")


def render_summary(result: ExtractionResult):
    inv = result.invoice
    val = result.validation

    if result.status == "auto_approved":
        st.success("Auto-approved — all checks passed")
    elif result.status == "needs_review":
        st.warning("Needs review — validation issues found")
    else:
        st.error(f"Failed: {result.meta.error or 'unknown error'}")
        return

    total_secs = sum(result.meta.timings.values()) if result.meta.timings else 0
    st.caption(f"{result.meta.model} · {result.meta.mode} mode · `{result.job_id}` · {total_secs:.1f}s")

    if not inv:
        return

    cur = inv.currency

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Subtotal", _fmt(inv.subtotal, cur))
    with m2:
        tax_sum = sum((t.amount or Decimal(0)) for t in inv.tax_lines) if inv.tax_lines else None
        st.metric("Tax", _fmt(tax_sum, cur))
    with m3:
        delta = None
        if val and val.computed.total is not None and inv.total is not None:
            diff = val.computed.total - inv.total
            if diff != Decimal(0):
                delta = f"{diff:+.2f}"
        st.metric("Total", _fmt(inv.total, cur), delta=delta, delta_color="off")
    with m4:
        st.metric("Line Items", len(inv.line_items))

    def _card(title: str, pairs: list[tuple[str, str | None]]) -> str:
        lines = [f'<div class="compact-card"><p class="card-title">{title}</p>']
        for label, value in pairs:
            display = value if value else '<span class="muted">—</span>'
            lines.append(f"<p><b>{label}:</b> {display}</p>")
        lines.append("</div>")
        return "\n".join(lines)

    d1, d2, d3 = st.columns(3)
    with d1:
        with st.container(border=True):
            st.markdown(_card("Vendor", [
                ("Name", inv.vendor.name),
                ("GSTIN", inv.vendor.tax_id),
                ("Address", inv.vendor.address),
            ]), unsafe_allow_html=True)
    with d2:
        buyer_pairs: list[tuple[str, str | None]] = [("Name", None), ("GSTIN", None), ("Address", None)]
        if inv.buyer:
            buyer_pairs = [
                ("Name", inv.buyer.name),
                ("GSTIN", inv.buyer.tax_id),
                ("Address", inv.buyer.address),
            ]
        with st.container(border=True):
            st.markdown(_card("Buyer", buyer_pairs), unsafe_allow_html=True)
    with d3:
        with st.container(border=True):
            st.markdown(_card("Invoice", [
                ("Number", inv.invoice_number),
                ("Date", str(inv.invoice_date) if inv.invoice_date else None),
                ("Due", str(inv.due_date) if inv.due_date else None),
                ("PO", inv.po_number),
                ("Currency", inv.currency),
            ]), unsafe_allow_html=True)


def render_line_items(inv: Invoice, val: ValidationResult | None):
    if not inv.line_items:
        return

    st.markdown("**Line Items**")
    bad = _bad_lines(val)
    rows = []
    for i, item in enumerate(inv.line_items):
        rows.append({
            "Description": item.description,
            "HSN/SAC": item.hsn_sac or "",
            "Qty": _fmt_qty(item.quantity),
            "Unit": item.unit or "",
            "Unit Price": _fmt_money_plain(item.unit_price),
            "Amount": _fmt_money_plain(item.amount),
            "Check": "✗" if i in bad else "✓",
        })
    st.dataframe(
        pd.DataFrame(rows),
        column_config={
            "Check": st.column_config.TextColumn(width="small"),
        },
        hide_index=True,
        use_container_width=True,
    )

    if inv.tax_lines:
        st.markdown("**Tax Breakdown**")
        tax_rows = [{
            "Tax": t.name,
            "Rate (%)": _fmt_qty(t.rate_percent),
            "Amount": _fmt_money_plain(t.amount),
        } for t in inv.tax_lines]
        st.dataframe(
            pd.DataFrame(tax_rows),
            hide_index=True,
            use_container_width=True,
        )


def render_validation(val: ValidationResult | None):
    if not val or val.passed:
        return
    st.markdown("**Validation**")
    for issue in val.errors:
        parts = [f"**{issue.code}**"]
        if issue.field:
            parts.append(f"`{issue.field}`")
        parts.append(issue.message)
        if issue.expected and issue.found:
            parts.append(f"(expected {issue.expected}, found {issue.found})")
        st.error(" · ".join(parts))
    for issue in val.warnings:
        parts = [f"**{issue.code}**"]
        if issue.field:
            parts.append(f"`{issue.field}`")
        parts.append(issue.message)
        st.warning(" · ".join(parts))


def render_raw(result: ExtractionResult):
    tab1, tab2 = st.tabs(["Raw JSON", "Metadata"])
    raw = result.model_dump_json(indent=2)
    with tab1:
        st.json(json.loads(raw))
        inv_num = result.invoice.invoice_number if result.invoice else None
        st.download_button(
            "Download JSON", raw,
            file_name=f"{inv_num or result.job_id}.json",
            mime="application/json",
        )
    with tab2:
        st.json(json.loads(result.meta.model_dump_json(indent=2)))


# ── Main flow ─────────────────────────────────────────────────────────────────

uploaded, go = render_header()

with st.sidebar:
    st.markdown("**Sample invoices**")
    st.caption("Download these and upload them to try the app:")
    demo_dir = Path(__file__).parent / "demo_samples"
    for f in sorted(demo_dir.iterdir()) if demo_dir.exists() else []:
        st.download_button(f.name, f.read_bytes(), file_name=f.name, key=f"demo_{f.name}")

if not uploaded:
    st.caption("Supported formats: PDF · DOCX · DOC · TXT · PNG · JPG")
    st.stop()

if go:
    if not os.environ.get("LLM_API_KEY"):
        st.error("`LLM_API_KEY` not configured. Set it in `.env` or Streamlit secrets.")
        st.stop()
    with st.status("Processing…", expanded=True) as status:
        result, doc = process_invoice(uploaded.getvalue(), uploaded.name, status)
        status.update(label="Done", state="complete", expanded=False)
    st.session_state.result = result
    st.session_state.doc = doc
    st.session_state.file_bytes = uploaded.getvalue()
    st.session_state.filename = uploaded.name

if "result" not in st.session_state:
    st.stop()

_result: ExtractionResult = st.session_state.result

if _result.status == "failed":
    st.error(_result.meta.error or "Processing failed.")
    render_raw(_result)
    st.stop()

left, right = st.columns([5, 7])
with left:
    render_preview(st.session_state.file_bytes, st.session_state.filename, st.session_state.doc)
with right:
    render_summary(_result)
    if _result.invoice:
        render_line_items(_result.invoice, _result.validation)
    render_validation(_result.validation)
    render_raw(_result)
