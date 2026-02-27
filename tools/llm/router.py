#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
# POC: GovProposal System Administrator
"""Config-driven LLM router for GovProposal.

Reads args/llm_config.yaml and resolves each function to a
provider + model via fallback chain. Probes provider availability
and caches results.

Adapted from ICDEV Phase 38 (Cloud-Agnostic Architecture).
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None

from tools.llm.provider import LLMProvider, LLMRequest, LLMResponse, EmbeddingProvider

logger = logging.getLogger("govproposal.llm.router")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "args" / "llm_config.yaml"


def _expand_env(value):
    """Expand ${VAR:-default} patterns in string values."""
    if not isinstance(value, str):
        return value
    pattern = r'\$\{([^}]+)\}'
    def replacer(match):
        expr = match.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.environ.get(var, default)
        return os.environ.get(expr, match.group(0))
    return re.sub(pattern, replacer, value)


class LLMRouter:
    """Config-driven router mapping GovProposal functions to LLM providers."""

    def __init__(self, config_path=None):
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: Dict = {}
        self._providers: Dict[str, LLMProvider] = {}
        self._embedding_providers: Dict[str, EmbeddingProvider] = {}
        self._availability_cache: Dict[str, bool] = {}
        self._availability_cache_time: float = 0.0
        self._cache_ttl: float = 1800.0
        self._load_config()

    def _load_config(self):
        """Load and parse llm_config.yaml."""
        if yaml is None:
            logger.warning("PyYAML not available — using empty LLM config")
            self._config = {}
            return
        if not self._config_path.exists():
            logger.warning("LLM config not found at %s — using empty config", self._config_path)
            self._config = {}
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            self._cache_ttl = float(
                self._config.get("settings", {}).get(
                    "availability_cache_ttl_seconds", 1800
                )
            )
        except Exception as exc:
            logger.error("Failed to load LLM config: %s", exc)
            self._config = {}

    def _get_provider(self, provider_name: str) -> Optional[LLMProvider]:
        """Get or create a provider instance by name."""
        if provider_name in self._providers:
            return self._providers[provider_name]

        provider_cfg = self._config.get("providers", {}).get(provider_name, {})
        if not provider_cfg:
            return None

        ptype = provider_cfg.get("type", "")
        instance = None

        try:
            if ptype == "bedrock":
                from tools.llm.bedrock_provider import BedrockLLMProvider
                region = _expand_env(provider_cfg.get("region", "us-gov-west-1"))
                instance = BedrockLLMProvider(region=region)

            elif ptype in ("openai", "openai_compatible"):
                from tools.llm.openai_provider import OpenAICompatibleProvider
                api_key = provider_cfg.get("api_key", "")
                if not api_key:
                    api_key_env = provider_cfg.get("api_key_env", "")
                    if api_key_env:
                        api_key = os.environ.get(api_key_env, "")
                base_url = _expand_env(provider_cfg.get("base_url", "https://api.openai.com/v1"))
                instance = OpenAICompatibleProvider(
                    api_key=api_key, base_url=base_url, provider_label=provider_name,
                )

            elif ptype == "anthropic":
                from tools.llm.anthropic_provider import AnthropicLLMProvider
                api_key_env = provider_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
                api_key = os.environ.get(api_key_env, "")
                instance = AnthropicLLMProvider(api_key=api_key)

            elif ptype == "ollama":
                from tools.llm.openai_provider import OpenAICompatibleProvider
                base_url = _expand_env(provider_cfg.get("base_url", "http://localhost:11434/v1"))
                instance = OpenAICompatibleProvider(
                    api_key="ollama", base_url=base_url, provider_label="ollama",
                )

        except ImportError as exc:
            logger.warning("Could not import provider '%s': %s", provider_name, exc)
            return None
        except Exception as exc:
            logger.warning("Failed to create provider '%s': %s", provider_name, exc)
            return None

        if instance:
            self._providers[provider_name] = instance
        return instance

    def _get_model_config(self, model_name: str) -> dict:
        return self._config.get("models", {}).get(model_name, {})

    def _check_model_available(self, model_name: str) -> bool:
        now = time.time()
        if (now - self._availability_cache_time) > self._cache_ttl:
            self._availability_cache = {}
            self._availability_cache_time = now

        if model_name in self._availability_cache:
            return self._availability_cache[model_name]

        model_cfg = self._get_model_config(model_name)
        if not model_cfg:
            self._availability_cache[model_name] = False
            return False

        provider_name = model_cfg.get("provider", "")
        provider = self._get_provider(provider_name)
        if provider is None:
            self._availability_cache[model_name] = False
            return False

        try:
            available = provider.check_availability(model_cfg.get("model_id", ""))
            self._availability_cache[model_name] = available
            return available
        except Exception:
            self._availability_cache[model_name] = False
            return False

    def get_provider_for_function(self, function: str) -> Tuple[Optional[LLMProvider], str, dict]:
        """Resolve function to (provider, model_id, model_config)."""
        routing = self._config.get("routing", {})
        route = routing.get(function, routing.get("default", {}))
        chain = route.get("chain", [])

        if not chain:
            return None, "", {}

        for model_name in chain:
            if self._check_model_available(model_name):
                model_cfg = self._get_model_config(model_name)
                provider_name = model_cfg.get("provider", "")
                provider = self._get_provider(provider_name)
                if provider:
                    return provider, model_cfg.get("model_id", ""), model_cfg

        # Fallback: try first model without availability check
        if chain:
            model_name = chain[0]
            model_cfg = self._get_model_config(model_name)
            provider_name = model_cfg.get("provider", "")
            provider = self._get_provider(provider_name)
            if provider:
                return provider, model_cfg.get("model_id", ""), model_cfg

        return None, "", {}

    def _scan_for_injection(self, request: LLMRequest) -> Optional[str]:
        """Scan request messages for prompt injection patterns."""
        try:
            from tools.security.prompt_injection_detector import PromptInjectionDetector
        except ImportError:
            return None

        detector = PromptInjectionDetector()
        texts = []
        for msg in (request.messages or []):
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    texts.append(content)

        if not texts:
            return "allow"

        combined = "\n".join(texts)
        result = detector.scan_text(combined, source="llm_router")

        if result["detected"]:
            logger.warning(
                "Prompt injection detected: confidence=%.2f action=%s findings=%d",
                result["confidence"], result["action"], result["finding_count"],
            )
            detector.log_detection(result, project_id=request.project_id)

        return result["action"]

    def invoke(self, function: str, request: LLMRequest) -> LLMResponse:
        """Resolve provider for function and invoke with fallback."""
        # Scan for prompt injection before invoking
        injection_action = self._scan_for_injection(request)
        if injection_action == "block":
            raise RuntimeError(
                "Prompt injection detected with high confidence — request blocked."
            )

        routing = self._config.get("routing", {})
        route = routing.get(function, routing.get("default", {}))
        chain = route.get("chain", [])
        last_error = None

        for model_name in chain:
            model_cfg = self._get_model_config(model_name)
            if not model_cfg:
                continue
            provider_name = model_cfg.get("provider", "")
            provider = self._get_provider(provider_name)
            if provider is None:
                continue
            model_id = model_cfg.get("model_id", "")
            try:
                response = provider.invoke(request, model_id, model_cfg)
                return response
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for %s: %s — trying next",
                    provider_name, function, exc,
                )
                last_error = exc
                self._availability_cache[model_name] = False
                continue

        raise RuntimeError(
            f"All providers in chain {chain} failed for function '{function}'. "
            f"Last error: {last_error}"
        )

    def get_embedding_provider(self) -> EmbeddingProvider:
        """Get the first available embedding provider."""
        emb_cfg = self._config.get("embeddings", {})
        chain = emb_cfg.get("default_chain", [])
        models = emb_cfg.get("models", {})

        for model_name in chain:
            if model_name in self._embedding_providers:
                return self._embedding_providers[model_name]

            mcfg = models.get(model_name, {})
            if not mcfg:
                continue

            provider_name = mcfg.get("provider", "")
            ptype = self._config.get("providers", {}).get(provider_name, {}).get("type", "")

            try:
                emb = None
                if ptype == "bedrock":
                    from tools.llm.bedrock_provider import BedrockEmbeddingProvider
                    pcfg = self._config.get("providers", {}).get(provider_name, {})
                    region = _expand_env(pcfg.get("region", "us-gov-west-1"))
                    emb = BedrockEmbeddingProvider(
                        region=region,
                        model_id=mcfg.get("model_id", "amazon.titan-embed-text-v2:0"),
                        dims=mcfg.get("dimensions", 1024),
                    )

                if emb and emb.check_availability():
                    self._embedding_providers[model_name] = emb
                    return emb
            except Exception as exc:
                logger.debug("Embedding provider '%s' failed: %s", model_name, exc)

        raise RuntimeError(
            "No embedding provider available. Check llm_config.yaml embeddings section."
        )
