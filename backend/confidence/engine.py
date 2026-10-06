"""
Confidence engine (Phase 7) and abstention routing (Phase 8).

Deliberately NOT `confidence = llm_confidence`. The model's own
self-rating is only 10% of the final score -- most of the weight goes
to things Lawgorithm can actually verify (did retrieval find anything
close, do the citations check out, does the cited text really support
the claim), not things the model merely asserts about itself.

Weights are a documented starting point, not scientifically calibrated
values -- Phase 17 (calibrate against real accuracy on the evaluation
set once it exists) is expected to adjust them.
"""

from dataclasses import dataclass

WEIGHTS = {
    "retrieval": 0.30,
    "grounding": 0.30,
    "citation": 0.20,
    "consistency": 0.10,
    "llm_confidence": 0.10,
}

# Abstention thresholds (Phase 8). Also a starting point -- tune once
# you have enough evaluation data to see how these correlate with
# actual correctness (Phase 17).
GROUNDED_THRESHOLD = 0.95
PARTIALLY_GROUNDED_THRESHOLD = 0.80
MIN_GROUNDING_SCORE_FOR_AUTO = 0.80

GROUNDED = "grounded"
PARTIALLY_GROUNDED = "partially_grounded"
INSUFFICIENT_GROUNDING = "insufficient_grounding"
HUMAN_REVIEW_REQUIRED = "human_review_required"


@dataclass
class ConfidenceInputs:
    retrieval_score: float       # how close/relevant was the best retrieved match (0-1)
    grounding_score: float       # from claim_validator.grounding_score_and_status
    citation_valid: bool         # from citation_validator.validate_citations
    consistency_score: float     # internal self-consistency of the output (0-1)
    llm_confidence: float        # the model's own self-rating (0-1)


def calculate_confidence(inputs: ConfidenceInputs) -> float:
    citation_score = 1.0 if inputs.citation_valid else 0.0

    score = (
        inputs.retrieval_score * WEIGHTS["retrieval"]
        + inputs.grounding_score * WEIGHTS["grounding"]
        + citation_score * WEIGHTS["citation"]
        + inputs.consistency_score * WEIGHTS["consistency"]
        + inputs.llm_confidence * WEIGHTS["llm_confidence"]
    )

    return max(0.0, min(1.0, score))


def determine_status(
    confidence: float,
    citation_valid: bool,
    grounding_score: float,
) -> str:
    """
    Four-way abstention outcome (Phase 8). The core principle: uncertain
    means don't guess -- route to a human rather than let the model
    paper over missing evidence with a confident-sounding answer.
    """
    if not citation_valid:
        # The model cited a source that was never actually retrieved --
        # this is the clearest sign of fabrication and always needs a
        # human, regardless of how confident everything else looks.
        return HUMAN_REVIEW_REQUIRED

    if grounding_score < MIN_GROUNDING_SCORE_FOR_AUTO:
        return INSUFFICIENT_GROUNDING

    if confidence >= GROUNDED_THRESHOLD:
        return GROUNDED

    if confidence >= PARTIALLY_GROUNDED_THRESHOLD:
        return PARTIALLY_GROUNDED

    return HUMAN_REVIEW_REQUIRED
