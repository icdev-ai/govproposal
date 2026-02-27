#!/usr/bin/env python3
# CUI // SP-PROPIN
"""OpenAI-compatible LLM provider.

Supports any OpenAI-compatible API: OpenAI, Ollama, vLLM, LM Studio, etc.
Used primarily for Ollama (local air-gapped inference).
"""

import json
import logging
import time
from typing import Iterator

from tools.llm.provider import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible REST APIs (Ollama, vLLM, etc.)."""

    def __init__(self, api_key: str = "ollama", base_url: str = "http://localhost:11434/v1",
                 provider_label: str = "openai_compatible"):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._label = provider_label
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        except ImportError:
            logger.warning("openai package not installed; OpenAICompatibleProvider unavailable")
            self._client = None

    @property
    def provider_name(self) -> str:
        return self._label

    def invoke(self, request: LLMRequest, model_id: str, model_config: dict) -> LLMResponse:
        if self._client is None:
            raise RuntimeError("openai package not installed")

        start = time.time()

        # Build messages
        messages = list(request.messages)
        if not messages:
            messages = [{"role": "user", "content": "Hello"}]

        # Prepend system prompt if present
        if request.system_prompt and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": request.system_prompt}] + messages

        try:
            resp = self._client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
            content = resp.choices[0].message.content or ""
            duration_ms = int((time.time() - start) * 1000)

            return LLMResponse(
                content=content,
                model_id=model_id,
                provider=self._label,
                input_tokens=getattr(resp.usage, "prompt_tokens", 0),
                output_tokens=getattr(resp.usage, "completion_tokens", 0),
                duration_ms=duration_ms,
                stop_reason=str(resp.choices[0].finish_reason),
            )
        except Exception as exc:
            raise RuntimeError(f"{self._label} invocation failed: {exc}") from exc

    def invoke_streaming(self, request: LLMRequest, model_id: str,
                         model_config: dict) -> Iterator[dict]:
        if self._client is None:
            raise RuntimeError("openai package not installed")

        messages = list(request.messages)
        if request.system_prompt and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": request.system_prompt}] + messages

        stream = self._client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield {"type": "text", "text": delta.content}
        yield {"type": "message_stop", "model_id": model_id}

    def check_availability(self, model_id: str) -> bool:
        if self._client is None:
            return False
        try:
            models = self._client.models.list()
            ids = [m.id for m in models.data]
            return model_id in ids
        except Exception:
            return False
