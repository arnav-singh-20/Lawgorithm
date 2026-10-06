"""
The document-analysis pipeline, shared by the synchronous endpoint
(POST /analyze-document) and background jobs (POST /analyze-document/start).

    extract -> clean -> segment -> summarise -> agent per clause -> store

Reports progress through an optional callback so a job can show
"clause 3 of 7" while the (slow, local-model) analysis runs.
"""

import uuid
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.agent import agent as agent_core
from backend.agent.agent import run_agent
from backend.agent.summarizer import summarize_document, summary_as_context
from backend.config import STORE_ANALYSES, SUPPORTED_DOCUMENT_TYPES
from backend.database.models import Clause, Document
from backend.ingestion import SUPPORTED_EXTENSIONS, extract_document
from backend.ingestion.cleaner import clean_text
from backend.llm.base import LLMUnavailableError
from backend.privacy.redaction import redact
from backend.risk.decision import document_decision
from backend.risk.risk_rules import get_overall_document_risk
from backend.risk.routing_flags import detect_states
from backend.segmentation.clause_segmenter import segment_clauses
from backend.services.clause_service import apply_analysis_to_clause
from backend.verification.verification_service import enqueue_for_verification

ProgressFn = Callable[..., None]


class AnalysisError(Exception):
    """A failure the user should see, with the HTTP status it maps to."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_upload(filename: str, document_type: str) -> None:
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise AnalysisError(400, f"document_type must be one of {SUPPORTED_DOCUMENT_TYPES}.")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise AnalysisError(
            415, f"Unsupported file type '{suffix or 'unknown'}'. Upload a PDF, photo (JPG/PNG), DOCX or TXT."
        )


def analyze_file(
    path: Path,
    filename: str,
    document_type: str,
    db: Optional[Session],
    on_progress: Optional[ProgressFn] = None,
) -> dict:
    """
    With STORE_ANALYSES off (the default) nothing is written to the
    database: the result exists only in the returned dict / the job's
    memory, and ids are random handles.
    """
    progress = on_progress or (lambda **_: None)
    store = STORE_ANALYSES and db is not None

    progress(stage="reading")
    try:
        raw_text = extract_document(path)
    except Exception as exc:
        raise AnalysisError(422, f"Couldn't read this file ({type(exc).__name__}). Try a clearer photo or a PDF.") from exc

    cleaned = clean_text(raw_text)
    # DPDP data minimisation: strip identifiers before any AI call.
    cleaned, redactions = redact(cleaned)
    if not cleaned.strip():
        raise AnalysisError(
            422, "No readable text was found in this file. If it's a photo, retake it in good light, flat and in focus."
        )
    clauses = [c for c in segment_clauses(cleaned) if c["clause_id"] != "0"]  # preamble: nothing to classify

    # Step 1: summarise the whole document once; the summary is shown to
    # the user and passed into every clause's agent run as context.
    progress(stage="summarising", total=len(clauses))
    try:
        summary = summarize_document(cleaned, agent_core._get_provider())
    except LLMUnavailableError as exc:
        raise AnalysisError(503, str(exc)) from exc
    document_context = summary_as_context(summary)

    # Which state's law governs matters for rent law in particular
    # (Phase 9). Detected once from the whole document so a clause that
    # doesn't itself mention the city still gets checked against it.
    known_states = detect_states(cleaned) | detect_states((summary or {}).get("location") or "")

    jurisdiction_states = sorted(known_states)
    if store:
        document = Document(
            filename=filename,
            document_type=document_type,
            jurisdiction_states=jurisdiction_states,
            summary=summary,
        )
        db.add(document)
        db.flush()  # get document.id before committing
        document_id = document.id
    else:
        document, document_id = None, uuid.uuid4().hex

    progress(stage="clauses", total=len(clauses), done=0, summary=summary,
             document_id=document_id, jurisdiction_states=jurisdiction_states)

    clause_results, failed_clauses = [], []
    for index, clause in enumerate(clauses):
        progress(stage="clauses", total=len(clauses), done=index, current_title=clause["title"])
        try:
            analysis = run_agent(
                clause_text=clause["text"],
                clause_id=clause["clause_id"],
                clause_title=clause["title"],
                known_states=known_states,
                document_context=document_context,
            )
        except LLMUnavailableError as exc:
            # The AI can't be reached at all -- every remaining clause
            # would fail the same way. Abort the whole document cleanly
            # rather than storing a half-analysed contract.
            if store:
                db.rollback()
            raise AnalysisError(503, str(exc)) from exc
        except Exception as exc:  # one bad clause shouldn't sink the document
            analysis = {"error": f"{type(exc).__name__}: {exc}"}

        if "error" in analysis:
            # Don't silently drop it -- the user should know this clause
            # wasn't analyzed, not just receive a shorter list.
            failed_clauses.append({
                "clause_id": clause["clause_id"],
                "clause_title": clause["title"],
                "status": "failed",
                "error": analysis.get("error", "Unknown agent failure"),
            })
            continue

        if store:
            clause_row = Clause(document_id=document_id, clause_text=clause["text"])
            apply_analysis_to_clause(clause_row, analysis)
            db.add(clause_row)
            db.flush()
            if analysis["verification_status"] == "pending":
                enqueue_for_verification(db, clause_row)
            clause_row_id = clause_row.id
        else:
            clause_row_id = uuid.uuid4().hex

        result = {**analysis, "clause_text": clause["text"], "clause_row_id": clause_row_id}
        clause_results.append(result)
        progress(stage="clauses", total=len(clauses), done=index + 1, clause=result)

    overall_risk = get_overall_document_risk(clause_results)
    if store:
        document.overall_risk = overall_risk
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "document_id": document_id,
        "filename": filename,
        "document_type": document_type,
        "overall_risk": overall_risk,
        "decision": document_decision(clause_results),
        "jurisdiction_states": jurisdiction_states,
        "stored": store,
        "redactions": redactions,
        "document_summary": summary,
        "clauses": clause_results,
        "failed_clauses": failed_clauses,
    }
