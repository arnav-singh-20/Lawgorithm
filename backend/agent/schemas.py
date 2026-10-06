"""
Structured output contract for a single clause analysis (Phase 8/9/10
+ trust layer: claims, citations, confidence engine, abstention).

Two layers of fields here, deliberately kept separate:

  - what the MODEL produces (plain_explanation, risk_level,
    legal_assessment, claims, llm_confidence) -- everything the LLM is
    asked to self-report in agent/prompts.py.

  - what LAWGORITHM computes AFTER the model answers (grounding_status,
    status, confidence, verification_status) -- these come from
    backend/validation/ and backend/confidence/engine.py running
    against the model's claims and the sources actually retrieved.
    Never trust the model's self-rated confidence alone for these.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class Claim(BaseModel):
    claim: str
    supporting_source_ids: List[str] = Field(default_factory=list)


# --- what the model is asked to produce ---
# Deliberately does NOT include retrieved_source_ids: Lawgorithm already
# knows exactly which sources were retrieved (it made the tool calls),
# so asking the model to also report that list is redundant output
# surface for no benefit -- and if the model's list ever disagreed with
# reality, that's a bug we'd want to just not have, not something to
# validate after the fact. _finalize() in agent.py builds
# retrieved_source_ids straight from context["retrieved_sources"].
class ModelClauseOutput(BaseModel):
    plain_explanation: str
    risk_level: str = Field(pattern="^(red|amber|green)$")
    legal_assessment: str
    # Phase 18: what the person signing should actually DO about this
    # clause ("ask for the lock-in to be reduced to 6 months"), as
    # opposed to what it means (plain_explanation) or what the law says
    # (legal_assessment).
    recommended_action: str = ""
    # What happens if the person signs it unchanged -- completes "If you
    # don't fix it, ..." in the human-in-the-loop answer. Empty for green.
    consequence: str = ""
    claims: List[Claim] = Field(default_factory=list)
    llm_confidence: float = Field(ge=0.0, le=1.0)


class CitedSource(BaseModel):
    """Display details for a source a claim actually cited (Phase 17)."""
    id: str
    law: Optional[str] = None
    section: Optional[str] = None
    title: Optional[str] = None
    jurisdiction: Optional[str] = None
    official_source: Optional[str] = None
    text: Optional[str] = None


class ClauseTypeHint(BaseModel):
    """
    Clause type predicted from the precedent index (rag/clause_index.py).
    Identification only -- never legal grounding, never citable.
    """
    clause_type: Optional[str] = None
    label: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# --- final result after validation + confidence engine ---
class ClauseAnalysisResult(BaseModel):
    clause_id: Optional[str] = None
    clause_title: Optional[str] = None

    plain_explanation: str
    risk_level: str = Field(pattern="^(red|amber|green)$")
    legal_assessment: str
    recommended_action: str = ""
    consequence: str = ""

    clause_type: Optional[ClauseTypeHint] = None

    claims: List[Claim] = Field(default_factory=list)
    retrieved_source_ids: List[str] = Field(default_factory=list)
    cited_sources: List[CitedSource] = Field(default_factory=list)

    # Per-factor scores that fed the confidence engine, kept around for
    # debugging/calibration (Phase 17) rather than just the final number.
    retrieval_score: float = Field(ge=0.0, le=1.0)
    grounding_score: float = Field(ge=0.0, le=1.0)
    citation_valid: bool
    consistency_score: float = Field(ge=0.0, le=1.0)
    llm_confidence: float = Field(ge=0.0, le=1.0)

    confidence: float = Field(ge=0.0, le=1.0)  # final, engine-computed
    grounding_status: str = Field(pattern="^(supported|partially_supported|unsupported|not_applicable)$")
    status: str = Field(
        pattern="^(grounded|partially_grounded|insufficient_grounding|human_review_required)$"
    )

    # Phase 9 named routing conditions (risk/routing_flags.py). Any flag
    # sends the clause to human review regardless of confidence.
    review_flags: List[str] = Field(default_factory=list)

    verification_status: str = "pending"  # pending | auto_approved | human_verified | rejected

    # What the person should do (risk/decision.py):
    # no_lawyer | negotiate | lawyer | expert
    decision: Optional[str] = None
