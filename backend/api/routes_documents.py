"""
Document analysis endpoints (Phase 13).

    POST /analyze-document         synchronous: waits for the full result
    POST /analyze-document/start   background job: returns {job_id} at once
    GET  /jobs/{job_id}            job progress + clauses finished so far

Both run the same pipeline (services/analysis_pipeline.py). The frontend
uses the job API because a local model takes minutes per document.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.database import db as db_module
from backend.database.db import get_db
from backend.services import jobs
from backend.payments import razorpay
from backend.services.analysis_pipeline import AnalysisError, analyze_file, validate_upload

router = APIRouter()


def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        return Path(tmp.name)


CONSENT_REQUIRED = (
    "Consent is required: please confirm you agree to your document being processed "
    "as described in the privacy notice."
)


def _check_consent(consent: str | None) -> None:
    # DPDP Act s.6: processing needs the person's free, informed consent.
    if (consent or "").strip().lower() not in ("true", "yes", "1", "on"):
        raise HTTPException(status_code=400, detail=CONSENT_REQUIRED)


def _take_payment(file: UploadFile, order_id, payment_id, signature) -> str | None:
    """None when free (payments off, or one of the sample contracts); else the redeemed payment id."""
    if razorpay.price("analysis") <= 0:
        return None
    content = file.file.read()
    file.file.seek(0)
    if razorpay.is_sample(content):
        return None
    try:
        return razorpay.redeem("analysis", order_id, payment_id, signature, use_ref=f"doc:{uuid.uuid4().hex[:12]}")
    except razorpay.PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# Plain `def`, not `async def`: the pipeline blocks for minutes, and an
# async handler would run it on the event loop and freeze every other
# request (including job polling) until it finished.
@router.post("/analyze-document")
def analyze_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    consent: str = Form(None),
    razorpay_order_id: str = Form(None),
    razorpay_payment_id: str = Form(None),
    razorpay_signature: str = Form(None),
    db: Session = Depends(get_db),
):
    _check_consent(consent)
    try:
        validate_upload(file.filename, document_type)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    paid = _take_payment(file, razorpay_order_id, razorpay_payment_id, razorpay_signature)
    try:
        path = _save_upload(file)
        try:
            return analyze_file(path, file.filename, document_type, db)
        finally:
            path.unlink(missing_ok=True)
    except AnalysisError as exc:
        razorpay.refund(paid, "analysis failed")
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/analyze-document/start", status_code=202)
def start_analysis(file: UploadFile = File(...), document_type: str = Form(...), consent: str = Form(None),
                   razorpay_order_id: str = Form(None), razorpay_payment_id: str = Form(None),
                   razorpay_signature: str = Form(None)):
    _check_consent(consent)
    try:
        validate_upload(file.filename, document_type)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    paid = _take_payment(file, razorpay_order_id, razorpay_payment_id, razorpay_signature)
    # The job owns the temp file from here and deletes it when finished.
    # SessionLocal is looked up at call time so tests can point it at
    # their own database.
    job_id = jobs.submit(_save_upload(file), file.filename, document_type,
                         session_factory=lambda: db_module.SessionLocal(), payment_id=paid)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This analysis has expired or was deleted.")
    return job


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    """Right to erasure: removes the analysis (running or finished) from memory immediately."""
    return {"deleted": jobs.delete(job_id)}
