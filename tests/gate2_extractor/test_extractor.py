"""Gate 2 — Extraction tests (G2-01 through G2-10).

Done when: extractor turns NormalizedDoc into Invoice via the provider interface,
handles bad LLM output, and never crashes the pipeline. Uses FakeProvider only.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from invoice_extractor.errors import ExtractionFailed
from invoice_extractor.extractor import extract
from invoice_extractor.llm.base import LLMResponse
from invoice_extractor.llm.factory import get_provider
from invoice_extractor.llm.fake_provider import FakeProvider
from invoice_extractor.schema import NormalizedDoc

LLM_RESPONSES = Path(__file__).parent.parent / "fixtures" / "llm_responses"


def _text_doc(text: str = "Invoice text") -> NormalizedDoc:
    return NormalizedDoc(
        mode="text", text=text, images=None, source_format="text/plain", page_count=1
    )


def _vision_doc() -> NormalizedDoc:
    return NormalizedDoc(
        mode="vision",
        text=None,
        images=[b"\x89PNG\r\n\x1a\nfake"],
        source_format="application/pdf",
        page_count=1,
    )


class TestG2_01_ValidJson:
    def test_valid_response_parsed(self):
        response_json = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(responses=[response_json])
        result = extract(_text_doc(), provider=provider)
        assert result.invoice_number == "INV-2026-001"
        assert result.vendor.name == "Acme Corp"
        assert len(result.line_items) == 2


class TestG2_02_JsonInCodeFence:
    def test_code_fence_stripped(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        wrapped = f"Here is the extracted data:\n\n```json\n{raw}\n```\n\nDone."
        provider = FakeProvider(responses=[wrapped])
        result = extract(_text_doc(), provider=provider)
        assert result.invoice_number == "INV-2026-001"

    def test_prose_wrapped(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        wrapped = f"I found the following invoice data:\n{raw}\nEnd of extraction."
        provider = FakeProvider(responses=[wrapped])
        result = extract(_text_doc(), provider=provider)
        assert result.invoice_number == "INV-2026-001"


class TestG2_03_RetryOnInvalid:
    def test_one_retry_then_success(self):
        responses_data = json.loads(
            (LLM_RESPONSES / "invalid_then_valid.json").read_text()
        )
        bad = json.dumps(responses_data[0])
        good = json.dumps(responses_data[1])
        provider = FakeProvider(responses=[bad, good])
        result = extract(_text_doc(), provider=provider)
        assert result.invoice_number == "INV-RETRY-001"
        assert provider.call_count == 2


class TestG2_04_FailAfterTwoInvalid:
    def test_raises_extraction_failed(self):
        provider = FakeProvider(responses=[
            '{"vendor": {"name": 123}, "line_items": "bad"}',
            '{"vendor": {"name": 456}, "line_items": "bad"}',
        ])
        with pytest.raises(ExtractionFailed):
            extract(_text_doc(), provider=provider)
        assert provider.call_count == 2


class TestG2_05_TextMode:
    def test_provider_receives_text(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(responses=[raw])
        doc = _text_doc("Some invoice text here")
        extract(doc, provider=provider)
        assert provider.last_text == "Some invoice text here"
        assert provider.last_images is None


class TestG2_06_VisionMode:
    def test_provider_receives_images(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(responses=[raw])
        doc = _vision_doc()
        extract(doc, provider=provider)
        assert provider.last_images is not None
        assert provider.last_text is None


class TestG2_07_PromptLoaded:
    def test_prompt_contains_rule(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(responses=[raw])
        result = extract(_text_doc(), provider=provider)
        assert provider.last_system_prompt is not None
        assert "do not calculate" in provider.last_system_prompt.lower()

    def test_prompt_version_in_meta(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(responses=[raw])
        result = extract(_text_doc(), provider=provider)
        from invoice_extractor.extractor import PROMPT_VERSION
        assert PROMPT_VERSION is not None


class TestG2_08_RetryOnServerError:
    def test_retries_on_5xx(self):
        raw = (LLM_RESPONSES / "valid_invoice.json").read_text()
        provider = FakeProvider(
            responses=[raw],
            errors=[
                LLMResponse(success=False, error_code=500, error_message="Internal Server Error"),
                LLMResponse(success=False, error_code=503, error_message="Service Unavailable"),
                None,
            ],
        )
        result = extract(_text_doc(), provider=provider)
        assert result.invoice_number == "INV-2026-001"

    def test_fails_after_max_retries(self):
        provider = FakeProvider(
            responses=[],
            errors=[
                LLMResponse(success=False, error_code=500, error_message="fail"),
                LLMResponse(success=False, error_code=500, error_message="fail"),
                LLMResponse(success=False, error_code=500, error_message="fail"),
            ],
        )
        with pytest.raises(ExtractionFailed):
            extract(_text_doc(), provider=provider)


class TestG2_09_AuthError:
    def test_no_retry_on_4xx(self):
        provider = FakeProvider(
            responses=[],
            errors=[
                LLMResponse(success=False, error_code=401, error_message="Unauthorized"),
            ],
        )
        with pytest.raises(ExtractionFailed, match="[Aa]uth|401|[Uu]nauthorized"):
            extract(_text_doc(), provider=provider)
        assert provider.call_count == 1


class TestG2_10_ProviderSwap:
    def test_factory_returns_fake(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "fake"}):
            provider = get_provider()
            assert isinstance(provider, FakeProvider)

    def test_factory_returns_anthropic(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "test-key"}):
            from invoice_extractor.llm.anthropic_provider import AnthropicProvider
            provider = get_provider()
            assert isinstance(provider, AnthropicProvider)


_LLM_API_KEY = os.environ.get("LLM_API_KEY")

_skip_no_key = pytest.mark.skipif(
    _LLM_API_KEY is None,
    reason="LLM_API_KEY not set — set it to run integration tests",
)


@pytest.mark.integration
class TestG2_11_RealLLMText:
    @_skip_no_key
    def test_real_llm_text_invoice(self):
        from invoice_extractor.extractor import extract
        from invoice_extractor.llm.factory import get_provider
        from invoice_extractor.loaders.router import normalize

        fixtures = Path(__file__).parent.parent / "fixtures" / "generated"
        doc = normalize(fixtures / "invoice_utf8.txt")
        assert doc.mode == "text"

        provider = get_provider()
        invoice = extract(doc, provider=provider)

        assert invoice.vendor.name is not None
        assert "acme" in invoice.vendor.name.lower()
        assert invoice.invoice_number == "INV-2026-001"
        assert invoice.total is not None


@pytest.mark.integration
class TestG2_12_RealLLMVision:
    @_skip_no_key
    def test_real_llm_scanned_invoice(self):
        from invoice_extractor.extractor import extract
        from invoice_extractor.llm.factory import get_provider
        from invoice_extractor.loaders.router import normalize

        fixtures = Path(__file__).parent.parent / "fixtures" / "generated"
        doc = normalize(fixtures / "invoice_scanned.pdf")
        assert doc.mode == "vision"

        provider = get_provider()
        invoice = extract(doc, provider=provider)

        assert invoice.vendor.name is not None
        assert invoice.total is not None
