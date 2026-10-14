from __future__ import annotations

import logging
import time
from pathlib import Path

from invoice_extractor.errors import ExtractionFailed, InvoiceExtractorError
from invoice_extractor.extractor import PROMPT_VERSION, extract
from invoice_extractor.ingestion import compute_cache_key, compute_file_hash, generate_job_id
from invoice_extractor.llm.base import LLMProvider
from invoice_extractor.loaders.router import normalize
from invoice_extractor.router import route
from invoice_extractor.schema import ExtractionResult, Meta
from invoice_extractor.store import find_by_cache_key, save_result
from invoice_extractor.validator import validate

logger = logging.getLogger(__name__)


def run_pipeline(
    path: Path,
    *,
    provider: LLMProvider,
    storage_dir: Path | None = None,
    ruleset: str | None = None,
    prompt_version: str | None = None,
) -> ExtractionResult:
    timings: dict[str, float] = {}
    job_id = generate_job_id()
    pv = prompt_version or PROMPT_VERSION

    logger.info("job=%s starting pipeline for %s", job_id, path.name)

    t0 = time.monotonic()
    file_hash = compute_file_hash(path)
    timings["hash"] = time.monotonic() - t0

    cache_key = compute_cache_key(file_hash, provider.model_name, pv)
    cached = find_by_cache_key(cache_key, storage_dir=storage_dir)
    if cached is not None:
        logger.info("job=%s duplicate detected (key=%s), returning cached", job_id, cache_key)
        return cached

    meta = Meta(file_hash=file_hash, cache_key=cache_key, prompt_version=pv)

    t0 = time.monotonic()
    try:
        doc = normalize(path)
    except InvoiceExtractorError as e:
        timings["normalize"] = time.monotonic() - t0
        meta.timings = timings
        meta.error = str(e)
        result = ExtractionResult(
            job_id=job_id, status="failed", invoice=None, validation=None, meta=meta
        )
        save_result(result, storage_dir=storage_dir)
        return result
    timings["normalize"] = time.monotonic() - t0

    meta.source_format = doc.source_format
    meta.mode = doc.mode
    meta.model = provider.model_name

    t0 = time.monotonic()
    try:
        invoice = extract(doc, provider=provider, prompt_version=pv)
    except ExtractionFailed as e:
        timings["extract"] = time.monotonic() - t0
        meta.timings = timings
        meta.error = str(e)
        result = ExtractionResult(
            job_id=job_id, status="needs_review", invoice=None, validation=None, meta=meta
        )
        save_result(result, storage_dir=storage_dir)
        return result
    timings["extract"] = time.monotonic() - t0

    t0 = time.monotonic()
    validation = validate(invoice, ruleset=ruleset)
    timings["validate"] = time.monotonic() - t0

    status = route(validation)

    meta.timings = timings
    result = ExtractionResult(
        job_id=job_id, status=status, invoice=invoice, validation=validation, meta=meta
    )

    save_result(result, storage_dir=storage_dir)
    logger.info("job=%s pipeline complete, status=%s", job_id, status)
    return result
