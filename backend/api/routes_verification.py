"""
Human verification dashboard endpoints (Phase 10).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import Clause
from backend.agent.agent import run_agent
from backend.config import STORE_ANALYSES
from backend.agent.summarizer import summary_as_context
from backend.llm.base import LLMUnavailableError
from backend.services.clause_service import apply_analysis_to_clause, clause_to_dict, flag_reason
from backend.verification import verification_service
from backend.verification.verification_service import enqueue_for_verification

router = APIRouter()


class ResolveRequest(BaseModel):
    action: str  # approve | edit | change_risk | reject | request_more_evidence
    edited_explanation: str | None = None
    edited_risk_level: str | None = None
    edited_recommended_action: str | None = None
    reviewer_notes: str | None = None


def _require_review_enabled() -> None:
    if not STORE_ANALYSES:
        raise HTTPException(status_code=404, detail="Human review is disabled: contracts are not stored (privacy mode).")


@router.get("/verification/pending")
def get_pending(db: Session = Depends(get_db)):
    if not STORE_ANALYSES:
        return {"count": 0, "items": [], "review_enabled": False}
    pending = verification_service.get_pending(db)
    return {
        "count": len(pending),
        "items": [{**clause_to_dict(c), "flag_reason": flag_reason(c)} for c in pending],
    }


@router.get("/verification/corrections")
def get_corrections(db: Session = Depends(get_db)):
    """Phase 11: the AI-vs-human correction dataset, oldest first."""
    _require_review_enabled()
    corrections = verification_service.list_corrections(db)
    return {
        "count": len(corrections),
        "items": [verification_service.correction_to_dict(c) for c in corrections],
    }


@router.post("/verification/{clause_row_id}")
def resolve_verification(clause_row_id: str, request: ResolveRequest, db: Session = Depends(get_db)):
    _require_review_enabled()
    try:
        clause = verification_service.resolve(
            db,
            clause_id=clause_row_id,
            action=request.action,
            edited_explanation=request.edited_explanation,
            edited_risk_level=request.edited_risk_level,
            reviewer_notes=request.reviewer_notes,
            edited_recommended_action=request.edited_recommended_action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if request.action == "request_more_evidence":
        try:
            clause = _rerun_analysis(db, clause)
        except LLMUnavailableError as exc:
            # The clause stays pending exactly as it was.
            raise HTTPException(status_code=503, detail=f"Re-analysis unavailable: {exc}") from exc

    return {
        "clause_row_id": clause.id,
        "verification_status": clause.verification_status,
        "risk_level": clause.risk_level,
        "plain_explanation": clause.plain_explanation,
        "status": clause.status,
        "confidence": clause.confidence,
        "re_analyzed": request.action == "request_more_evidence",
    }


def _rerun_analysis(db: Session, clause: Clause) -> Clause:
    """
    "Request more evidence" isn't just a label -- it actually re-runs
    the agent on the same clause text (giving it a fresh chance to
    search, e.g. after the legal corpus has been extended) rather than
    leaving the reviewer with nothing but a resubmit button that does
    nothing. If the new run is confidently grounded, the clause clears
    the review queue on its own; otherwise it stays pending with an
    updated flag_reason for the next reviewer.
    """
    analysis = run_agent(
        clause_text=clause.clause_text,
        clause_id=clause.clause_id,
        clause_title=clause.clause_title,
        known_states=set(clause.document.jurisdiction_states or []) if clause.document else None,
        document_context=summary_as_context(clause.document.summary) if clause.document else "",
    )

    if "error" in analysis:
        # Re-analysis failed outright -- leave the clause exactly as it
        # was (still pending) rather than losing the previous, at-least-
        # partially-useful result.
        return clause

    apply_analysis_to_clause(clause, analysis)

    if clause.verification_status == "pending" and clause.verification is None:
        enqueue_for_verification(db, clause)

    db.commit()
    db.refresh(clause)
    return clause
