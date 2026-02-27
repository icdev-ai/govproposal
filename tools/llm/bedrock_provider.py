#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
# POC: GovProposal System Administrator
"""Bedrock LLM Provider — AWS Bedrock (GovCloud) integration.

Adapted from ICDEV Phase 38 (Cloud-Agnostic Architecture).
"""

import json
import logging
import os
import time
from typing import Iterator, List

from tools.llm.provider import LLMProvider, LLMRequest, LLMResponse, EmbeddingProvider

logger = logging.getLogger("govproposal.llm.bedrock")

try:
    import boto3
except ImportError:
    boto3 = None


class BedrockLLMProvider(LLMProvider):
    """AWS Bedrock LLM provider for GovCloud."""

    def __init__(self, region: str = "us-gov-west-1"):
        self._region = region
        self._client = None

    @property
    def provider_name(self) -> str:
        return "bedrock"

    def _get_client(self):
        if self._client is None:
            if boto3 is None:
                raise ImportError("boto3 required for Bedrock provider")
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
            )
        return self._client

    def invoke(self, request: LLMRequest, model_id: str, model_config: dict) -> LLMResponse:
        """Invoke Bedrock model."""
        client = self._get_client()
        start = time.time()

        messages = []
        for msg in request.messages:
            content = msg.get("content", "")
            role = msg.get("role", "user")
            if isinstance(content, str):
                messages.append({
                    "role": role,
                    "content": [{"type": "text", "text": content}],
                })
            elif isinstance(content, list):
                messages.append({"role": role, "content": content})

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }

        if request.system_prompt:
            body["system"] = request.system_prompt

        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )

        result = json.loads(response["body"].read())
        elapsed_ms = int((time.time() - start) * 1000)

        content_text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")

        usage = result.get("usage", {})

        return LLMResponse(
            content=content_text,
            model_id=model_id,
            provider="bedrock",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            duration_ms=elapsed_ms,
            stop_reason=result.get("stop_reason", ""),
            classification=request.classification,
        )

    def check_availability(self, model_id: str) -> bool:
        """Check if model is available."""
        try:
            self._get_client()
            return True
        except Exception:
            return False


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock embedding provider (Titan Embed)."""

    def __init__(self, region: str = "us-gov-west-1",
                 model_id: str = "amazon.titan-embed-text-v2:0",
                 dims: int = 1024):
        self._region = region
        self._model_id = model_id
        self._dims = dims
        self._client = None

    @property
    def provider_name(self) -> str:
        return "bedrock"

    @property
    def dimensions(self) -> int:
        return self._dims

    def _get_client(self):
        if self._client is None:
            if boto3 is None:
                raise ImportError("boto3 required for Bedrock embedding provider")
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
            )
        return self._client

    def embed(self, text: str) -> List[float]:
        """Generate embedding via Bedrock."""
        client = self._get_client()
        body = json.dumps({
            "inputText": text,
            "dimensions": self._dims,
        })
        response = client.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(response["body"].read())
        return result.get("embedding", [])

    def check_availability(self) -> bool:
        """Check if embedding model is available."""
        try:
            self._get_client()
            return True
        except Exception:
            return False
