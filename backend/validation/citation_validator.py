"""
Citation validator (Phase 5) -- deterministic, no LLM call.

Checks the cheap thing first: does every source_id a claim cites
actually correspond to something that was retrieved during this
clause's ReAct loop? This catches the most common and most avoidable
hallucination -- the model inventing a section number or citing one it
never actually saw -- without spending a model call on it.

This does NOT check whether the cited source actually supports the
claim's content -- that's claim_validator.py (grounding verification,
Phase 6). A citation can pass this check and still be wrong.
"""

import re
from typing import List


def validate_citations(claims: List[dict], retrieved_source_ids: set) -> bool:
    """
    Returns True only if every supporting_source_id on every claim
    exists in the set of source_ids actually retrieved this run.

    An empty claims list is considered valid (nothing to invalidate) --
    that's a grounding/abstention concern, not a citation-fabrication
    concern, and is handled separately by claim_validator + the
    abstention logic in agent.py.
    """
    for claim in claims:
        for source_id in claim.get("supporting_source_ids", []):
            if source_id not in retrieved_source_ids:
                return False

    return True


def find_invalid_citations(claims: List[dict], retrieved_source_ids: set) -> List[dict]:
    """
    Same check, but returns the offending (claim, source_id) pairs
    instead of a single bool -- useful for surfacing to a human
    reviewer or logging exactly what was fabricated.
    """
    invalid = []
    for claim in claims:
        for source_id in claim.get("supporting_source_ids", []):
            if source_id not in retrieved_source_ids:
                invalid.append({"claim": claim.get("claim"), "invalid_source_id": source_id})

    return invalid


# --- legal references inside free text (legal_assessment) ---------------
#
# validate_citations() only covers structured claims. The model's
# free-text legal_assessment can still name a section or Act that no
# claim cites -- e.g. a small local model answering a non-compete
# question by also invoking "Section 23 of the Model Tenancy Act". Those
# references were never validated by anything. This check is the same
# idea as citation validation, applied to prose: every Act/Section the
# text names must be one a claim actually cited.

_SECTION_RE = re.compile(r"\b(?:sections?|secs?\.?|s\.)\s*(\d+[A-Z]?)", re.IGNORECASE)
_ACT_RE = re.compile(
    r"\b([A-Z][\w()'-]*\s+(?:(?:[A-Z][\w()'-]*|of|and|for|the|on|in)\s+){0,7}?Act)\b(?:,?\s*(\d{4}))?"
)
_ACT_STOPWORDS = {"the", "of", "and", "act"}


def _act_key(name: str) -> frozenset:
    words = re.findall(r"[a-z]+", name.lower())
    return frozenset(w for w in words if w not in _ACT_STOPWORDS)


def find_unbacked_references(text: str, cited_sources: List[dict]) -> List[str]:
    """
    Returns the Act names / section numbers mentioned in `text` that are
    not among `cited_sources` (each with "law" and "section"). Section
    numbers are matched by number only, so "Section 27" is backed by any
    cited s.27 -- deliberately lenient; the point is catching references
    to law that was never retrieved and cited at all.
    """
    if not text:
        return []

    cited_sections = {str(s.get("section", "")).strip().upper() for s in cited_sources}
    cited_acts = [_act_key(s.get("law") or "") for s in cited_sources]

    unbacked = []
    for number in dict.fromkeys(m.group(1).upper() for m in _SECTION_RE.finditer(text)):
        if number not in cited_sections:
            unbacked.append(f"Section {number}")

    for match in _ACT_RE.finditer(text):
        name = re.sub(r"^(?:The|Under|Of|In|By|And|Per)\s+", "", match.group(1).strip())
        key = _act_key(name)
        if not key:
            continue
        # backed when a cited law's distinctive words contain this mention's
        # (e.g. "Contract Act" is backed by "Indian Contract Act, 1872")
        if not any(key <= cited for cited in cited_acts if cited):
            label = f"{name}, {match.group(2)}" if match.group(2) else name
            if label not in unbacked:
                unbacked.append(label)

    return unbacked
