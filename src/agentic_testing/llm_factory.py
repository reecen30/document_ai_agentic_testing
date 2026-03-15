"""
Central LLM factory for all agents.

Default profile is cost-aware and cloud-friendly for CrewAI AMP deployment.
"""
from __future__ import annotations

import os
from typing import Tuple

from crewai import LLM

from .runtime_logging import get_runtime_logger, log_event

LOGGER = get_runtime_logger("llm_factory")

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _default_model_for(role: str, provider: str) -> str:
    """
    Reasonable defaults by provider + workload role.
    """
    provider = provider.lower()
    role = role.lower()

    defaults = {
        "groq": {
            "reasoning": "llama-3.1-8b-instant",
            "structured": "llama-3.1-8b-instant",
            "code": "llama-3.1-8b-instant",
        },
        "deepseek": {
            "reasoning": "deepseek-chat",
            "structured": "deepseek-chat",
            "code": "deepseek-chat",
        },
        "openai": {
            "reasoning": "gpt-4o-mini",
            "structured": "gpt-4o-mini",
            "code": "gpt-4o-mini",
        },
        "anthropic": {
            "reasoning": "claude-3-5-haiku-latest",
            "structured": "claude-3-5-haiku-latest",
            "code": "claude-3-5-haiku-latest",
        },
        "ollama": {
            "reasoning": "deepseek-r1:8b",
            "structured": "qwen2.5:7b-instruct",
            "code": "qwen2.5-coder:7b-instruct",
        },
    }
    provider_defaults = defaults.get(provider, defaults["groq"])
    return provider_defaults.get(role, provider_defaults["structured"])


def _strip_known_prefix(model: str) -> Tuple[str, str | None]:
    """
    Accept both prefixed and plain model names.

    Examples:
    - groq/llama-3.1-8b-instant -> (llama-3.1-8b-instant, groq)
    - gpt-4o-mini -> (gpt-4o-mini, None)
    """
    cleaned = (model or "").strip().strip("'").strip('"')
    if "/" not in cleaned:
        return cleaned, None
    prefix, _, rest = cleaned.partition("/")
    normalized_prefix = prefix.strip().lower()
    if normalized_prefix in {"groq", "deepseek", "openai", "anthropic", "claude", "ollama"} and rest:
        return rest.strip(), normalized_prefix
    return cleaned, None


def get_agent_llm(role: str) -> LLM:
    """
    Build an LLM with env-driven model/base_url settings.

    Required env var depends on selected provider (for cloud providers):
    - Groq: GROQ_API_KEY
    - OpenAI: OPENAI_API_KEY
    - Anthropic: ANTHROPIC_API_KEY
    """
    configured_provider = os.getenv("AGENTIC_LLM_PROVIDER", "groq").strip().lower()
    temperature = _env_float("AGENTIC_LLM_TEMPERATURE", 0.1)

    model = os.getenv(f"AGENTIC_{role.upper()}_MODEL")
    if not model:
        model = _default_model_for(role, configured_provider)
    model, detected_prefix = _strip_known_prefix(model)
    provider = detected_prefix or configured_provider

    kwargs = {
        "model": model,
        "temperature": temperature,
    }

    # Only set base_url when explicitly provided, or for provider-specific defaults.
    explicit_base_url = os.getenv("AGENTIC_LLM_BASE_URL")
    if explicit_base_url:
        kwargs["base_url"] = explicit_base_url
    elif provider == "groq":
        # Use OpenAI-compatible Groq endpoint to avoid LiteLLM dependency.
        kwargs["base_url"] = "https://api.groq.com/openai/v1"
    elif provider == "deepseek":
        kwargs["base_url"] = "https://api.deepseek.com/v1"
    elif provider == "ollama":
        # Local OpenAI-compatible Ollama endpoint.
        kwargs["base_url"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    # Provider-specific auth and routing.
    if provider == "groq":
        # Force native OpenAI provider path in CrewAI (no LiteLLM required).
        kwargs["provider"] = "openai"
        groq_key = os.getenv("GROQ_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
        if groq_key:
            kwargs["api_key"] = groq_key
    elif provider == "deepseek":
        kwargs["provider"] = "openai"
        deepseek_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
        if deepseek_key:
            kwargs["api_key"] = deepseek_key
    elif provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
        if openai_key:
            kwargs["api_key"] = openai_key
    elif provider in {"anthropic", "claude"}:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
        if anthropic_key:
            kwargs["api_key"] = anthropic_key
    elif provider == "ollama":
        kwargs["provider"] = "openai"
        kwargs["api_key"] = os.getenv("OLLAMA_API_KEY", "ollama")

    try:
        llm = LLM(**kwargs)
        log_event(
            LOGGER,
            event="llm_initialized",
            level="INFO",
            stage="get_agent_llm",
            context={
                "role": role,
                "provider": provider,
                "configured_provider": configured_provider,
                "model": model,
                "detected_model_prefix": detected_prefix,
                "has_base_url": "base_url" in kwargs,
                "uses_openai_provider_path": kwargs.get("provider") == "openai",
                "has_api_key": "api_key" in kwargs and bool(kwargs.get("api_key")),
                "temperature": temperature,
            },
        )
        return llm
    except Exception as exc:
        log_event(
            LOGGER,
            event="llm_initialization_failed",
            level="ERROR",
            stage="get_agent_llm",
            context={
                "role": role,
                "provider": provider,
                "configured_provider": configured_provider,
                "model": model,
                "detected_model_prefix": detected_prefix,
                "has_base_url": "base_url" in kwargs,
                "uses_openai_provider_path": kwargs.get("provider") == "openai",
                "has_api_key": "api_key" in kwargs and bool(kwargs.get("api_key")),
                "temperature": temperature,
            },
            exc=exc,
        )
        # Last-chance self-heal: if we ever see a prefixed model + LiteLLM import
        # error pattern, retry once using OpenAI-compatible routing.
        if detected_prefix in {"groq", "deepseek", "ollama"} and "LiteLLM fallback package is not installed" in str(exc):
            retry_kwargs = {
                "model": model,
                "temperature": temperature,
                "provider": "openai",
            }
            if explicit_base_url:
                retry_kwargs["base_url"] = explicit_base_url
            elif detected_prefix == "groq":
                retry_kwargs["base_url"] = "https://api.groq.com/openai/v1"
            elif detected_prefix == "deepseek":
                retry_kwargs["base_url"] = "https://api.deepseek.com/v1"
            else:
                retry_kwargs["base_url"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

            if detected_prefix == "groq":
                retry_key = os.getenv("GROQ_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
            elif detected_prefix == "deepseek":
                retry_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AGENTIC_LLM_API_KEY")
            else:
                retry_key = os.getenv("OLLAMA_API_KEY", "ollama")
            if retry_key:
                retry_kwargs["api_key"] = retry_key

            try:
                llm = LLM(**retry_kwargs)
                log_event(
                    LOGGER,
                    event="llm_initialized_retry_success",
                    level="WARNING",
                    stage="get_agent_llm.retry",
                    context={
                        "role": role,
                        "provider": provider,
                        "detected_model_prefix": detected_prefix,
                        "model": model,
                        "has_base_url": "base_url" in retry_kwargs,
                        "has_api_key": "api_key" in retry_kwargs and bool(retry_kwargs.get("api_key")),
                    },
                )
                return llm
            except Exception as retry_exc:
                log_event(
                    LOGGER,
                    event="llm_initialization_retry_failed",
                    level="ERROR",
                    stage="get_agent_llm.retry",
                    context={
                        "role": role,
                        "provider": provider,
                        "detected_model_prefix": detected_prefix,
                        "model": model,
                    },
                    exc=retry_exc,
                )
                raise retry_exc

        raise
