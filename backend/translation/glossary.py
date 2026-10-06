"""
Legal-party glossary for machine translation.

NLLB confuses the parties of a contract: measured on three rental
sentences across six languages, "landlord"/"tenant" survived translation
in only 2 of 18 cases (it routinely wrote "pay the tenant" for "pay the
landlord"). Substituting the correct target-language term into the
English BEFORE translation -- so the model copies it instead of
translating it -- raised that to 12 of 18 (all Hindi cases correct).
The role check in translator.py still verifies every result.

Terms were chosen as the everyday words used in Indian rent/employment
agreements; have a native speaker review them like the UI strings.
"""

import re

GLOSSARY = {
    "hindi":   {"landlord": "मकान मालिक", "tenant": "किरायेदार", "employer": "नियोक्ता", "employee": "कर्मचारी"},
    "marathi": {"landlord": "घरमालक", "tenant": "भाडेकरू", "employer": "नियोक्ता", "employee": "कर्मचारी"},
    "tamil":   {"landlord": "வீட்டு உரிமையாளர்", "tenant": "வாடகைதாரர்", "employer": "முதலாளி", "employee": "ஊழியர்"},
    "bengali": {"landlord": "বাড়িওয়ালা", "tenant": "ভাড়াটে", "employer": "নিয়োগকর্তা", "employee": "কর্মী"},
    "telugu":  {"landlord": "ఇంటి యజమాని", "tenant": "అద్దెదారు", "employer": "యజమాని", "employee": "ఉద్యోగి"},
    "kannada": {"landlord": "ಮನೆ ಮಾಲೀಕ", "tenant": "ಬಾಡಿಗೆದಾರ", "employer": "ಉದ್ಯೋಗದಾತ", "employee": "ಉದ್ಯೋಗಿ"},
}

# English variants that mean the same party.
_ALIASES = {
    "landlord": r"landlords?|lessors?",
    "tenant": r"tenants?|lessees?",
    "employer": r"employers?",
    "employee": r"employees?",
}


def apply_glossary(text: str, target_language: str) -> str:
    """Replace party words (and a leading "the") with the target-language term."""
    terms = GLOSSARY.get(target_language)
    if not terms:
        return text
    for role, pattern in _ALIASES.items():
        text = re.sub(rf"\b(?:the\s+)?(?:{pattern})\b", terms[role], text, flags=re.IGNORECASE)
    return text
