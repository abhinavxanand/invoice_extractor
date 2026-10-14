from __future__ import annotations

import json
from pathlib import Path

from invoice_extractor.schema import ExtractionResult

_DEFAULT_STORAGE = Path("./storage")


def save_result(result: ExtractionResult, *, storage_dir: Path | None = None) -> Path:
    base = storage_dir or _DEFAULT_STORAGE
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{result.job_id}.json"
    path.write_text(result.model_dump_json(indent=2))
    return path


def load_result(job_id: str, *, storage_dir: Path | None = None) -> ExtractionResult | None:
    base = storage_dir or _DEFAULT_STORAGE
    path = base / f"{job_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return ExtractionResult.model_validate(data)


def find_by_hash(file_hash: str, *, storage_dir: Path | None = None) -> ExtractionResult | None:
    base = storage_dir or _DEFAULT_STORAGE
    if not base.exists():
        return None
    for p in base.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("meta", {}).get("file_hash") == file_hash:
                return ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, Exception):
            continue
    return None


def find_by_cache_key(
    cache_key: str, *, storage_dir: Path | None = None
) -> ExtractionResult | None:
    base = storage_dir or _DEFAULT_STORAGE
    if not base.exists():
        return None
    for p in base.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("meta", {}).get("cache_key") == cache_key:
                return ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, Exception):
            continue
    return None
