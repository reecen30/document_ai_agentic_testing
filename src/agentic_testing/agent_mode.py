"""
Agent execution mode helpers.

For some providers/models (notably low-cost Groq/DeepSeek options), strict tool
schema + structured-output combinations can fail. This module enables a
deterministic fallback mode for stable demo/runtime behavior.
"""

from __future__ import annotations

import os


def _infer_provider_from_env() -> str:
    provider = (os.getenv("AGENTIC_LLM_PROVIDER", "") or "").strip().lower()
    if provider:
        return provider

    base_url = (os.getenv("AGENTIC_LLM_BASE_URL", "") or "").strip().lower()
    if "api.groq.com" in base_url:
        return "groq"
    if "api.deepseek.com" in base_url:
        return "deepseek"

    model_envs = (
        "AGENTIC_REASONING_MODEL",
        "AGENTIC_STRUCTURED_MODEL",
        "AGENTIC_CODE_MODEL",
        "AGENTIC_LLM_MODEL",
    )
    for name in model_envs:
        value = (os.getenv(name, "") or "").strip().lower()
        if value.startswith("groq/"):
            return "groq"
        if value.startswith("deepseek/"):
            return "deepseek"

    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    return "groq"


def use_deterministic_mode() -> bool:
    """
    Determine whether agent runners should use deterministic Python logic instead
    of LLM tool-calling flows.

    Control via:
    - `AGENTIC_DETERMINISTIC_ONLY=true|false|auto` (default: auto)
    - In auto mode, enable for providers with known strict tool/schema limits.
    """
    mode = (os.getenv("AGENTIC_DETERMINISTIC_ONLY", "auto") or "auto").strip().lower()
    if mode in {"1", "true", "yes", "y", "on"}:
        return True
    if mode in {"0", "false", "no", "n", "off"}:
        return False

    provider = _infer_provider_from_env()
    return provider in {"groq", "deepseek"}
