from __future__ import annotations

import json
import os

import anthropic

from invoice_extractor.llm.base import LLMResponse


class AnthropicProvider:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self._model = model or os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")
        self._client = anthropic.Anthropic(api_key=self._api_key)

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
        messages_content: list[dict] = []

        if text:
            user_text = text
            if error_feedback:
                user_text += (
                    f"\n\nPrevious extraction had errors: {error_feedback}"
                    "\nPlease fix and try again."
                )
            messages_content.append({"type": "text", "text": user_text})
        elif images:
            for img in images:
                import base64
                b64 = base64.b64encode(img).decode("ascii")
                messages_content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64},
                })
            if error_feedback:
                messages_content.append({
                    "type": "text",
                    "text": (
                        f"Previous extraction had errors: {error_feedback}"
                        "\nPlease fix and try again."
                    ),
                })

        try:
            kwargs: dict = {
                "model": self._model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": messages_content}],
            }
            if tool_schema:
                kwargs["tools"] = [{
                    "name": "extract_invoice",
                    "description": "Extract structured invoice data",
                    "input_schema": tool_schema,
                }]

            response = self._client.messages.create(**kwargs)

            content_text = ""
            for block in response.content:
                if block.type == "text":
                    content_text += block.text
                elif block.type == "tool_use":
                    content_text = json.dumps(block.input)

            return LLMResponse(
                success=True,
                content=content_text,
                model=self._model,
            )
        except anthropic.AuthenticationError as e:
            return LLMResponse(
                success=False, error_code=401, error_message=str(e), model=self._model
            )
        except anthropic.RateLimitError as e:
            return LLMResponse(
                success=False, error_code=429, error_message=str(e), model=self._model
            )
        except anthropic.InternalServerError as e:
            return LLMResponse(
                success=False, error_code=500, error_message=str(e), model=self._model
            )
        except anthropic.APIStatusError as e:
            return LLMResponse(
                success=False,
                error_code=e.status_code,
                error_message=str(e),
                model=self._model,
            )
        except anthropic.APIConnectionError as e:
            return LLMResponse(
                success=False, error_code=503, error_message=str(e), model=self._model
            )
