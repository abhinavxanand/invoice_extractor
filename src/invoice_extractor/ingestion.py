from __future__ import annotations

import hashlib
import uuid
from pathlib import Path


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_job_id() -> str:
    return uuid.uuid4().hex[:16]


def compute_cache_key(file_hash: str, model: str, prompt_version: str) -> str:
    return f"{file_hash}:{model}:{prompt_version}"
