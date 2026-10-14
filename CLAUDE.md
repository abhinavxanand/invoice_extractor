
# CLAUDE.md — Invoice Extraction System

This file is the working contract for anyone (human or Claude Code) building this repo.
Read it fully before writing code. Build **gate by gate**: a gate is done only when every
test listed under it passes. Do not start gate N+1 while gate N is red.

---

## 1. What we are building

A pipeline that takes an invoice file (`.pdf`, `.docx`, `.doc`, `.txt`, `.png`, `.jpg`) and
returns one structured JSON containing vendor details, invoice identifiers, line items,
taxes, totals, code-computed totals, and validation results.

```
file → L1 Ingestion → L2 Normalization → L3 Extraction (LLM) → L4 Validation (code)
     → L5 Routing (auto_approved | needs_review) → L6 Output (JSON + store)
```

### Core principles (non-negotiable)

1. **The LLM reads, the code calculates.** The LLM only extracts values *as printed*.
   All arithmetic happens in `validator.py` using `Decimal`.
2. **Never `float` for money.** Use `decimal.Decimal` everywhere. Rounding: `ROUND_HALF_UP`, 2 dp.
3. **Missing = `null`, never guessed.** The prompt and schema must allow `None` for every
   extracted field except `line_items` (empty list allowed).
4. **Only L2 knows file formats.** Layers after L2 see only `NormalizedDoc`.
5. **Only L3 talks to the LLM**, through a provider interface, so the vendor can be swapped.
6. **Unit tests never call a real LLM.** Real calls run only under `pytest -m integration`.
7. **Every output is traceable**: model name, prompt version, and extraction mode go into `meta`.

---

## 2. Tech stack

| Concern             | Choice                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------- |
| Language            | Python 3.11+                                                                                |
| Env / deps          | `uv` (`uv sync`, `uv run`)                                                            |
| Schema              | `pydantic` v2                                                                             |
| PDF                 | `pymupdf` (text + page rendering)                                                         |
| DOCX                | `python-docx`                                                                             |
| DOC → DOCX         | `libreoffice --headless --convert-to docx` (system dependency)                            |
| File type detection | `python-magic` (content-based, never trust extension)                                     |
| Encoding detection  | `charset-normalizer`                                                                      |
| LLM                 | Provider interface in`llm/base.py`; first implementation in `llm/anthropic_provider.py` |
| Tests               | `pytest`, `pytest-cov`; fixtures generated with `reportlab` + `python-docx`         |
| Lint / types        | `ruff`, `mypy --strict` on `src/`                                                     |

Config comes from environment variables (see `.env.example`): `LLM_PROVIDER`, `LLM_MODEL`,
`LLM_API_KEY`, `PROMPT_VERSION`, `STORAGE_DIR`. Never hardcode keys or model names.

---

## 3. Repository layout

```
invoice_extractor/
├── CLAUDE.md
├── pyproject.toml
├── .env.example
├── src/invoice_extractor/
│   ├── schema.py            # Gate 0 — Pydantic models (the shared contract)
│   ├── loaders/             # Gate 1 — L2 Normalization
│   │   ├── router.py        #   detect type → pick loader
│   │   ├── txt_loader.py
│   │   ├── docx_loader.py
│   │   ├── doc_loader.py    #   LibreOffice → docx_loader
│   │   ├── pdf_loader.py    #   text layer, falls back to page images
│   │   └── image_loader.py
│   ├── llm/                 # Gate 2 — provider abstraction
│   │   ├── base.py          #   LLMProvider protocol
│   │   ├── anthropic_provider.py
│   │   └── fake_provider.py #   returns canned JSON; used by all unit tests
│   ├── prompts/
│   │   └── extract_v1.md    #   versioned prompt; bump version on any change
│   ├── extractor.py         # Gate 2 — L3
│   ├── validator.py         # Gate 3 — L4
│   ├── ingestion.py         # Gate 4 — L1 (hash, dedupe, job id)
│   ├── router.py            # Gate 4 — L5 routing decision
│   ├── store.py             # Gate 4 — L6 persistence (JSON files / SQLite to start)
│   └── pipeline.py          # Gate 4 — wires L1→L6
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── make_fixtures.py #   generates synthetic invoices deterministically
│   │   ├── generated/       #   output of make_fixtures.py (git-ignored)
│   │   └── llm_responses/   #   canned LLM JSON for fake_provider
│   ├── gate0_schema/
│   ├── gate1_loaders/
│   ├── gate2_extractor/
│   ├── gate3_validator/
│   ├── gate4_pipeline/
│   └── gate5_eval/          #   real-sample accuracy eval (integration only)
└── samples/                 # real client invoices + expected JSON (git-ignored, PII)
```

---

## 4. Data contract (`schema.py`)

```python
class LineItem(BaseModel):
    description: str
    hsn_sac: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None          # as printed

class TaxLine(BaseModel):
    name: str                              # "CGST", "SGST", "IGST", "VAT", "Sales Tax"
    rate_percent: Decimal | None = None
    amount: Decimal | None = None          # as printed

class Party(BaseModel):
    name: str | None = None
    tax_id: str | None = None              # GSTIN / VAT no.
    address: str | None = None

class Invoice(BaseModel):
    vendor: Party
    buyer: Party | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    currency: str | None = None            # ISO 4217
    line_items: list[LineItem] = []
    subtotal: Decimal | None = None
    tax_lines: list[TaxLine] = []
    discount: Decimal | None = None
    total: Decimal | None = None

class NormalizedDoc(BaseModel):
    mode: Literal["text", "vision"]
    text: str | None
    images: list[bytes] | None
    source_format: str
    page_count: int

class ValidationResult(BaseModel):
    passed: bool
    errors: list[ValidationIssue]          # code, field, message, expected, found
    warnings: list[ValidationIssue]
    computed: ComputedTotals               # subtotal, tax_total, total

class ExtractionResult(BaseModel):          # the final JSON returned to callers
    job_id: str
    status: Literal["auto_approved", "needs_review", "failed"]
    invoice: Invoice | None
    validation: ValidationResult | None
    meta: Meta                              # source_format, mode, model, prompt_version, file_hash, timings
```

Money fields serialize to JSON as **strings** (`"1180.00"`) to avoid float drift in consumers.

**OPEN DECISION (ask the owner before Gate 3):** are invoices Indian GST only, or
international? This decides the GST-specific rules (GSTIN regex, CGST = SGST, IGST
mutually exclusive with CGST/SGST). Until answered, implement them behind a
`ruleset="gst"` flag, off by default.

---

## 5. Commands

```bash
uv sync                                   # install
uv run python tests/fixtures/make_fixtures.py   # generate synthetic fixtures
uv run pytest tests/gate0_schema          # run one gate
uv run pytest -m "not integration"        # all unit gates (no network)
uv run pytest -m integration              # real LLM calls (needs LLM_API_KEY)
uv run ruff check . && uv run mypy src
```

---

## 6. Gates and test cases

Test IDs are stable; reference them in commit messages (`feat: G1-07 scanned pdf fallback`).

### Gate 0 — Schema (`tests/gate0_schema/`)

Done when: models exist, round-trip to JSON cleanly, and reject bad input.

| ID    | Test                                                   | Expected                                                 |
| ----- | ------------------------------------------------------ | -------------------------------------------------------- |
| G0-01 | Build a full`Invoice` from a valid dict              | Validates, no error                                      |
| G0-02 | Money given as`"1,180.00"` / `"₹1180"` / `1180` | All parse to`Decimal("1180.00")`                       |
| G0-03 | Money given as a float`0.1 + 0.2`                    | Stored as exact`Decimal`, not `0.30000000000000004`  |
| G0-04 | Dump to JSON                                           | Money fields are strings with 2 dp                       |
| G0-05 | JSON round-trip (dump → load)                         | Equal to original object                                 |
| G0-06 | All optional fields missing                            | Validates; fields are`None`, lists empty               |
| G0-07 | Invalid date`"31/02/2026"`                           | `ValidationError`                                      |
| G0-08 | Currency`"rupees"`                                   | Normalized to`"INR"` or rejected; behaviour documented |
| G0-09 | `Invoice.model_json_schema()`                        | Produces a schema usable as the LLM tool schema          |

### Gate 1 — Normalization / loaders (`tests/gate1_loaders/`)

Done when: every supported format becomes a correct `NormalizedDoc`. No LLM involved.

| ID    | Test                                                 | Expected                                                                 |
| ----- | ---------------------------------------------------- | ------------------------------------------------------------------------ |
| G1-01 | UTF-8`.txt` invoice                                | `mode="text"`, text contains invoice number                            |
| G1-02 | Latin-1 / Windows-1252`.txt` with `₹` or `é` | Decoded correctly, no mojibake                                           |
| G1-03 | `.docx` with line items in a table                 | Table rows appear in text, row order preserved, cells separated by`\|`  |
| G1-04 | `.docx` with header/footer containing vendor name  | Vendor name present in text                                              |
| G1-05 | `.doc` (legacy)                                    | Converted via LibreOffice, same output as G1-03 equivalent               |
| G1-06 | Digital multi-page`.pdf`                           | `mode="text"`, `page_count` correct, page markers `--- page N ---` |
| G1-07 | Scanned`.pdf` (image only)                         | `mode="vision"`, one PNG per page, ≤ 2000 px longest side             |
| G1-08 | Mixed`.pdf` (page 1 text, page 2 scanned)          | `mode="vision"` (any scanned page ⇒ vision for whole doc)             |
| G1-09 | `.png` / `.jpg` input                            | `mode="vision"`, image passed through (re-encoded PNG)                 |
| G1-10 | PDF renamed to`.txt`                               | Router detects PDF by content, uses PDF loader                           |
| G1-11 | Empty file (0 bytes)                                 | Raises`UnsupportedOrEmptyFile`                                         |
| G1-12 | Unsupported type (`.zip`, `.xlsx`)               | Raises`UnsupportedOrEmptyFile` with type in message                    |
| G1-13 | Password-protected PDF                               | Raises`EncryptedDocument`                                              |
| G1-14 | Corrupt PDF bytes                                    | Raises`CorruptDocument`, no crash                                      |
| G1-15 | PDF over page limit (default 20)                     | Raises`DocumentTooLarge`                                               |

### Gate 2 — Extraction (`tests/gate2_extractor/`)

Done when: extractor turns `NormalizedDoc` into `Invoice` via the provider interface,
handles bad LLM output, and never crashes the pipeline. Uses `FakeProvider` only.

| ID                     | Test                                                  | Expected                                                                                      |
| ---------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| G2-01                  | Fake returns valid JSON                               | `Invoice` returned, fields match                                                            |
| G2-02                  | Fake returns JSON wrapped in prose / code fence       | Still parsed (provider uses tool/structured output; parser is a fallback)                     |
| G2-03                  | Fake returns schema-invalid JSON once, valid on retry | One retry with the error message fed back; success                                            |
| G2-04                  | Fake returns invalid JSON twice                       | Raises`ExtractionFailed`; no third call                                                     |
| G2-05                  | Text mode                                             | Provider receives text, no images                                                             |
| G2-06                  | Vision mode                                           | Provider receives images, no text                                                             |
| G2-07                  | Prompt file loaded                                    | Prompt content contains "do not calculate" rule and`PROMPT_VERSION` is reported in `meta` |
| G2-08                  | Provider timeout / 5xx                                | Retries with backoff (max 3), then`ExtractionFailed`                                        |
| G2-09                  | Provider 4xx auth error                               | Fails immediately, no retry                                                                   |
| G2-10                  | Swap provider via`LLM_PROVIDER` env                 | Factory returns correct class; no import of other providers needed                            |
| G2-11*(integration)* | Real LLM on synthetic text invoice                    | Vendor, number, total match fixture truth                                                     |
| G2-12*(integration)* | Real LLM on synthetic scanned invoice                 | Same as G2-11                                                                                 |

### Gate 3 — Validation (`tests/gate3_validator/`)

Done when: every arithmetic and format rule is covered. Pure functions, fastest tests,
aim for 100% branch coverage on `validator.py`.

Tolerance: `0.01` per line; totals tolerance `0.01 × max(1, number_of_lines)`.

| ID                     | Test                                                   | Expected                                                               |
| ---------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------- |
| G3-01                  | Perfect invoice                                        | `passed=True`, no errors                                             |
| G3-02                  | One line`2 × 150 ≠ 320`                            | Error`LINE_AMOUNT_MISMATCH` on `line_items[i]` with expected/found |
| G3-03                  | Line rounding diff of 0.01                             | Passes (within tolerance)                                              |
| G3-04                  | Σ lines ≠ subtotal                                   | Error`SUBTOTAL_MISMATCH`                                             |
| G3-05                  | subtotal + tax ≠ total                                | Error`TOTAL_MISMATCH`                                                |
| G3-06                  | Discount present                                       | `subtotal − discount + tax = total` used                            |
| G3-07                  | Line missing qty or unit_price but has amount          | Line check skipped, warning`LINE_UNVERIFIABLE`, not error            |
| G3-08                  | No line items, only totals                             | Warning`NO_LINE_ITEMS`; total check still runs                       |
| G3-09                  | Missing vendor name / invoice number / total           | Error`REQUIRED_FIELD_MISSING` per field                              |
| G3-10                  | Invoice date in the future                             | Warning`FUTURE_DATE`                                                 |
| G3-11                  | Due date before invoice date                           | Warning`DUE_BEFORE_INVOICE`                                          |
| G3-12                  | Negative line (credit/return)                          | Allowed; arithmetic still checked                                      |
| G3-13                  | `computed` totals                                    | Always filled from code, independent of printed values                 |
| G3-14                  | Tax rate × base ≠ tax amount                         | Warning`TAX_RATE_MISMATCH`                                           |
| G3-15*(gst ruleset)* | Invalid GSTIN format                                   | Error`INVALID_TAX_ID`                                                |
| G3-16*(gst ruleset)* | CGST ≠ SGST                                           | Error`GST_SPLIT_MISMATCH`                                            |
| G3-17*(gst ruleset)* | IGST together with CGST/SGST                           | Error`GST_TYPE_CONFLICT`                                             |
| G3-18                  | Property test (hypothesis): random consistent invoices | Always`passed=True`                                                  |

### Gate 4 — Ingestion, routing, storage, pipeline (`tests/gate4_pipeline/`)

Done when: one call `run_pipeline(path)` returns an `ExtractionResult` for every case and
never raises to the caller.

| ID    | Test                                                 | Expected                                                                                        |
| ----- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| G4-01 | New file                                             | New`job_id`, original file stored, hash recorded                                              |
| G4-02 | Same file submitted twice                            | Second call returns cached result; LLM not called (assert fake call count = 1)                  |
| G4-03 | Same content, different filename                     | Treated as duplicate (hash-based)                                                               |
| G4-04 | Validation passed                                    | `status="auto_approved"`                                                                      |
| G4-05 | Validation has errors                                | `status="needs_review"`, errors included                                                      |
| G4-06 | Loader raises (corrupt / empty / encrypted)          | `status="failed"`, `invoice=None`, reason in `meta.error`                                 |
| G4-07 | Extractor raises`ExtractionFailed`                 | `status="needs_review"` (a human can still read it), reason recorded                          |
| G4-08 | `meta` contents                                    | Has`source_format`, `mode`, `model`, `prompt_version`, `file_hash`, per-layer timings |
| G4-09 | Result persisted                                     | Reloading by`job_id` returns identical JSON                                                   |
| G4-10 | End-to-end with FakeProvider for each fixture format | Every format reaches L6                                                                         |

### Gate 5 — Accuracy eval (`tests/gate5_eval/`, integration only)

Done when: real samples meet target accuracy. This gate guards every prompt/model change.

- Inputs: `samples/<name>.<ext>` + `samples/<name>.expected.json` (hand-labelled).
- Metrics per field: exact match for identifiers (vendor tax id, invoice number, date),
  numeric equality for money, line-item F1 matched by description + amount.
- Report: `uv run python -m invoice_extractor.eval` writes `eval_report.md` with a per-field table.

| ID    | Check                                                    | Target (initial, revisit after first run)           |
| ----- | -------------------------------------------------------- | --------------------------------------------------- |
| G5-01 | Invoice number exact match                               | ≥ 95%                                              |
| G5-02 | Vendor name match (normalized)                           | ≥ 95%                                              |
| G5-03 | Total amount exact                                       | ≥ 98%                                              |
| G5-04 | Line-item F1                                             | ≥ 90%                                              |
| G5-05 | Auto-approve precision (auto-approved AND fully correct) | ≥ 99% — a wrong auto-approve is the worst failure |
| G5-06 | No regression vs previous`eval_report.md`              | No field drops > 2 points                           |

---

## 7. Working rules for Claude Code

- Before writing code for a gate, write that gate's tests first and confirm they fail.
- Keep each layer's public surface to one function: `normalize(path)`, `extract(doc)`,
  `validate(invoice)`, `route(result)`, `run_pipeline(path)`.
- Custom exceptions live in `errors.py`; never raise bare `Exception`.
- Any prompt change ⇒ new file `extract_vN.md` + bump `PROMPT_VERSION` + rerun Gate 5.
- Never commit anything from `samples/` or real API keys. Real invoices contain PII.
- Log with `job_id` on every line; never log full invoice text at INFO level.
- If a requirement here is ambiguous or blocks progress, stop and ask the owner instead of guessing.

## 8. Open questions (resolve and record answers here)

1. GST-only or international? → affects Gate 3 rulesets.
2. One invoice per file, or bundled files needing a split step?
3. Expected volume and latency (batch vs synchronous API)?
4. Can documents go to a hosted LLM, or is on-prem required?
5. What does the review queue need to be (DB flag only, or a UI)?
