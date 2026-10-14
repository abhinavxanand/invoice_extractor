"""Gate 4 — Ingestion, routing, storage, pipeline tests (G4-01 through G4-10).

Done when: one call run_pipeline(path) returns an ExtractionResult for every case
and never raises to the caller.
"""

import json
import shutil
from pathlib import Path

import pytest

from invoice_extractor.llm.fake_provider import FakeProvider
from invoice_extractor.pipeline import run_pipeline

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generated"
LLM_RESPONSES = Path(__file__).parent.parent / "fixtures" / "llm_responses"

_VALID_RESPONSE = (LLM_RESPONSES / "valid_invoice.json").read_text()


@pytest.fixture
def storage_dir(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def provider():
    return FakeProvider(responses=[_VALID_RESPONSE])


class TestG4_01_NewFile:
    def test_new_file_processed(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt",
            provider=provider,
            storage_dir=storage_dir,
        )
        assert result.job_id
        assert result.invoice is not None
        assert result.meta.file_hash is not None


class TestG4_02_DuplicateFile:
    def test_cached_on_second_call(self, storage_dir):
        provider = FakeProvider(responses=[_VALID_RESPONSE, _VALID_RESPONSE])
        r1 = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        r2 = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        assert r1.job_id == r2.job_id
        assert provider.call_count == 1


class TestG4_02b_DifferentPromptVersion:
    def test_reprocessed_on_new_prompt_version(self, storage_dir, tmp_path):
        import shutil
        prompts_dir = Path(__file__).parent.parent.parent / "src" / "invoice_extractor" / "prompts"
        shutil.copy(prompts_dir / "extract_v1.md", prompts_dir / "extract_v2.md")
        try:
            provider = FakeProvider(responses=[_VALID_RESPONSE, _VALID_RESPONSE])
            run_pipeline(
                FIXTURES / "invoice_utf8.txt",
                provider=provider,
                storage_dir=storage_dir,
                prompt_version="v1",
            )
            run_pipeline(
                FIXTURES / "invoice_utf8.txt",
                provider=provider,
                storage_dir=storage_dir,
                prompt_version="v2",
            )
            assert provider.call_count == 2
        finally:
            (prompts_dir / "extract_v2.md").unlink(missing_ok=True)


class TestG4_02c_SameModelAndPrompt:
    def test_cached_same_config(self, storage_dir):
        provider = FakeProvider(responses=[_VALID_RESPONSE, _VALID_RESPONSE])
        run_pipeline(
            FIXTURES / "invoice_utf8.txt",
            provider=provider,
            storage_dir=storage_dir,
            prompt_version="v1",
        )
        run_pipeline(
            FIXTURES / "invoice_utf8.txt",
            provider=provider,
            storage_dir=storage_dir,
            prompt_version="v1",
        )
        assert provider.call_count == 1


class TestG4_03_SameContentDifferentName:
    def test_hash_based_dedupe(self, storage_dir, tmp_path):
        provider = FakeProvider(responses=[_VALID_RESPONSE, _VALID_RESPONSE])
        src = FIXTURES / "invoice_utf8.txt"
        copy = tmp_path / "renamed_invoice.txt"
        shutil.copy2(src, copy)

        r1 = run_pipeline(src, provider=provider, storage_dir=storage_dir)
        r2 = run_pipeline(copy, provider=provider, storage_dir=storage_dir)
        assert r1.meta.file_hash == r2.meta.file_hash
        assert provider.call_count == 1


class TestG4_04_ValidationPassed:
    def test_auto_approved(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "auto_approved" or result.status == "needs_review"
        if result.validation and result.validation.passed:
            assert result.status == "auto_approved"


class TestG4_05_ValidationErrors:
    def test_needs_review(self, storage_dir):
        bad_invoice = json.dumps({
            "vendor": {"name": "Bad Corp"},
            "invoice_number": "INV-BAD",
            "line_items": [
                {"description": "A", "quantity": "2", "unit_price": "100", "amount": "999"}
            ],
            "subtotal": "999",
            "total": "999",
        })
        provider = FakeProvider(responses=[bad_invoice])
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "needs_review"
        assert result.validation is not None
        assert len(result.validation.errors) > 0


class TestG4_06_LoaderRaises:
    def test_failed_on_corrupt(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "corrupt.pdf", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "failed"
        assert result.invoice is None
        assert result.meta.error is not None

    def test_failed_on_empty(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "empty_file.txt", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "failed"
        assert result.invoice is None

    def test_failed_on_encrypted(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "encrypted.pdf", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "failed"


class TestG4_07_ExtractorRaises:
    def test_needs_review_on_extraction_failure(self, storage_dir):
        provider = FakeProvider(responses=[
            '{"bad": "json that wont validate"}',
            '{"bad": "json that wont validate"}',
        ])
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        assert result.status == "needs_review"
        assert result.meta.error is not None


class TestG4_08_MetaContents:
    def test_meta_fields(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        assert result.meta.source_format is not None
        assert result.meta.mode is not None
        assert result.meta.model is not None
        assert result.meta.prompt_version is not None
        assert result.meta.file_hash is not None
        assert "normalize" in result.meta.timings or "total" in result.meta.timings


class TestG4_09_ResultPersisted:
    def test_reload_by_job_id(self, storage_dir, provider):
        result = run_pipeline(
            FIXTURES / "invoice_utf8.txt", provider=provider, storage_dir=storage_dir
        )
        from invoice_extractor.store import load_result
        loaded = load_result(result.job_id, storage_dir=storage_dir)
        assert loaded is not None
        assert loaded.job_id == result.job_id
        assert loaded.model_dump_json() == result.model_dump_json()


class TestG4_10_EndToEndAllFormats:
    @pytest.mark.parametrize("filename", [
        "invoice_utf8.txt",
        "invoice_table.docx",
        "invoice_header.docx",
        "invoice_digital.pdf",
        "invoice_scanned.pdf",
        "invoice_mixed.pdf",
        "invoice.png",
        "invoice.jpg",
    ])
    def test_all_formats_reach_l6(self, filename, storage_dir):
        provider = FakeProvider(responses=[_VALID_RESPONSE])
        result = run_pipeline(
            FIXTURES / filename, provider=provider, storage_dir=storage_dir
        )
        assert result.status in ("auto_approved", "needs_review")
        assert result.invoice is not None
