"""Gate 1 — Normalization / loader tests (G1-01 through G1-15).

Done when: every supported format becomes a correct NormalizedDoc. No LLM involved.
"""

import shutil
from pathlib import Path

import pytest

from invoice_extractor.errors import (
    CorruptDocument,
    DocumentTooLarge,
    EncryptedDocument,
    UnsupportedOrEmptyFile,
)
from invoice_extractor.loaders.router import normalize

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generated"


class TestG1_01_Utf8Txt:
    def test_text_mode_with_invoice_number(self):
        doc = normalize(FIXTURES / "invoice_utf8.txt")
        assert doc.mode == "text"
        assert doc.source_format == "text/plain"
        assert "INV-2026-001" in doc.text
        assert doc.page_count == 1


class TestG1_02_Latin1Txt:
    def test_decoded_correctly(self):
        doc = normalize(FIXTURES / "invoice_latin1.txt")
        assert doc.mode == "text"
        assert "Café" in doc.text or "Caf" in doc.text
        assert "INV-LAT-001" in doc.text


class TestG1_03_DocxTable:
    def test_table_rows_preserved(self):
        doc = normalize(FIXTURES / "invoice_table.docx")
        assert doc.mode == "text"
        assert "Widget A" in doc.text
        assert "Widget B" in doc.text
        assert "|" in doc.text
        lines_with_pipe = [l for l in doc.text.splitlines() if "|" in l and "Widget A" in l]
        assert len(lines_with_pipe) >= 1
        widget_a_line = lines_with_pipe[0]
        widget_a_idx = doc.text.index("Widget A")
        widget_b_idx = doc.text.index("Widget B")
        assert widget_a_idx < widget_b_idx


class TestG1_04_DocxHeader:
    def test_vendor_name_in_header(self):
        doc = normalize(FIXTURES / "invoice_header.docx")
        assert doc.mode == "text"
        assert "Acme Corp" in doc.text


class TestG1_05_DocLegacy:
    @pytest.mark.skipif(
        shutil.which("soffice") is None,
        reason="soffice binary not found",
    )
    def test_doc_converted(self):
        doc_path = FIXTURES / "invoice_table.doc"
        if not doc_path.exists():
            pytest.skip("invoice_table.doc fixture not generated (needs soffice)")
        doc = normalize(doc_path)
        assert doc.mode == "text"
        assert doc.source_format == "application/msword"
        assert "Widget A" in doc.text
        assert "Widget B" in doc.text


class TestG1_06_DigitalPdf:
    def test_text_mode_multipage(self):
        doc = normalize(FIXTURES / "invoice_digital.pdf")
        assert doc.mode == "text"
        assert doc.page_count == 2
        assert "--- page 1 ---" in doc.text.lower() or "--- Page 1 ---" in doc.text
        assert "INV-PDF-001" in doc.text


class TestG1_07_ScannedPdf:
    def test_vision_mode(self):
        doc = normalize(FIXTURES / "invoice_scanned.pdf")
        assert doc.mode == "vision"
        assert doc.images is not None
        assert len(doc.images) >= 1
        for img_bytes in doc.images:
            assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_image_size_limit(self):
        from io import BytesIO

        from PIL import Image

        doc = normalize(FIXTURES / "invoice_scanned.pdf")
        for img_bytes in doc.images:
            img = Image.open(BytesIO(img_bytes))
            assert max(img.size) <= 2000


class TestG1_08_MixedPdf:
    def test_vision_mode_for_mixed(self):
        doc = normalize(FIXTURES / "invoice_mixed.pdf")
        assert doc.mode == "vision"
        assert doc.images is not None
        assert doc.page_count == 2


class TestG1_09_ImageInput:
    @pytest.mark.parametrize("ext", ["png", "jpg"])
    def test_image_passthrough(self, ext):
        doc = normalize(FIXTURES / f"invoice.{ext}")
        assert doc.mode == "vision"
        assert doc.images is not None
        assert len(doc.images) == 1
        assert doc.images[0][:8] == b"\x89PNG\r\n\x1a\n"
        assert doc.page_count == 1


class TestG1_10_PdfRenamedAsTxt:
    def test_detected_by_content(self):
        doc = normalize(FIXTURES / "actually_a_pdf.txt")
        assert doc.source_format == "application/pdf"


class TestG1_11_EmptyFile:
    def test_raises_unsupported(self):
        with pytest.raises(UnsupportedOrEmptyFile):
            normalize(FIXTURES / "empty_file.txt")


class TestG1_12_UnsupportedType:
    @pytest.mark.parametrize("filename", ["archive.zip", "spreadsheet.xlsx"])
    def test_raises_unsupported(self, filename):
        with pytest.raises(UnsupportedOrEmptyFile) as exc_info:
            normalize(FIXTURES / filename)
        assert filename.split(".")[-1] in str(exc_info.value).lower() or "unsupported" in str(exc_info.value).lower()


class TestG1_13_EncryptedPdf:
    def test_raises_encrypted(self):
        with pytest.raises(EncryptedDocument):
            normalize(FIXTURES / "encrypted.pdf")


class TestG1_14_CorruptPdf:
    def test_raises_corrupt(self):
        with pytest.raises(CorruptDocument):
            normalize(FIXTURES / "corrupt.pdf")


class TestG1_15_PdfOverPageLimit:
    def test_raises_too_large(self):
        with pytest.raises(DocumentTooLarge):
            normalize(FIXTURES / "large_25pages.pdf")
