"""
Phase 14 translation validation tests -- the last gap in the original
Phase 1 test checklist. Monkeypatches translator._get_provider with a
fake so this runs without a live Gemini call; the embedding similarity
check itself uses the real (deterministic, fallback) EmbeddingModel,
so the comparison logic is genuinely exercised, not just the plumbing.
"""

import pytest

from backend.translation import translator
from backend.agent.prompts import TRANSLATION_SYSTEM_PROMPT


class FakeTranslationProvider:
    """
    Returns different canned text depending on which system prompt it's
    asked with, so a test can simulate "translation round-trips back to
    (almost) the same meaning" vs. "translation drifted".
    """

    def __init__(self, translated_text: str, back_translated_text: str):
        self._translated_text = translated_text
        self._back_translated_text = back_translated_text
        self.calls = []

    def simple_completion(self, system_prompt, user_input):
        self.calls.append((system_prompt, user_input))
        if system_prompt == TRANSLATION_SYSTEM_PROMPT:
            return self._translated_text
        return self._back_translated_text  # back-translate prompt


def test_identical_back_translation_is_accepted_on_first_attempt(monkeypatch):
    original = "You will be paid fifty thousand rupees per month."
    fake = FakeTranslationProvider(
        translated_text="[Hindi translation placeholder]",
        back_translated_text=original,  # perfect round-trip
    )
    monkeypatch.setattr(translator, "_get_provider", lambda: fake)

    result = translator.translate_and_validate(original, "hindi")

    assert result["validated"] is True
    assert result["attempts"] == 1
    assert result["similarity_score"] == pytest.approx(1.0, abs=1e-6)


def test_drifted_back_translation_is_not_validated(monkeypatch):
    original = "You will be paid fifty thousand rupees per month."
    fake = FakeTranslationProvider(
        translated_text="[Hindi translation placeholder]",
        # Completely unrelated meaning -- should fail the similarity check.
        back_translated_text="The weather in Mumbai is expected to be cloudy tomorrow.",
    )
    monkeypatch.setattr(translator, "_get_provider", lambda: fake)

    result = translator.translate_and_validate(original, "hindi")

    assert result["validated"] is False
    assert result["similarity_score"] < translator.SIMILARITY_ACCEPT_THRESHOLD
    # Should have retried up to the configured max before giving up.
    assert result["attempts"] == translator.MAX_REGENERATION_ATTEMPTS


def test_unsupported_language_is_rejected_before_any_llm_call(monkeypatch):
    fake = FakeTranslationProvider(translated_text="x", back_translated_text="x")
    monkeypatch.setattr(translator, "_get_provider", lambda: fake)

    with pytest.raises(ValueError, match="Unsupported target language"):
        translator.translate_and_validate("some text", "klingon")

    assert fake.calls == []  # never even tried to call the LLM


def test_plain_translate_explanation_does_not_validate(monkeypatch):
    fake = FakeTranslationProvider(translated_text="[translation]", back_translated_text="irrelevant")
    monkeypatch.setattr(translator, "_get_provider", lambda: fake)

    result = translator.translate_explanation("Some plain explanation.", "tamil")

    assert result == "[translation]"
    assert len(fake.calls) == 1  # only the forward translation, no back-translation
