"""
High-risk routing flags (Phase 9).

RED risk and low confidence already route to review (risk_rules.py).
These are the remaining conditions from the roadmap, each detected
deterministically (no LLM call) and surfaced as an explicit, named
flag so a reviewer sees exactly which one fired:

  conflicting_sources
      The sources the answer relies on come from different
      jurisdictions (e.g. Delhi Rent Control Act AND the Model Tenancy
      Act), or two versions of the same section were cited. Different
      regimes can prescribe different rules for the same clause, so the
      system shouldn't pick one silently.

  jurisdiction_uncertain
      The answer relies on a state-specific (or model, adopt-if-you-
      want) law, but the contract doesn't establish that it's governed
      by that state. Rent law in particular is state law in India; a
      Delhi rule applied to a Bengaluru flat is wrong even if the
      citation is "valid".

  unverified_source
      A cited source is marked verified=false in the corpus (Phase 4) --
      fine to retrieve, not fine to auto-approve on.
"""

import re

from backend.validation.citation_validator import find_unbacked_references

CENTRAL_JURISDICTIONS = {"india", ""}

FLAG_DESCRIPTIONS = {
    "conflicting_sources": "Cited sources come from different jurisdictions or versions and may conflict.",
    "jurisdiction_uncertain": "Relies on state-specific law, but the contract doesn't establish which state's law applies.",
    "unverified_source": "Relies on a source that hasn't been verified against the official text yet.",
    "unbacked_legal_reference": "The legal assessment mentions a law or section that no cited source supports.",
    "skipped_legal_check": "This kind of clause often raises legal problems, but the AI didn't check the law for it.",
}

# State / UT -> name variants and major cities that indicate it.
STATE_INDICATORS = {
    "Delhi": ["delhi", "new delhi"],
    "Maharashtra": ["maharashtra", "mumbai", "pune", "nagpur", "thane", "navi mumbai"],
    "Karnataka": ["karnataka", "bengaluru", "bangalore", "mysuru", "mysore", "mangaluru"],
    "Tamil Nadu": ["tamil nadu", "chennai", "coimbatore", "madurai"],
    "Telangana": ["telangana", "hyderabad", "secunderabad"],
    "Andhra Pradesh": ["andhra pradesh", "visakhapatnam", "vijayawada"],
    "West Bengal": ["west bengal", "kolkata", "calcutta"],
    "Gujarat": ["gujarat", "ahmedabad", "surat", "vadodara"],
    "Uttar Pradesh": ["uttar pradesh", "noida", "lucknow", "ghaziabad", "kanpur"],
    "Haryana": ["haryana", "gurugram", "gurgaon", "faridabad"],
    "Rajasthan": ["rajasthan", "jaipur", "udaipur", "jodhpur"],
    "Kerala": ["kerala", "kochi", "thiruvananthapuram", "trivandrum"],
    "Punjab": ["punjab", "ludhiana", "amritsar", "mohali"],
    "Chandigarh": ["chandigarh"],
    "Madhya Pradesh": ["madhya pradesh", "bhopal", "indore"],
    "Bihar": ["bihar", "patna"],
    "Odisha": ["odisha", "orissa", "bhubaneswar"],
    "Goa": ["goa", "panaji"],
    "Assam": ["assam", "guwahati"],
}

_STATE_PATTERNS = {
    state: re.compile(r"\b(" + "|".join(re.escape(v) for v in variants) + r")\b", re.I)
    for state, variants in STATE_INDICATORS.items()
}


def detect_states(text: str) -> set[str]:
    """States/UTs the text mentions (by name or a major city)."""
    if not text:
        return set()
    return {state for state, pattern in _STATE_PATTERNS.items() if pattern.search(text)}


def _is_state_specific(source: dict) -> bool:
    return (source.get("jurisdiction") or "").strip().lower() not in CENTRAL_JURISDICTIONS


def _relied_on_sources(claims: list[dict], retrieved_sources: list[dict]) -> list[dict]:
    """Sources actually cited by a claim, de-duplicated by id."""
    by_id = {s["id"]: s for s in retrieved_sources if s.get("id")}
    cited_ids = {sid for c in claims for sid in c.get("supporting_source_ids", [])}
    return [by_id[sid] for sid in sorted(cited_ids) if sid in by_id]


def compute_review_flags(
    claims: list[dict],
    retrieved_sources: list[dict],
    clause_text: str = "",
    known_states: set[str] | None = None,
    legal_assessment: str = "",
) -> list[str]:
    """
    known_states: states already established for the whole document
    (e.g. detected from its full text by the API layer). The clause's
    own text is checked too.
    """
    flags = []
    relied_on = _relied_on_sources(claims, retrieved_sources)

    # Checked even when nothing was cited: an assessment that names a
    # statute with zero citations behind it is exactly the case to catch.
    if find_unbacked_references(legal_assessment, relied_on):
        flags.append("unbacked_legal_reference")

    if not relied_on:
        return flags

    # Central law + one state's law routinely apply together (e.g. the
    # Transfer of Property Act alongside a state rent act), so that alone
    # isn't a conflict. Two DIFFERENT state/model regimes is.
    non_central = {s.get("jurisdiction", "").strip() for s in relied_on if _is_state_specific(s)}
    versions_per_section: dict[tuple, set] = {}
    for s in relied_on:
        versions_per_section.setdefault((s.get("law"), s.get("section")), set()).add(s.get("source_version") or "")
    if len(non_central) >= 2 or any(len(v) > 1 for v in versions_per_section.values()):
        flags.append("conflicting_sources")

    state_specific = [s for s in relied_on if _is_state_specific(s)]
    if state_specific:
        established = set(known_states or set()) | detect_states(clause_text)
        for s in state_specific:
            jurisdiction = s.get("jurisdiction", "")
            # A model act or a state law only applies when the contract's
            # state is known AND that state is the source's state.
            if jurisdiction not in established:
                flags.append("jurisdiction_uncertain")
                break

    if any(s.get("verified") is False for s in relied_on):
        flags.append("unverified_source")

    return flags
