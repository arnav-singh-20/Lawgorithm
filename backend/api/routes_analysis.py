from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.risk.decision import document_decision
from backend.database.db import get_db
from backend.database.models import Document
from backend.llm.base import LLMUnavailableError
from backend.config import (
    DPDP_ACT_URL, EXPERT_REVIEW_KEEP_DAYS, EXPERT_REVIEW_MAX_DAYS, FREE_LEGAL_AID, LLM_PROVIDER, REVIEWER_KIND, PRIVACY_CONTACT,
    RESULT_TTL_MINUTES, STORE_ANALYSES,
)
from backend.expert_review import service as expert_review
from backend.services import jobs
from backend.services.clause_service import clause_to_dict
from backend.translation.translator import translate_explanation, translate_and_validate

router = APIRouter()


class TranslateRequest(BaseModel):
    text: str
    target_language: str
    validate_translation: bool = False


@router.get("/config")
def public_config():
    """What the page needs to describe data handling accurately (no secrets)."""
    return {
        "ai_service": {"groq": "Groq", "gemini": "Google Gemini"}.get(LLM_PROVIDER),   # None = runs on this server
        "store_analyses": STORE_ANALYSES,
        "review_enabled": STORE_ANALYSES,
        "retention_minutes": RESULT_TTL_MINUTES,
        "expert_review_enabled": expert_review.enabled(),
        "expert_review_keep_days": EXPERT_REVIEW_KEEP_DAYS,
        "expert_review_max_days": EXPERT_REVIEW_MAX_DAYS,
        "free_legal_aid": FREE_LEGAL_AID,
        "reviewer_kind": "legal" if REVIEWER_KIND == "legal" else "team",
        "privacy_contact": PRIVACY_CONTACT or None,
        "dpdp_act_url": DPDP_ACT_URL,
    }


@router.get("/document/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    if not STORE_ANALYSES:
        # Privacy mode: results only ever lived in memory and expire.
        result = jobs.find_document(document_id)
        if result is None:
            raise HTTPException(status_code=404, detail="This analysis has expired or was deleted.")
        return result

    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    clauses = [clause_to_dict(c) for c in document.clauses]
    return {
        "document_id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "overall_risk": document.overall_risk,
        "decision": document_decision(clauses),
        "jurisdiction_states": document.jurisdiction_states or [],
        "document_summary": document.summary,
        "clauses": clauses,
    }


@router.delete("/document/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    """Right to erasure: remove the analysis from memory (and the database, if storing)."""
    deleted = jobs.delete(document_id)
    if STORE_ANALYSES:
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is not None:
            db.delete(document)
            db.commit()
            deleted = True
    return {"deleted": deleted}


@router.post("/translate")
def translate(request: TranslateRequest):
    try:
        if request.validate_translation:
            result = translate_and_validate(request.text, request.target_language)
            return {"target_language": request.target_language, **result}

        translated = translate_explanation(request.text, request.target_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Translation unavailable: {exc}") from exc

    return {"target_language": request.target_language, "translated_text": translated}
