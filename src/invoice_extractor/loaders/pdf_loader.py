from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pymupdf

from invoice_extractor.errors import (
    CorruptDocument,
    DocumentTooLarge,
    EncryptedDocument,
)
from invoice_extractor.schema import NormalizedDoc

MAX_PAGES = 20
MAX_IMAGE_LONG_SIDE = 2000


def load_pdf(path: Path, max_pages: int = MAX_PAGES) -> NormalizedDoc:
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        msg = str(e).lower()
        if "encrypt" in msg or "password" in msg:
            raise EncryptedDocument(f"PDF is encrypted: {path.name}") from e
        raise CorruptDocument(f"Cannot open PDF: {path.name}: {e}") from e

    if doc.is_encrypted:
        doc.close()
        raise EncryptedDocument(f"PDF is encrypted: {path.name}")

    page_count = len(doc)
    if page_count > max_pages:
        doc.close()
        raise DocumentTooLarge(
            f"PDF has {page_count} pages, exceeding limit of {max_pages}"
        )

    if page_count == 0:
        doc.close()
        raise CorruptDocument(f"PDF has no pages: {path.name}")

    has_scanned_page = False
    text_parts: list[str] = []

    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if len(text) < 20:
            has_scanned_page = True
        text_parts.append(f"--- Page {i + 1} ---\n{text}")

    if has_scanned_page:
        images: list[bytes] = []
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            if max(pix.width, pix.height) > MAX_IMAGE_LONG_SIDE:
                scale = MAX_IMAGE_LONG_SIDE / max(pix.width, pix.height)
                new_w = int(pix.width * scale)
                new_h = int(pix.height * scale)
                from PIL import Image
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="PNG")
                images.append(buf.getvalue())
            else:
                images.append(pix.tobytes("png"))
        doc.close()
        return NormalizedDoc(
            mode="vision",
            text=None,
            images=images,
            source_format="application/pdf",
            page_count=page_count,
        )

    doc.close()
    full_text = "\n\n".join(text_parts)
    return NormalizedDoc(
        mode="text",
        text=full_text,
        images=None,
        source_format="application/pdf",
        page_count=page_count,
    )
