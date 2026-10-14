from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from invoice_extractor.errors import UnsupportedOrEmptyFile
from invoice_extractor.loaders.docx_loader import load_docx
from invoice_extractor.schema import NormalizedDoc

_LIBREOFFICE_PATHS = [
    "/usr/bin/libreoffice",
    "/usr/local/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def _find_libreoffice() -> str | None:
    for p in _LIBREOFFICE_PATHS:
        if Path(p).exists():
            return p
    return shutil.which("libreoffice") or shutil.which("soffice")


def load_doc(path: Path) -> NormalizedDoc:
    lo = _find_libreoffice()
    if lo is None:
        raise UnsupportedOrEmptyFile("LibreOffice is required to convert .doc files")

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [lo, "--headless", "--convert-to", "docx", str(path), "--outdir", tmpdir],
            check=True,
            capture_output=True,
            timeout=60,
        )
        docx_path = Path(tmpdir) / (path.stem + ".docx")
        if not docx_path.exists():
            raise UnsupportedOrEmptyFile(f"LibreOffice conversion failed for {path.name}")
        doc = load_docx(docx_path)
        doc.source_format = "application/msword"
        return doc
