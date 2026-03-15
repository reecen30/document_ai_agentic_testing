"""
Central LLM factory for all agents.

Default profile is cost-aware and cloud-friendly for CrewAI AMP deployment.
"""
from __future__ import annotations

import os

from crewai import LLM


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
            "reasoning": "groq/llama-3.1-8b-instant",
            "structured": "groq/llama-3.1-8b-instant",
            "code": "groq/llama-3.1-8b-instant",
        },
        "openai": {
            "reasoning": "openai/gpt-4o-mini",
            "structured": "openai/gpt-4o-mini",
            "code": "openai/gpt-4o-mini",
        },
        "anthropic": {
            "reasoning": "anthropic/claude-3-5-haiku-latest",
            "structured": "anthropic/claude-3-5-haiku-latest",
            "code": "anthropic/claude-3-5-haiku-latest",
        },
        "ollama": {
            "reasoning": "ollama/deepseek-r1:8b",
            "structured": "ollama/qwen2.5:7b-instruct",
            "code": "ollama/qwen2.5-coder:7b-instruct",
        },
    }
    provider_defaults = defaults.get(provider, defaults["groq"])
    return provider_defaults.get(role, provider_defaults["structured"])


def get_agent_llm(role: str) -> LLM:
    """
    Build an LLM with env-driven model/base_url settings.

    Required env var depends on selected provider (for cloud providers):
    - Groq: GROQ_API_KEY
    - OpenAI: OPENAI_API_KEY
    - Anthropic: ANTHROPIC_API_KEY
    """
    provider = os.getenv("AGENTIC_LLM_PROVIDER", "groq").strip().lower()
    temperature = _env_float("AGENTIC_LLM_TEMPERATURE", 0.1)

    model = os.getenv(f"AGENTIC_{role.upper()}_MODEL")
    if not model:
        model = _default_model_for(role, provider)

    kwargs = {
        "model": model,
        "temperature": temperature,
    }

    # Only set base_url when explicitly provided, or for local ollama fallback.
    explicit_base_url = os.getenv("AGENTIC_LLM_BASE_URL")
    if explicit_base_url:
        kwargs["base_url"] = explicit_base_url
    elif provider == "ollama":
        kwargs["base_url"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    return LLM(**kwargs)
