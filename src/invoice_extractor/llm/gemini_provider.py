from __future__ import annotations

import base64
import json
import os

from google import genai
from google.genai import types

from invoice_extractor.llm.base import LLMResponse


class GeminiProvider:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self._model = model or os.environ.get("LLM_MODEL", "gemini-2.5-flash")
        self._client = genai.Client(api_key=self._api_key)

    @property
    def model_name(self) -> str:
        return self._model

    def call(
        self,
        *,
        system_prompt: str,
        text: str | None = None,
        images: list[bytes] | None = None,
        tool_schema: dict | None = None,
        error_feedback: str | None = None,
    ) -> LLMResponse:
        parts: list[types.Part] = []

        if text:
            user_text = text
            if error_feedback:
                user_text += (
                    f"\n\nPrevious extraction had errors: {error_feedback}"
                    "\nPlease fix and try again."
                )
            parts.append(types.Part.from_text(text=user_text))
        elif images:
            for img in images:
                parts.append(types.Part.from_bytes(data=img, mime_type="image/png"))
            instruction = "Extract all invoice data from the image(s) above."
            if error_feedback:
                instruction += (
                    f"\n\nPrevious extraction had errors: {error_feedback}"
                    "\nPlease fix and try again."
                )
            parts.append(types.Part.from_text(text=instruction))
        else:
            parts.append(types.Part.from_text(text="Extract invoice data."))

        effective_system = system_prompt
        if tool_schema:
            effective_system += (
                "\n\n## JSON Schema\n"
                "Return a JSON object matching this schema:\n```json\n"
                + json.dumps(tool_schema, indent=2)
                + "\n```"
            )

        config = types.GenerateContentConfig(
            system_instruction=effective_system,
            max_output_tokens=4096,
            response_mime_type="application/json" if tool_schema else None,
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=parts,
                config=config,
            )

            content_text = response.text or ""

            return LLMResponse(
                success=True,
                content=content_text,
                model=self._model,
            )
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "403" in err_str or "UNAUTHENTICATED" in err_str.upper():
                return LLMResponse(
                    success=False, error_code=401, error_message=err_str, model=self._model
                )
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                return LLMResponse(
                    success=False, error_code=429, error_message=err_str, model=self._model
                )
            if "400" in err_str or "INVALID_ARGUMENT" in err_str.upper():
                return LLMResponse(
                    success=False, error_code=400, error_message=err_str, model=self._model
                )
            return LLMResponse(
                success=False, error_code=500, error_message=err_str, model=self._model
            )
