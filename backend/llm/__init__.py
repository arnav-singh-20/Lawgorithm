"""
LLM provider selection. Every caller gets its provider from
get_provider(), so switching LLM_PROVIDER switches all of them together.

role="agent" is the clause-analysis ReAct loop; role="light" is the
cheaper work (grounding verifier, translation). Providers with per-model
quotas (Groq) use a different model for each role.
"""

from backend.config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL_AGENT,
    GROQ_MODEL_AGENT_FALLBACKS,
    GROQ_MODEL_LIGHT,
    GROQ_MODEL_LIGHT_FALLBACKS,
    LLM_PROVIDER,
)
from backend.llm.base import LLMProvider, LLMUnavailableError

_cache: dict[str, LLMProvider] = {}


def get_provider(role: str = "agent") -> LLMProvider:
    key = f"{LLM_PROVIDER}:{role}"
    if key not in _cache:
        _cache[key] = _build(role)
    return _cache[key]


def _build(role: str) -> LLMProvider:
    if LLM_PROVIDER == "groq":
        from backend.llm.openai_compat import OpenAICompatibleProvider

        if role == "agent":
            model, fallbacks = GROQ_MODEL_AGENT, GROQ_MODEL_AGENT_FALLBACKS
        else:
            model, fallbacks = GROQ_MODEL_LIGHT, GROQ_MODEL_LIGHT_FALLBACKS
        return OpenAICompatibleProvider(GROQ_BASE_URL, GROQ_API_KEY, model, name="Groq", fallback_models=fallbacks)
    if LLM_PROVIDER == "ollama":
        from backend.llm.ollama import OllamaProvider

        return OllamaProvider()
    if LLM_PROVIDER == "gemini":
        # Imported lazily so the google-genai SDK is only needed when used.
        from backend.llm.gemini import GeminiProvider

        return GeminiProvider()
    raise LLMUnavailableError(
        f"Unknown LLM_PROVIDER '{LLM_PROVIDER}' (use 'groq', 'ollama' or 'gemini').", "model")
