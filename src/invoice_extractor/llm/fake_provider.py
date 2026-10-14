from __future__ import annotations

from invoice_extractor.llm.base import LLMResponse


class FakeProvider:
    def __init__(
        self,
        responses: list[str] | None = None,
        errors: list[LLMResponse | None] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._errors = list(errors or [])
        self.call_count = 0
        self.last_text: str | None = None
        self.last_images: list[bytes] | None = None
        self.last_system_prompt: str | None = None

    @property
    def model_name(self) -> str:
        return "fake-model"

    def call(
        self,
        *,
        system_prompt: str,
        text: str | None = None,
        images: list[bytes] | None = None,
        tool_schema: dict | None = None,
        error_feedback: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_text = text
        self.last_images = images
        self.last_system_prompt = system_prompt

        if self._errors:
            err = self._errors.pop(0)
            if err is not None:
                return err

        if self._responses:
            content = self._responses.pop(0)
            return LLMResponse(success=True, content=content, model="fake-model")

        return LLMResponse(
            success=False, error_code=500, error_message="No more canned responses"
        )
