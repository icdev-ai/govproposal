#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
# POC: GovProposal System Administrator
"""Vendor-agnostic LLM provider base classes and data types.

Adapted from ICDEV Phase 38 (Cloud-Agnostic Architecture).
Defines universal request/response format and abstract interfaces.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class LLMRequest:
    """Vendor-agnostic LLM invocation request."""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    tools: Optional[List[Dict]] = None
    output_schema: Optional[Dict] = None
    stop_sequences: Optional[List[str]] = None
    effort: str = "medium"
    project_id: str = ""
    classification: str = "CUI // SP-PROPIN"


@dataclass
class LLMResponse:
    """Vendor-agnostic LLM invocation response."""
    content: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    structured_output: Optional[Dict] = None
    model_id: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    duration_ms: int = 0
    stop_reason: str = ""
    classification: str = "CUI // SP-PROPIN"


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier."""

    @abstractmethod
    def invoke(self, request: LLMRequest, model_id: str, model_config: dict) -> LLMResponse:
        """Invoke the LLM synchronously."""

    def invoke_streaming(self, request: LLMRequest, model_id: str,
                         model_config: dict) -> Iterator[dict]:
        """Invoke with streaming. Default: falls back to non-streaming."""
        resp = self.invoke(request, model_id, model_config)
        yield {"type": "text", "text": resp.content}
        yield {"type": "message_stop", "model_id": resp.model_id}

    @abstractmethod
    def check_availability(self, model_id: str) -> bool:
        """Check if a specific model is available."""


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensionality."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text."""

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(t) for t in texts]

    @abstractmethod
    def check_availability(self) -> bool:
        """Check if the embedding model is available."""
