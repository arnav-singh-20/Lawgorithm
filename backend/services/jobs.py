"""
Background analysis jobs.

With a local model a contract takes minutes (~50 s per clause on an
8 GB laptop), far too long to hold one HTTP request open behind a
spinner. POST /analyze-document/start returns a job id at once; the
frontend polls GET /jobs/{id} and renders each clause as it finishes.

One worker thread: a local LLM can't usefully run two analyses at once
on this hardware, so extra uploads queue (and report "queued").

In-memory on purpose -- jobs are progress handles, not records. The
results themselves are committed to the database by the pipeline and
stay readable via GET /document/{id} after a restart.
"""

import datetime
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.config import RESULT_TTL_MINUTES, STORE_ANALYSES
from backend.database.db import SessionLocal
from backend.payments import razorpay
from backend.services.analysis_pipeline import AnalysisError, analyze_file

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()

MAX_FINISHED_JOBS = 50


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _expired(job: dict) -> bool:
    """Finished jobs (and their results) are kept for RESULT_TTL_MINUTES only."""
    finished = job.get("finished_at")
    if not finished:
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(finished)
    return age > datetime.timedelta(minutes=RESULT_TTL_MINUTES)


def submit(path: Path, filename: str, document_type: str, session_factory=SessionLocal,
           payment_id: str | None = None) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",       # queued | running | done | failed
            "stage": "queued",        # reading | summarising | clauses
            "filename": filename,
            "document_type": document_type,
            "total": None,
            "done": 0,
            "current_title": None,
            "summary": None,
            "document_id": None,
            "jurisdiction_states": [],
            "clauses": [],
            "result": None,
            "error": None,
            "error_status": None,
            "created_at": _now(),
            "finished_at": None,
            "expires_in_minutes": RESULT_TTL_MINUTES,
        }
        _prune()
    _executor.submit(_run, job_id, path, filename, document_type, session_factory, payment_id)
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        _prune()
        job = _jobs.get(job_id)
        return None if job is None else {**job, "clauses": list(job["clauses"])}


def find_document(document_id: str) -> dict | None:
    """The finished result for a document id, while it hasn't expired."""
    with _lock:
        _prune()
        for job in _jobs.values():
            if job.get("result") and job["result"].get("document_id") == document_id:
                return job["result"]
    return None


def delete(job_or_document_id: str) -> bool:
    """'Delete now' (DPDP right to erasure): drop the job and its result from memory."""
    with _lock:
        for job_id, job in list(_jobs.items()):
            result = job.get("result") or {}
            if job_id == job_or_document_id or result.get("document_id") == job_or_document_id \
                    or job.get("document_id") == job_or_document_id:
                if job["status"] in ("queued", "running"):
                    job["cancelled"] = True       # the worker discards it when it finishes
                _jobs.pop(job_id, None)
                return True
    return False


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:      # deleted mid-analysis: drop the progress on the floor
            return
        clause = fields.pop("clause", None)
        if clause is not None:
            job["clauses"].append(clause)
        job.update({k: v for k, v in fields.items() if v is not None or k == "current_title"})


def _run(job_id: str, path: Path, filename: str, document_type: str, session_factory,
         payment_id: str | None = None) -> None:
    if job_id not in _jobs:      # deleted while queued: nothing was delivered, so refund
        path.unlink(missing_ok=True)
        razorpay.refund(payment_id, "deleted before the check started")
        return
    _update(job_id, status="running")
    db = session_factory() if STORE_ANALYSES else None
    try:
        result = analyze_file(path, filename, document_type, db, on_progress=lambda **p: _update(job_id, **p))
        _update(job_id, status="done", stage="done", result=result, current_title=None, finished_at=_now())
    except AnalysisError as exc:
        refunded = razorpay.refund(payment_id, "analysis failed")
        _update(job_id, status="failed", error=exc.detail, error_status=exc.status_code, refunded=refunded or None,
                finished_at=_now())
    except Exception as exc:  # never leave a job "running" forever
        refunded = razorpay.refund(payment_id, "analysis failed")
        _update(job_id, refunded=refunded or None)
        _update(job_id, status="failed", error=f"Unexpected error: {type(exc).__name__}",
                error_status=500, finished_at=_now())
    finally:
        if db is not None:
            db.close()
        path.unlink(missing_ok=True)     # the uploaded file never outlives the analysis


def _prune() -> None:
    for job_id in [j for j, job in _jobs.items() if _expired(job)]:
        _jobs.pop(job_id, None)
    finished = [j for j in _jobs.values() if j["status"] in ("done", "failed")]
    for job in sorted(finished, key=lambda j: j["created_at"])[:-MAX_FINISHED_JOBS]:
        _jobs.pop(job["job_id"], None)
