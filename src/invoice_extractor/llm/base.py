from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    success: bool = True
    content: str = ""
    error_code: int | None = None
    error_message: str | None = None
    model: str = ""


class LLMProvider(Protocol):
    def call(
        self,
        *,
        system_prompt: str,
        text: str | None = None,
        images: list[bytes] | None = None,
        tool_schema: dict | None = None,
        error_feedback: str | None = None,
    ) -> LLMResponse: ...

    @property
    def model_name(self) -> str: ...
