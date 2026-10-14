from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from pydantic import ValidationError

from invoice_extractor.errors import ExtractionFailed
from invoice_extractor.llm.base import LLMProvider
from invoice_extractor.schema import Invoice, NormalizedDoc

_PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")

MAX_PARSE_RETRIES = 2
MAX_TRANSPORT_RETRIES = 3


def _load_prompt(version: str = PROMPT_VERSION) -> str:
    path = _PROMPTS_DIR / f"extract_{version}.md"
    return path.read_text()


def _extract_json(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if fence:
        return fence.group(1).strip()

    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        return raw[brace_start : brace_end + 1]

    return raw.strip()


def extract(
    doc: NormalizedDoc,
    *,
    provider: LLMProvider,
    prompt_version: str | None = None,
) -> Invoice:
    version = prompt_version or PROMPT_VERSION
    system_prompt = _load_prompt(version)
    tool_schema = Invoice.model_json_schema()

    text = doc.text if doc.mode == "text" else None
    images = doc.images if doc.mode == "vision" else None

    error_feedback: str | None = None
    parse_attempts = 0

    for transport_attempt in range(MAX_TRANSPORT_RETRIES):
        response = provider.call(
            system_prompt=system_prompt,
            text=text,
            images=images,
            tool_schema=tool_schema,
            error_feedback=error_feedback,
        )

        if not response.success:
            code = response.error_code or 0
            if 400 <= code < 500 and code != 429:
                raise ExtractionFailed(
                    f"Authentication/client error ({code}): {response.error_message}"
                )
            if transport_attempt < MAX_TRANSPORT_RETRIES - 1:
                time.sleep(0.01 * (2 ** transport_attempt))
                continue
            raise ExtractionFailed(
                f"Provider error after {MAX_TRANSPORT_RETRIES} retries: {response.error_message}"
            )

        raw_json = _extract_json(response.content)

        try:
            data = json.loads(raw_json)
            invoice = Invoice.model_validate(data)
            return invoice
        except (json.JSONDecodeError, ValidationError) as e:
            parse_attempts += 1
            if parse_attempts >= MAX_PARSE_RETRIES:
                raise ExtractionFailed(
                    f"Failed to parse LLM response after {MAX_PARSE_RETRIES} attempts: {e}"
                ) from e
            error_feedback = str(e)
            continue

    raise ExtractionFailed("Extraction failed: exhausted all retries")
