from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from invoice_extractor.schema import NormalizedDoc


def load_image(path: Path) -> NormalizedDoc:
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    return NormalizedDoc(
        mode="vision",
        text=None,
        images=[png_bytes],
        source_format=f"image/{img.format.lower() if img.format else 'png'}",
        page_count=1,
    )
