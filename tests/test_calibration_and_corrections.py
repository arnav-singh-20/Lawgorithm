"""
Phase 11 (reviewer corrections are saved as their own dataset, with an
untouched snapshot of the AI's prediction) and Phases 13/14
(calibration metrics + threshold recommendation).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.confidence.calibration import (
    brier_score,
    expected_calibration_error,
    recommend_threshold,
    reliability_bins,
)
from backend.database.db import init_db
from backend.database.models import Clause, Document, ReviewerCorrection
from backend.verification import verification_service


# ---------------- calibration ----------------

def test_perfectly_calibrated_has_zero_ece():
    pairs = [(0.8, True)] * 8 + [(0.8, False)] * 2
    assert expected_calibration_error(pairs) == pytest.approx(0.0)


def test_overconfident_ece_and_brier():
    pairs = [(0.9, True)] * 5 + [(0.9, False)] * 5   # says 90%, right 50%
    assert expected_calibration_error(pairs) == pytest.approx(0.4)
    assert brier_score(pairs) == pytest.approx((5 * 0.01 + 5 * 0.81) / 10)


def test_confidence_of_one_lands_in_last_bin():
    bins = reliability_bins([(1.0, True)])
    assert len(bins) == 1 and bins[0].upper == 1.0


def test_recommend_threshold_finds_lowest_qualifying():
    pairs = [(0.5, False)] * 20 + [(0.85, True)] * 38 + [(0.85, False)] * 2 + [(0.97, True)] * 40
    rec = recommend_threshold(pairs, target_precision=0.95, min_support=30)
    assert rec["threshold"] == 0.85
    assert rec["precision_at_threshold"] >= 0.95


def test_recommend_threshold_refuses_on_small_samples():
    rec = recommend_threshold([(0.99, True)] * 5, min_support=30)
    assert rec["threshold"] is None and "need at least" in rec["reason"]


def test_recommend_threshold_rejects_out_of_range():
    with pytest.raises(ValueError):
        recommend_threshold([(1.5, True)] * 40)


# ---------------- reviewer corrections ----------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    init_db(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _clause(db, **overrides):
    document = Document(filename="lease.pdf", document_type="rental")
    db.add(document)
    db.flush()
    fields = dict(
        document_id=document.id, clause_id="3", clause_title="LOCK-IN",
        clause_text="Tenant agrees to a 24 month lock-in.",
        plain_explanation="You must stay 24 months.", risk_level="amber",
        legal_assessment="Long lock-in.", recommended_action="Ask for a shorter lock-in.",
        clause_type="lease_term_renewal", claims=[], retrieved_source_ids=["mta_10"],
        retrieval_score=0.5, grounding_score=0.5, citation_valid=True, consistency_score=1.0,
        llm_confidence=0.7, confidence=0.72, grounding_status="partially_supported",
        status="human_review_required", review_flags=[], verification_status="pending",
    )
    fields.update(overrides)
    clause = Clause(**fields)
    db.add(clause)
    db.flush()
    verification_service.enqueue_for_verification(db, clause)
    db.commit()
    return clause


def test_approve_records_ai_was_correct(db_session):
    clause = _clause(db_session)
    verification_service.resolve(db_session, clause.id, "approve", reviewer_notes="looks right")

    (c,) = db_session.query(ReviewerCorrection).all()
    assert c.ai_was_correct is True
    assert c.ai_confidence == 0.72 and c.human_risk_level == "amber" and c.reason == "looks right"


def test_edit_snapshots_ai_output_before_applying_changes(db_session):
    clause = _clause(db_session)
    verification_service.resolve(
        db_session, clause.id, "edit",
        edited_explanation="You are locked in for 24 months of an 11-month lease.",
        edited_risk_level="red",
        edited_recommended_action="Refuse a lock-in longer than the lease term.",
        reviewer_notes="lock-in longer than the lease itself",
    )

    (c,) = db_session.query(ReviewerCorrection).all()
    assert c.ai_risk_level == "amber" and c.human_risk_level == "red"
    assert c.ai_explanation == "You must stay 24 months."
    assert c.human_explanation.startswith("You are locked in")
    assert c.ai_recommended_action == "Ask for a shorter lock-in."
    assert c.ai_was_correct is False

    db_session.refresh(clause)
    assert clause.risk_level == "red"  # edit now applies the risk change too
    assert clause.recommended_action == "Refuse a lock-in longer than the lease term."


def test_reject_is_incorrect_and_request_more_evidence_records_nothing(db_session):
    clause = _clause(db_session)
    verification_service.resolve(db_session, clause.id, "request_more_evidence")
    assert db_session.query(ReviewerCorrection).count() == 0

    verification_service.resolve(db_session, clause.id, "reject", reviewer_notes="wrong statute")
    (c,) = db_session.query(ReviewerCorrection).all()
    assert c.ai_was_correct is False and c.reviewer_action == "reject"


def test_invalid_risk_level_is_rejected(db_session):
    clause = _clause(db_session)
    with pytest.raises(ValueError):
        verification_service.resolve(db_session, clause.id, "change_risk", edited_risk_level="purple")


def test_init_db_adds_columns_to_an_old_database():
    """A lawgorithm.db created before this release must keep working."""
    from sqlalchemy import inspect, text

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE clauses (id VARCHAR PRIMARY KEY, document_id VARCHAR)"))
    init_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("clauses")}
    assert {"recommended_action", "review_flags", "cited_sources", "clause_type"} <= columns
