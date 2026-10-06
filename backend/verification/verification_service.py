"""
Human verification queue (Phase 10).

Any clause result that should_send_for_verification() flags gets a
VerificationRecord row created for it. The reviewer dashboard reads
get_pending() and posts back through resolve().
"""

import datetime

from sqlalchemy.orm import Session

from backend.database.models import Clause, ReviewerCorrection, VerificationRecord

# "request_more_evidence" does NOT resolve the review -- it's a signal
# to the route layer to re-run the agent (see routes_verification.py),
# after which the clause either clears the queue on its own (if the new
# analysis is confidently grounded) or stays pending for a human to look
# at again with better evidence in hand.
VALID_ACTIONS = {"approve", "edit", "change_risk", "reject", "request_more_evidence"}
RESOLVING_ACTIONS = {"approve", "edit", "change_risk", "reject"}
VALID_RISK_LEVELS = {"red", "amber", "green"}


def enqueue_for_verification(db: Session, clause: Clause) -> VerificationRecord:
    """
    Adds the record to the session but does NOT commit -- the caller
    (e.g. routes_documents.analyze_document) is processing a whole
    document as one unit of work and should commit once at the end, so
    a failure partway through a document doesn't leave partial rows
    committed while the rest silently never happened.
    """
    record = VerificationRecord(clause_id=clause.id)
    db.add(record)
    return record


def get_pending(db: Session) -> list[Clause]:
    return (
        db.query(Clause)
        .filter(Clause.verification_status == "pending")
        .all()
    )


def resolve(
    db: Session,
    clause_id: str,
    action: str,
    edited_explanation: str = None,
    edited_risk_level: str = None,
    reviewer_notes: str = None,
    edited_recommended_action: str = None,
) -> Clause:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_ACTIONS}")
    if edited_risk_level is not None and edited_risk_level not in VALID_RISK_LEVELS:
        raise ValueError(f"Invalid risk level '{edited_risk_level}'. Must be one of {VALID_RISK_LEVELS}")

    clause = db.query(Clause).filter(Clause.id == clause_id).first()
    if clause is None:
        raise ValueError(f"No clause found with id {clause_id}")

    record = clause.verification
    if record is None:
        record = VerificationRecord(clause_id=clause.id)
        db.add(record)

    record.reviewer_action = action
    if reviewer_notes:
        record.reviewer_notes = reviewer_notes

    if action == "request_more_evidence":
        # Not resolved -- the route layer will re-run the agent next and
        # decide the clause's fate from the fresh result. Leave
        # verification_status and resolved_at alone.
        db.commit()
        db.refresh(clause)
        return clause

    record.resolved_at = datetime.datetime.now(datetime.timezone.utc)

    # Snapshot the AI's output BEFORE any edit is applied to the row.
    correction = _snapshot_ai_prediction(clause)

    # "edit" may carry any combination of corrected fields (the
    # dashboard's edit form sends explanation + risk + reason together);
    # "change_risk" is the risk-only shortcut.
    if action == "edit" and edited_explanation and edited_explanation != clause.plain_explanation:
        record.edited_explanation = edited_explanation
        correction.human_explanation = edited_explanation
        clause.plain_explanation = edited_explanation

    if action == "edit" and edited_recommended_action and edited_recommended_action != clause.recommended_action:
        record.edited_recommended_action = edited_recommended_action
        correction.human_recommended_action = edited_recommended_action
        clause.recommended_action = edited_recommended_action

    if action in ("edit", "change_risk") and edited_risk_level and edited_risk_level != clause.risk_level:
        record.edited_risk_level = edited_risk_level
        clause.risk_level = edited_risk_level

    correction.reviewer_action = action
    correction.human_risk_level = clause.risk_level
    correction.reason = reviewer_notes
    correction.ai_was_correct = action == "approve" or (
        action in ("edit", "change_risk")
        and correction.human_risk_level == correction.ai_risk_level
        and correction.human_explanation is None
        and correction.human_recommended_action is None
    )
    db.add(correction)

    clause.verification_status = "rejected" if action == "reject" else "human_verified"

    db.commit()
    db.refresh(clause)
    return clause


def _snapshot_ai_prediction(clause: Clause) -> ReviewerCorrection:
    return ReviewerCorrection(
        clause_row_id=clause.id,
        document_type=clause.document.document_type if clause.document else None,
        clause_text=clause.clause_text,
        clause_type=clause.clause_type,
        ai_risk_level=clause.risk_level,
        ai_explanation=clause.plain_explanation,
        ai_legal_assessment=clause.legal_assessment,
        ai_recommended_action=clause.recommended_action,
        ai_claims=clause.claims,
        ai_retrieved_source_ids=clause.retrieved_source_ids,
        ai_confidence=clause.confidence,
        ai_status=clause.status,
        ai_review_flags=clause.review_flags,
    )


def correction_to_dict(c: ReviewerCorrection) -> dict:
    return {
        "id": c.id,
        "clause_row_id": c.clause_row_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "document_type": c.document_type,
        "clause_text": c.clause_text,
        "clause_type": c.clause_type,
        "ai": {
            "risk_level": c.ai_risk_level,
            "explanation": c.ai_explanation,
            "legal_assessment": c.ai_legal_assessment,
            "recommended_action": c.ai_recommended_action,
            "claims": c.ai_claims,
            "retrieved_source_ids": c.ai_retrieved_source_ids,
            "confidence": c.ai_confidence,
            "status": c.ai_status,
            "review_flags": c.ai_review_flags,
        },
        "human": {
            "action": c.reviewer_action,
            "risk_level": c.human_risk_level,
            "explanation": c.human_explanation,
            "recommended_action": c.human_recommended_action,
            "reason": c.reason,
        },
        "ai_was_correct": c.ai_was_correct,
    }


def list_corrections(db: Session) -> list[ReviewerCorrection]:
    return db.query(ReviewerCorrection).order_by(ReviewerCorrection.created_at).all()
