from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
import json
from typing import Callable

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - only relevant when dependency missing
    OpenAI = None  # type: ignore


class MissingOpenAIClient(RuntimeError):
    """Raised when the OpenAI SDK is not installed."""


class MissingAPIKey(RuntimeError):
    """Raised when no API key is configured."""


@dataclass(slots=True)
class SummarizationOptions:
    instructions: str | None = None
    max_words: int | None = None

def _coerce_response_text(value: object) -> str:
    """Extract textual content from various OpenAI response shapes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        parts = [_coerce_response_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("output_text", "output", "text", "content", "value", "message"):
            if key in value:
                text = _coerce_response_text(value[key])
                if text:
                    return text
        for item in value.values():
            text = _coerce_response_text(item)
            if text:
                return text
        return ""
    for attr in ("output_text", "output", "text", "content", "value"):
        if hasattr(value, attr):
            text = _coerce_response_text(getattr(value, attr))
            if text:
                return text
    return ""


class AISummarizationEngine:
    """Thin wrapper around the OpenAI Responses API for short summaries."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        default_max_words: int | None = None,
        client_factory: Callable[..., object] | None = None,
    ) -> None:
        if OpenAI is None:
            raise MissingOpenAIClient(
                "The `openai` package is not installed. "
                "Run `pip install openai` to enable AI summarization."
            )

        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise MissingAPIKey(
                "Set the OPENAI_API_KEY environment variable to enable summarization."
            )

        self.model = model or os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")
        max_words_env = os.getenv("OPENAI_SUMMARY_MAX_WORDS")
        if default_max_words is None and max_words_env:
            try:
                default_max_words = int(max_words_env)
            except ValueError:
                default_max_words = None
        self.default_max_words = default_max_words or 1024

        factory = client_factory or OpenAI  # type: ignore[assignment]
        self._client = factory(api_key=key)

    async def summarize(self, text: str, *, options: SummarizationOptions | None = None) -> str:
        summary, _ = await self._summarize_internal(text, options=options)
        return summary

    async def summarize_with_raw(
        self, text: str, *, options: SummarizationOptions | None = None
    ) -> tuple[str, str]:
        return await self._summarize_internal(text, options=options)

    async def _summarize_internal(
        self, text: str, *, options: SummarizationOptions | None = None
    ) -> tuple[str, str]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Text to summarize cannot be empty.")

        opts = options or SummarizationOptions()
        max_words = opts.max_words or self.default_max_words
        instruction = opts.instructions or (
            f"You are ChatGPT. Respond to the user's text as if it were a direct question to you. "
            f"Answer explicitly and conversationally, in first person, and keep the reply under {max_words} words."
        )

        def _serialize_response(response: object) -> str:
            if response is None:
                return ""
            if hasattr(response, "model_dump_json"):
                try:
                    return response.model_dump_json(indent=2)  # type: ignore[attr-defined]
                except Exception:
                    pass
            if hasattr(response, "model_dump"):
                try:
                    data = response.model_dump()  # type: ignore[attr-defined]
                    return json.dumps(data, indent=2, default=str)
                except Exception:
                    pass
            if isinstance(response, (dict, list, tuple)):
                try:
                    return json.dumps(response, indent=2, default=str)
                except Exception:
                    pass
            return repr(response)

        def _call_openai() -> tuple[str, str]:
            response = self._client.responses.create(  # type: ignore[attr-defined]
                model=self.model,
                input=[
                    {"role": "system", "content": instruction},
                    {
                        "role": "user",
                        "content": f"Summarize in <= {max_words} words:\n{cleaned}",
                    },
                ],
                max_output_tokens=max(64, max_words * 2),
            )
            text = _coerce_response_text(
                getattr(response, "output_text", None) or getattr(response, "output", None)
            )
            if not text:
                text = _coerce_response_text(response)
            raw = _serialize_response(response)
            return text, raw

        summary, raw = await asyncio.to_thread(_call_openai)
        return summary, raw


def get_summarization_engine() -> AISummarizationEngine:
    return AISummarizationEngine()
