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
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.database import db as db_module
from backend.database.db import get_db
from backend.services import jobs
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


# Plain `def`, not `async def`: the pipeline blocks for minutes, and an
# async handler would run it on the event loop and freeze every other
# request (including job polling) until it finished.
@router.post("/analyze-document")
def analyze_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    consent: str = Form(None),
    db: Session = Depends(get_db),
):
    _check_consent(consent)
    try:
        validate_upload(file.filename, document_type)
        path = _save_upload(file)
        try:
            return analyze_file(path, file.filename, document_type, db)
        finally:
            path.unlink(missing_ok=True)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/analyze-document/start", status_code=202)
def start_analysis(file: UploadFile = File(...), document_type: str = Form(...), consent: str = Form(None)):
    _check_consent(consent)
    try:
        validate_upload(file.filename, document_type)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    # The job owns the temp file from here and deletes it when finished.
    # SessionLocal is looked up at call time so tests can point it at
    # their own database.
    job_id = jobs.submit(_save_upload(file), file.filename, document_type,
                         session_factory=lambda: db_module.SessionLocal())
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
