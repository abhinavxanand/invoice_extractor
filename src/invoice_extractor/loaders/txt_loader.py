from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

from invoice_extractor.schema import NormalizedDoc


def load_txt(path: Path) -> NormalizedDoc:
    raw = path.read_bytes()
    result = from_bytes(raw).best()
    if result is None:
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(result)
    return NormalizedDoc(
        mode="text",
        text=text,
        images=None,
        source_format="text/plain",
        page_count=1,
    )
