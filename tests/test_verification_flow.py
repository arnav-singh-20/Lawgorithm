"""
Tests for the "request more evidence" reviewer action (Phase 10),
using an isolated in-memory SQLite DB and a fake agent (no live
Gemini call) so this exercises the real DB/service wiring without
network access.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Document, Clause
from backend.verification import verification_service
from backend.services.clause_service import apply_analysis_to_clause, flag_reason


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _pending_clause(db_session, **overrides) -> Clause:
    document = Document(filename="test.pdf", document_type="employment")
    db_session.add(document)
    db_session.flush()

    defaults = dict(
        document_id=document.id,
        clause_text="The employee shall not compete for 12 months.",
        clause_id="4",
        clause_title="NON-COMPETE",
        plain_explanation="You can't join a competitor for a year.",
        risk_level="amber",
        legal_assessment="No relevant source was retrieved.",
        claims=[],
        retrieved_source_ids=[],
        retrieval_score=0.0,
        grounding_score=0.0,
        citation_valid=True,
        consistency_score=0.5,
        llm_confidence=0.3,
        confidence=0.3,
        grounding_status="unsupported",
        status="insufficient_grounding",
        verification_status="pending",
    )
    defaults.update(overrides)

    clause = Clause(**defaults)
    db_session.add(clause)
    db_session.flush()

    verification_service.enqueue_for_verification(db_session, clause)
    db_session.commit()
    db_session.refresh(clause)
    return clause


def test_request_more_evidence_does_not_resolve_the_review(db_session):
    clause = _pending_clause(db_session)

    resolved = verification_service.resolve(db_session, clause_id=clause.id, action="request_more_evidence")

    assert resolved.verification_status == "pending"
    assert resolved.verification.reviewer_action == "request_more_evidence"
    assert resolved.verification.resolved_at is None


def test_approve_action_still_resolves_normally(db_session):
    clause = _pending_clause(db_session)

    resolved = verification_service.resolve(db_session, clause_id=clause.id, action="approve")

    assert resolved.verification_status == "human_verified"
    assert resolved.verification.resolved_at is not None


def test_rerun_with_better_evidence_clears_the_queue(db_session):
    """
    Simulates what routes_verification._rerun_analysis does, but calling
    apply_analysis_to_clause directly with a fabricated "better" agent
    result (as if a live Gemini re-run had found real grounding this
    time) instead of actually invoking run_agent -- keeps this test
    network-free while still proving the DB update + status transition
    logic works end to end.
    """
    clause = _pending_clause(db_session)
    assert clause.verification_status == "pending"

    better_analysis = {
        "clause_id": "4",
        "clause_title": "NON-COMPETE",
        "plain_explanation": "You can't join a competitor for a year.",
        "risk_level": "amber",
        "legal_assessment": "This restrains a lawful trade, per Contract Act s.27.",
        "claims": [{"claim": "Restrains lawful trade.", "supporting_source_ids": ["src_27"]}],
        "retrieved_source_ids": ["src_27"],
        "retrieval_score": 0.9,
        "grounding_score": 1.0,
        "citation_valid": True,
        "consistency_score": 1.0,
        "llm_confidence": 0.9,
        "confidence": 0.97,
        "grounding_status": "supported",
        "status": "grounded",
        "verification_status": "auto_approved",
    }

    apply_analysis_to_clause(clause, better_analysis)
    db_session.commit()
    db_session.refresh(clause)

    assert clause.verification_status == "auto_approved"
    assert clause.status == "grounded"
    assert clause.retrieved_source_ids == ["src_27"]


def test_flag_reason_explains_invalid_citation():
    clause = Clause(citation_valid=False, status="human_review_required", risk_level="amber")
    assert "fabricated" in flag_reason(clause).lower()


def test_flag_reason_explains_red_risk():
    clause = Clause(citation_valid=True, status="grounded", risk_level="red")
    assert "red" in flag_reason(clause).lower() or "high-risk" in flag_reason(clause).lower()


def test_flag_reason_explains_insufficient_grounding():
    clause = Clause(citation_valid=True, status="insufficient_grounding", risk_level="amber")
    assert "grounding" in flag_reason(clause).lower()
