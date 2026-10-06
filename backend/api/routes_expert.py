"""
Expert review endpoints -- the human in the loop (expert_review/service.py).

  Person (holds the ticket link):
    POST   /expert-review                 send chosen clauses, with consent
    GET    /expert-review/{ticket_id}     status + reviewer decisions
    DELETE /expert-review/{ticket_id}     erase it now

  Reviewer (X-Reviewer-Key header: an owner key from REVIEWER_KEYS, or an
  invited reviewer's key from their invite link):
    GET    /expert-review/reviewer/me
    GET    /expert-review/reviewer/queue
    POST   /expert-review/{ticket_id}/clauses/{clause_row_id}

  Owner only:
    GET    /expert-review/reviewers
    POST   /expert-review/reviewers            {name} -> invite key (shown once)
    DELETE /expert-review/reviewers/{id}       revoke at once
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.config import STORE_ANALYSES
from backend.expert_review import service
from backend.services import jobs

router = APIRouter(prefix="/expert-review")


class CreateRequest(BaseModel):
    document_id: str
    clause_row_ids: list[str]
    consent: bool = False


class AddReviewerRequest(BaseModel):
    name: str


class ReviewRequest(BaseModel):
    decision: str
    risk_level: str
    note: str = ""
    consequence: str = ""


def _call(fn, *args):
    try:
        return fn(*args)
    except service.ReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _document(document_id: str) -> dict:
    if not STORE_ANALYSES:
        document = jobs.find_document(document_id)
    else:
        from backend.api.routes_analysis import get_document
        from backend.database.db import SessionLocal

        db = SessionLocal()
        try:
            document = get_document(document_id, db)
        except HTTPException:
            document = None
        finally:
            db.close()
    if document is None:
        raise HTTPException(status_code=404, detail="This analysis has expired or was deleted -- analyse the contract again first.")
    return document


@router.post("", status_code=201)
def create(request: CreateRequest):
    return _call(service.create_ticket, _document(request.document_id), request.clause_row_ids, request.consent)


@router.get("/reviewer/me")
def reviewer_me(x_reviewer_key: str | None = Header(default=None)):
    who = _call(service.identify, x_reviewer_key)
    return {"name": who["name"], "role": who["role"]}


@router.get("/reviewers")
def list_reviewers(x_reviewer_key: str | None = Header(default=None)):
    return {"reviewers": _call(service.list_reviewers, x_reviewer_key)}


@router.post("/reviewers", status_code=201)
def add_reviewer(request: AddReviewerRequest, x_reviewer_key: str | None = Header(default=None)):
    return _call(service.add_reviewer, x_reviewer_key, request.name)


@router.delete("/reviewers/{reviewer_id}")
def remove_reviewer(reviewer_id: str, x_reviewer_key: str | None = Header(default=None)):
    if not _call(service.remove_reviewer, x_reviewer_key, reviewer_id):
        raise HTTPException(status_code=404, detail="No such reviewer.")
    return {"removed": True}


@router.get("/reviewer/queue")
def reviewer_queue(x_reviewer_key: str | None = Header(default=None)):
    name = _call(service.reviewer_name, x_reviewer_key)
    items = _call(service.pending)
    role = _call(service.identify, x_reviewer_key)["role"]
    return {"reviewer": name, "role": role, "count": len(items), "items": items}


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str):
    return _call(service.get_ticket, ticket_id)


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: str):
    if not _call(service.delete_ticket, ticket_id):
        raise HTTPException(status_code=404, detail="This expert check was already deleted.")
    return {"deleted": True}


@router.post("/{ticket_id}/clauses/{clause_row_id}")
def review_clause(ticket_id: str, clause_row_id: str, request: ReviewRequest,
                  x_reviewer_key: str | None = Header(default=None)):
    name = _call(service.reviewer_name, x_reviewer_key)
    return _call(service.record_review, ticket_id, clause_row_id, name,
                 request.decision, request.risk_level, request.note, request.consequence)
