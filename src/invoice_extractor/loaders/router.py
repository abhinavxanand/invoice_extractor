from __future__ import annotations

from pathlib import Path

import magic

from invoice_extractor.errors import UnsupportedOrEmptyFile
from invoice_extractor.schema import NormalizedDoc

_MIME_TO_LOADER = {
    "text/plain": "txt",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "image/png": "image",
    "image/jpeg": "image",
}


def normalize(path: Path, max_pages: int = 20) -> NormalizedDoc:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    size = path.stat().st_size
    if size == 0:
        raise UnsupportedOrEmptyFile("File is empty (0 bytes)")

    mime = magic.from_file(str(path), mime=True)

    loader_key = _MIME_TO_LOADER.get(mime)
    if loader_key is None:
        ext = path.suffix.lower().lstrip(".")
        raise UnsupportedOrEmptyFile(
            f"Unsupported file type: {mime} (extension: .{ext})"
        )

    if loader_key == "txt":
        from invoice_extractor.loaders.txt_loader import load_txt
        return load_txt(path)
    elif loader_key == "pdf":
        from invoice_extractor.loaders.pdf_loader import load_pdf
        return load_pdf(path, max_pages=max_pages)
    elif loader_key == "docx":
        from invoice_extractor.loaders.docx_loader import load_docx
        return load_docx(path)
    elif loader_key == "doc":
        from invoice_extractor.loaders.doc_loader import load_doc
        return load_doc(path)
    elif loader_key == "image":
        from invoice_extractor.loaders.image_loader import load_image
        return load_image(path)
    else:
        raise UnsupportedOrEmptyFile(f"No loader for: {mime}")
