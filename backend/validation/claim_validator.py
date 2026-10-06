"""
Grounding verification (Phase 6).

Citation validity (citation_validator.py) only proves a claim points
at something that was really retrieved. It says nothing about whether
that source's text actually supports what the claim asserts -- a model
can cite a real, retrieved section and still misdescribe what it says.
This module checks that.

For each claim with valid citations, ask the LLM (as an independent
verifier call, not the same call that produced the claim) whether the
cited source text actually supports the claim, and how strongly.
Falls back to a crude lexical-overlap heuristic if the verifier call
fails or can't be parsed, so a bad LLM response degrades gracefully to
"probably not well supported" rather than crashing the pipeline.

IMPORTANT CAVEAT: this verifier is itself an LLM call, and LLM
verifiers make mistakes too. "The verifier said SUPPORTED" is evidence,
not proof -- it should not be treated as 100% ground truth. The
verifier's own accuracy needs to be checked against the evaluation
benchmark (Phase 15/16) just like the primary agent's does, once real
gold data exists. Until then, the strongest available setup is:
    deterministic checks (citation_validator) + LLM verifier (this
    module) + eventual evaluation against expert-labelled data
-- and only the third piece proves the first two are actually working,
rather than just agreeing with each other.
"""

import json
import logging
from typing import List

from backend.llm.base import LLMUnavailableError
from backend.rag.retrieval import excerpt

logger = logging.getLogger(__name__)

VERDICT_SCORES = {
    "SUPPORTED": 1.0,
    "PARTIALLY_SUPPORTED": 0.5,
    "UNSUPPORTED": 0.0,
}

VERIFIER_SYSTEM_PROMPT = """
You are a strict legal fact-checker. You will be given one or more
claims, each with the exact text of the statutory source(s) cited to
support it.

For each claim, decide:
- SUPPORTED: the cited source text clearly supports the claim as stated.
- PARTIALLY_SUPPORTED: the source is topically related but doesn't
  fully support the specific assertion made (e.g. it's about the right
  general subject but doesn't establish the specific consequence claimed).
- UNSUPPORTED: the source text does not support the claim at all.

Be strict. A source being on the same general topic is not enough for
SUPPORTED -- the source text must actually say what the claim asserts.

Return ONLY a JSON array, no markdown fences, in this exact shape:
[
  {"claim_index": 0, "verdict": "SUPPORTED", "reason": "..."},
  {"claim_index": 1, "verdict": "UNSUPPORTED", "reason": "..."}
]
"""


def verify_grounding(claims: List[dict], retrieved_sources: List[dict]) -> List[dict]:
    """
    Returns one verdict dict per claim:
        {"claim": ..., "source_ids": [...], "verdict": "SUPPORTED"|..., "score": 0.0-1.0}
    in the same order as `claims`.
    """
    sources_by_id = {s["id"]: s for s in retrieved_sources if s.get("id")}

    verdicts = [None] * len(claims)
    verifiable_indices = []
    prompt_claims = []

    for i, claim in enumerate(claims):
        source_ids = claim.get("supporting_source_ids", [])
        cited_sources = [sources_by_id[sid] for sid in source_ids if sid in sources_by_id]

        if not cited_sources:
            # No valid citation to check against -- automatically unsupported.
            verdicts[i] = _verdict(claim, source_ids, "UNSUPPORTED")
            continue

        verifiable_indices.append(i)
        prompt_claims.append(
            {
                "claim_index": i,
                "claim": claim.get("claim", ""),
                "sources": [{"source_id": s["id"], "text": excerpt(s["text"], claim.get("claim", ""))}
                            for s in cited_sources],
            }
        )

    if prompt_claims:
        llm_results = _call_verifier(prompt_claims)
        for i in verifiable_indices:
            source_ids = claims[i].get("supporting_source_ids", [])
            verdict_label = llm_results.get(i)
            if verdict_label is None:
                # Verifier didn't return this index (parse failure, etc.)
                # -- fall back to a crude lexical-overlap heuristic rather
                # than silently assuming it's fine.
                verdict_label = _heuristic_verdict(claims[i], sources_by_id, source_ids)
            verdicts[i] = _verdict(claims[i], source_ids, verdict_label)

    return verdicts


def grounding_score_and_status(verdicts: List[dict]) -> tuple[float, str]:
    """
    Aggregates per-claim verdicts into one grounding_score (0-1) and one
    grounding_status label for the whole clause.
    """
    if not verdicts:
        return 0.0, "unsupported"

    avg_score = sum(v["score"] for v in verdicts) / len(verdicts)

    if all(v["verdict"] == "SUPPORTED" for v in verdicts):
        status = "supported"
    elif all(v["verdict"] == "UNSUPPORTED" for v in verdicts):
        status = "unsupported"
    else:
        status = "partially_supported"

    return avg_score, status


def _verdict(claim: dict, source_ids: list, verdict_label: str) -> dict:
    return {
        "claim": claim.get("claim", ""),
        "source_ids": source_ids,
        "verdict": verdict_label,
        "score": VERDICT_SCORES.get(verdict_label, 0.0),
    }


def _call_verifier(prompt_claims: List[dict]) -> dict:
    """Returns {claim_index: verdict_label}. Empty dict on any failure."""
    try:
        # Imported lazily, not at module load time, so anything that only
        # needs the pure scoring functions in this module (e.g.
        # grounding_score_and_status in unit tests) can do so without the
        # Gemini SDK installed at all. The live pipeline still imports it
        # normally the first time this actually runs.
        from backend.llm import get_provider

        provider = get_provider("light")
        response_text = provider.simple_completion(
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            user_input=json.dumps(prompt_claims, indent=2),
        )
        parsed = json.loads(_strip_fences(response_text))
        return {
            item["claim_index"]: item["verdict"]
            for item in parsed
            if item.get("verdict") in VERDICT_SCORES
        }
    except LLMUnavailableError:
        # Model unusable altogether -- surface it like every other LLM
        # call instead of silently grading every claim by word overlap.
        raise
    except Exception:
        logger.exception("Grounding verifier call failed; falling back to heuristic scoring.")
        return {}


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _heuristic_verdict(claim: dict, sources_by_id: dict, source_ids: list) -> str:
    """
    Last-resort fallback when the verifier LLM call fails entirely:
    crude word-overlap between the claim and the cited source text.
    Deliberately conservative -- this is NOT a substitute for the LLM
    verifier, only a way to avoid crashing/over-trusting when it's
    unavailable.
    """
    claim_words = set(claim.get("claim", "").lower().split())
    if not claim_words:
        return "UNSUPPORTED"

    best_overlap = 0.0
    for sid in source_ids:
        source = sources_by_id.get(sid)
        if not source:
            continue
        source_words = set(source["text"].lower().split())
        if not source_words:
            continue
        overlap = len(claim_words & source_words) / len(claim_words)
        best_overlap = max(best_overlap, overlap)

    if best_overlap >= 0.4:
        return "PARTIALLY_SUPPORTED"
    return "UNSUPPORTED"
