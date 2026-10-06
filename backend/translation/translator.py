"""
Multilingual output (Phase 11) + translation validation (Phase 14).

Important: we translate the ALREADY-VERIFIED plain-language explanation,
never risk_level/confidence/source_id/section numbers/status -- those
stay in their original form and are not passed through the LLM again.

    ORIGINAL CLAUSE -> LEGAL ANALYSIS -> VERIFIED STRUCTURED RESULT
                                              |
                                       plain_explanation
                                              |
                                              v
                                        TRANSLATION
                                              |
                                              v
                              TRANSLATE BACK TO ENGLISH
                                              |
                                              v
                            COMPARE MEANING (embedding similarity)
                                              |
                                    similar enough? -> accept
                                    not similar?     -> regenerate once, then flag

Two engines (TRANSLATION_ENGINE): "nllb", a dedicated local translation
model (default), or "llm", the chat model behind LLM_PROVIDER. Both go
through the same validation below.

On top of the meaning check, every number in the English must survive
translation unchanged (numbers_preserved) -- a translated contract term
with the wrong amount is the most harmful failure there is, and an
embedding similarity score can't be trusted to notice one digit.
"""

import logging
import re

from backend.config import SUPPORTED_LANGUAGES, TRANSLATION_ENGINE
from backend.translation.glossary import apply_glossary
from backend.agent.prompts import TRANSLATION_SYSTEM_PROMPT
from backend.rag.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)

_provider = None


def _get_provider():
    """Lazy singleton -- see backend/agent/agent.py::_get_provider for why."""
    global _provider
    if _provider is None:
        from backend.llm import get_provider

        _provider = get_provider("light")
    return _provider


ENGINE = TRANSLATION_ENGINE
_unavailable: set[str] = set()   # engines that failed to load this process


def _load(engine: str):
    """The engine's translator object, or None if it can't be used here."""
    if engine in _unavailable:
        return None
    try:
        if engine == "indictrans2":
            from backend.translation.indictrans import IndicTrans2Translator

            return IndicTrans2Translator.get()
        if engine == "nllb":
            from backend.translation.nllb import NLLBTranslator

            return NLLBTranslator.get()
    except Exception:
        logger.exception("Translation engine '%s' unavailable; trying the next one.", engine)
        _unavailable.add(engine)
    return None


def _engine_chain() -> list[str]:
    """
    Engines to try, best first. indictrans2 -> nllb -> llm: when a
    translation fails a check, the next engine gets a go, so two
    independent models get a chance to produce a faithful translation.
    """
    chain = {"indictrans2": ["indictrans2", "nllb"], "nllb": ["nllb"]}.get(ENGINE, [])
    available = [e for e in chain if _load(e) is not None]
    return available or ["llm"]


def _forward_with(engine: str, text: str, target_language: str) -> str:
    if engine == "indictrans2":
        try:
            return _load("indictrans2").translate(text, target_language)
        except Exception:
            logger.exception("IndicTrans2 translation failed; disabling it for this process.")
            _unavailable.add("indictrans2")
            raise
    if engine == "nllb":
        # glossary first: NLLB otherwise swaps landlord/tenant (see glossary.py)
        return _load("nllb").translate(apply_glossary(text, target_language), "english", target_language)
    return _get_provider().simple_completion(
        system_prompt=TRANSLATION_SYSTEM_PROMPT,
        user_input=f"Target language: {target_language}\n{party_terms_hint(text, target_language)}"
                   f"\nExplanation to translate:\n{text}",
    )


def party_terms_hint(text: str, target_language: str) -> str:
    """
    The LLM gets the glossary's party words too. Seen live: Groq's model
    wrote "resident" for "landlord" in Tamil, which the role check then
    (correctly) rejected -- telling it the exact words avoids the miss.
    """
    from backend.translation.glossary import GLOSSARY, _ALIASES

    terms = GLOSSARY.get(target_language) or {}
    used = [role for role, pattern in _ALIASES.items() if role in terms and re.search(rf"\b(?:{pattern})\b", text, re.I)]
    if not used:
        return ""
    pairs = "; ".join(f"{role} = {terms[role]}" for role in used)
    return f"Use exactly these words for the parties (never swap them): {pairs}\n"


def _forward(text: str, target_language: str) -> str:
    return _forward_with(_engine_chain()[0], text, target_language)


def _backward(text: str, source_language: str) -> str:
    """
    Back-translation for the meaning check. NLLB when available -- a
    different model from IndicTrans2, so the check isn't a model
    agreeing with itself.
    """
    nllb = _load("nllb") if ENGINE in ("indictrans2", "nllb") else None
    if nllb is not None:
        return nllb.translate(text, source_language, "english")
    return _get_provider().simple_completion(system_prompt=BACK_TRANSLATE_SYSTEM_PROMPT, user_input=text)


# Digits in every script Lawgorithm translates into, mapped to ASCII.
_INDIC_DIGITS = str.maketrans(
    "०१२३४५६७८९" "০১২৩৪৫৬৭৮৯" "௦௧௨௩௪௫௬௭௮௯" "౦౧౨౩౪౫౬౭౮౯" "೦೧೨೩೪೫೬೭೮೯",
    "0123456789" * 5,
)


# "75 हजार" / "৫ লাখ" is how amounts are normally written in Indian
# languages (and English: "5 lakh"). Word stems, so inflected forms
# (వేల/వేలు, లక్షల, कोटी, crores...) match too.
_MULTIPLIERS = [
    (1_000, "thousand|हज़ार|हजार|হাজার|ஆயிர|వేల|వేలు|ಸಾವಿರ"),
    (100_000, "lakhs?|lacs?|लाख|লাখ|লক্ষ|இலட்ச|லட்ச|లక్ష|ಲಕ್ಷ"),
    (10_000_000, "crores?|करोड़|करोड|कोटी|কোটি|கோடி|కోటి|కోట్ల|ಕೋಟಿ"),
]
_NUMBER_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)(?:\s*(" + "|".join(p for _, p in _MULTIPLIERS) + r"))?", re.IGNORECASE
)


def _numbers(text: str) -> list[str]:
    """
    Every number in the text as plain digits: "2,50,000" -> "250000",
    "७५ हजार" -> "75000", "5 lakh" -> "500000".
    """
    out = []
    for digits, word in _NUMBER_RE.findall(text.translate(_INDIC_DIGITS)):
        value = digits.replace(",", "")
        if word:
            factor = next(f for f, pattern in _MULTIPLIERS if re.fullmatch(pattern, word, re.IGNORECASE))
            amount = float(value) * factor
            value = str(int(amount)) if amount.is_integer() else str(amount)
        out.append(value)
    return out


# Who-owes-whom: the parties a contract sentence names. Measured live,
# NLLB translated "give the landlord a deposit" as "give the TENANT a
# deposit" in five of six languages -- and the embedding meaning check
# passed it (landlord/tenant sit close together in embedding space).
ROLE_GROUPS = {
    "landlord": r"\b(landlords?|lessors?|(?:house|property) owners?|owners?)\b",
    "tenant": r"\b(tenants?|lessees?|renters?)\b",
    "employer": r"\b(employers?|company|companies)\b",
    "employee": r"\b(employees?)\b",
}


def roles_preserved(original: str, back_translated: str) -> bool:
    """
    The same parties must appear in the English original and in the
    back-translation: a party that vanishes or appears means the
    translation changed who does what to whom.
    """
    for pattern in ROLE_GROUPS.values():
        in_original = re.search(pattern, original, re.IGNORECASE) is not None
        in_back = re.search(pattern, back_translated, re.IGNORECASE) is not None
        if in_original != in_back:
            return False
    return True


def numbers_preserved(original: str, translated: str) -> bool:
    """
    True when every multi-digit number in the original appears in the
    translation. Single digits are exempt: a correct translation may
    spell them out ("2 years" -> "दो साल"), while the numbers that matter
    -- rent, deposits, penalties, 15/30/90-day periods -- have 2+ digits.
    """
    remaining = _numbers(translated)
    for number in _numbers(original):
        if len(number.replace(".", "")) < 2:
            continue
        if number in remaining:
            remaining.remove(number)
        else:
            return False
    return True

BACK_TRANSLATE_SYSTEM_PROMPT = """
Translate the given text into English. Return ONLY the translation,
nothing else -- no notes, no markdown.
"""

SIMILARITY_ACCEPT_THRESHOLD = 0.75
# ^ Arbitrary starting point, same status as the confidence engine's
# weights (backend/confidence/engine.py) and abstention thresholds --
# an engineering guess, not a calibrated value. To calibrate properly:
# build parallel test cases (English source + human "gold" translation)
# across each supported language, measure what similarity score a human
# reviewer's own translation actually produces vs. a deliberately bad
# one, and set the threshold where it separates the two. Nobody has
# done that yet -- don't treat 0.75 as meaningful until someone does.
MAX_REGENERATION_ATTEMPTS = 2


def translate_explanation(plain_explanation: str, target_language: str) -> str:
    """Plain translation, no validation -- kept for simple/cheap call sites."""
    _validate_language(target_language)
    return _forward(plain_explanation, target_language.strip().lower())


def translate_and_validate(plain_explanation: str, target_language: str) -> dict:
    """
    Phase 14: translate, then back-translate to English and compare
    meaning against the original via embedding cosine similarity. If
    it drifts too far, regenerate (up to MAX_REGENERATION_ATTEMPTS)
    before giving up and flagging it for human review rather than
    silently shipping a translation nobody checked.

    Returns:
        {
            "translated_text": "...",
            "similarity_score": 0.0-1.0,
            "validated": bool,
            "numbers_preserved": bool,
            "roles_preserved": bool,
            "engine": "indictrans2" | "nllb" | "llm",
            "attempts": int,
        }
    """
    _validate_language(target_language)
    language = target_language.strip().lower()

    best_result = None
    attempts = 0
    for engine in _engine_chain():
        # The LLM samples, so a retry can differ; the dedicated models
        # decode deterministically, so they get exactly one go each.
        tries = MAX_REGENERATION_ATTEMPTS if engine == "llm" else 1
        for _ in range(tries):
            attempts += 1
            try:
                translated = _forward_with(engine, plain_explanation, language)
            except Exception:
                break   # engine broke mid-run: move on to the next one
            back_translated = _backward(translated, language)

            similarity = _cosine_similarity(plain_explanation, back_translated)
            numbers_ok = numbers_preserved(plain_explanation, translated)
            roles_ok = roles_preserved(plain_explanation, back_translated)
            result = {
                "translated_text": translated,
                "similarity_score": float(similarity),
                "validated": bool(similarity >= SIMILARITY_ACCEPT_THRESHOLD and numbers_ok and roles_ok),
                "numbers_preserved": numbers_ok,
                "roles_preserved": roles_ok,
                "engine": engine,
                "attempts": attempts,
            }
            if result["validated"]:
                return result

            logger.warning(
                "Translation check failed (engine=%s, similarity=%.2f, numbers=%s, roles=%s).",
                engine, similarity, numbers_ok, roles_ok,
            )
            # Keep whichever attempt scored highest, but always report the
            # TOTAL number of attempts actually made.
            if best_result is None or similarity > best_result["similarity_score"]:
                best_result = result

    if best_result is None:
        raise ValueError("No translation engine could translate this text.")
    best_result["attempts"] = attempts
    # Nothing passed -- return the best one, validated=False, so the caller
    # shows the English as well rather than presenting it as trustworthy.
    return best_result


def _cosine_similarity(text_a: str, text_b: str) -> float:
    embedder = EmbeddingModel.get()
    vec_a, vec_b = embedder.embed([text_a, text_b])

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def _validate_language(target_language: str) -> None:
    if target_language.strip().lower() not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported target language '{target_language}'. "
            f"Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )
