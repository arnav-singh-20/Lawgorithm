"""
Shared logic for turning a run_agent() result dict into Clause row
fields. Used by both the initial document analysis endpoint
(routes_documents.py) and the human-review "request more evidence"
re-analysis flow (routes_verification.py) -- pulled out so both stay
in sync with the schema instead of maintaining two copies of the same
field mapping.
"""

from backend.database.models import Clause
from backend.risk.decision import clause_decision
from backend.risk.routing_flags import FLAG_DESCRIPTIONS


def apply_analysis_to_clause(clause: Clause, analysis: dict) -> Clause:
    """
    Mutates `clause` in place with every field from a validated
    run_agent() result and returns it (for chaining). Does NOT commit --
    the caller owns the transaction boundary.
    """
    clause.clause_id = analysis.get("clause_id", clause.clause_id)
    clause.clause_title = analysis.get("clause_title", clause.clause_title)
    clause.plain_explanation = analysis["plain_explanation"]
    clause.risk_level = analysis["risk_level"]
    clause.legal_assessment = analysis["legal_assessment"]
    clause.recommended_action = analysis.get("recommended_action", "")
    clause.consequence = analysis.get("consequence", "")
    clause_type = analysis.get("clause_type") or {}
    clause.clause_type = clause_type.get("clause_type")
    clause.clause_type_label = clause_type.get("label")
    clause.clause_type_confidence = clause_type.get("confidence")
    clause.claims = analysis.get("claims", [])
    clause.retrieved_source_ids = analysis.get("retrieved_source_ids", [])
    clause.cited_sources = analysis.get("cited_sources", [])
    clause.review_flags = analysis.get("review_flags", [])
    clause.retrieval_score = analysis["retrieval_score"]
    clause.grounding_score = analysis["grounding_score"]
    clause.citation_valid = analysis["citation_valid"]
    clause.consistency_score = analysis["consistency_score"]
    clause.llm_confidence = analysis["llm_confidence"]
    clause.confidence = analysis["confidence"]
    clause.grounding_status = analysis["grounding_status"]
    clause.status = analysis["status"]
    clause.verification_status = analysis["verification_status"]
    return clause


def flag_reason(clause: Clause) -> str:
    """
    Human-readable reason a clause landed in the review queue (Phase 10:
    reviewers should see WHY something was flagged, not just that it
    was). Mirrors the logic in risk_rules.should_send_for_verification
    but phrased for a person reading the dashboard rather than a boolean
    gate.
    """
    if not clause.citation_valid:
        return "The AI cited a source that was never actually retrieved (possible fabricated citation)."

    if clause.status == "insufficient_grounding":
        return "Not enough verified legal grounding was found to support a confident answer."

    if clause.status == "partially_grounded":
        return "Some supporting evidence was found, but confidence didn't reach the auto-approval bar."

    if clause.status == "human_review_required":
        return "Overall confidence was too low to auto-approve."

    if clause.review_flags:
        return " ".join(FLAG_DESCRIPTIONS.get(f, f) for f in clause.review_flags)

    if clause.risk_level == "red":
        return "High-risk (RED) clauses always get a human review, regardless of confidence."

    return "Flagged for review."


def clause_to_dict(c: Clause) -> dict:
    """Single serialization of a Clause row for every endpoint that returns one."""
    return {
        "clause_row_id": c.id,
        "document_id": c.document_id,
        "clause_id": c.clause_id,
        "clause_title": c.clause_title,
        "clause_text": c.clause_text,
        "plain_explanation": c.plain_explanation,
        "risk_level": c.risk_level,
        "legal_assessment": c.legal_assessment,
        "recommended_action": c.recommended_action,
        "consequence": c.consequence or "",
        "clause_type": (
            {"clause_type": c.clause_type, "label": c.clause_type_label, "confidence": c.clause_type_confidence}
            if c.clause_type_confidence is not None
            else None
        ),
        "claims": c.claims,
        "retrieved_source_ids": c.retrieved_source_ids,
        "cited_sources": c.cited_sources or [],
        "retrieval_score": c.retrieval_score,
        "grounding_score": c.grounding_score,
        "citation_valid": c.citation_valid,
        "consistency_score": c.consistency_score,
        "llm_confidence": c.llm_confidence,
        "confidence": c.confidence,
        "grounding_status": c.grounding_status,
        "status": c.status,
        "review_flags": c.review_flags or [],
        "verification_status": c.verification_status,
        "decision": clause_decision({
            "risk_level": c.risk_level, "status": c.status, "citation_valid": c.citation_valid,
            "review_flags": c.review_flags or [], "verification_status": c.verification_status,
        }),
    }
