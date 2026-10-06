"""
Persistence layer.

Kept intentionally simple (SQLite via SQLAlchemy) -- enough to support
the /document/{id} and /verification endpoints without needing a
running Postgres instance for local dev. Swap DATABASE_URL in config.py
for anything else later; nothing else needs to change.
"""

import datetime
import uuid

from sqlalchemy import Column, String, Float, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    filename = Column(String, nullable=False)
    document_type = Column(String, nullable=False)  # "employment" | "rental"
    overall_risk = Column(String, nullable=True)
    # Indian states the document text mentions (Phase 9 jurisdiction check).
    jurisdiction_states = Column(JSON, nullable=True)
    # Whole-document simple-English summary (agent/summarizer.py).
    summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    clauses = relationship("Clause", back_populates="document", cascade="all, delete-orphan")


class Clause(Base):
    __tablename__ = "clauses"

    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)

    clause_id = Column(String)          # in-document identifier, e.g. "4"
    clause_title = Column(String)
    clause_text = Column(Text)

    plain_explanation = Column(Text)
    risk_level = Column(String)
    legal_assessment = Column(Text)
    recommended_action = Column(Text)        # Phase 18
    consequence = Column(Text)               # "If you don't fix it, ..."

    clause_type = Column(String)             # from the precedent index; identification only
    clause_type_label = Column(String)
    clause_type_confidence = Column(Float)

    claims = Column(JSON)                    # list[{"claim":..., "supporting_source_ids":[...]}]
    retrieved_source_ids = Column(JSON)      # list[str]
    cited_sources = Column(JSON)             # list[{id, law, section, title, jurisdiction, official_source, text}]

    retrieval_score = Column(Float)
    grounding_score = Column(Float)
    citation_valid = Column(Boolean)
    consistency_score = Column(Float)
    llm_confidence = Column(Float)

    confidence = Column(Float)               # final, engine-computed
    grounding_status = Column(String)        # supported | partially_supported | unsupported
    status = Column(String)                  # grounded | partially_grounded | insufficient_grounding | human_review_required
    review_flags = Column(JSON)              # Phase 9: list[str]
    verification_status = Column(String, default="pending")

    document = relationship("Document", back_populates="clauses")
    verification = relationship(
        "VerificationRecord", back_populates="clause", uselist=False, cascade="all, delete-orphan"
    )


class VerificationRecord(Base):
    __tablename__ = "verification_records"

    id = Column(String, primary_key=True, default=_uuid)
    clause_id = Column(String, ForeignKey("clauses.id"), nullable=False)

    reviewer_action = Column(String, nullable=True)  # approve | edit | change_risk | reject | request_more_evidence
    edited_explanation = Column(Text, nullable=True)
    edited_recommended_action = Column(Text, nullable=True)
    edited_risk_level = Column(String, nullable=True)
    reviewer_notes = Column(Text, nullable=True)     # reason for correction / reviewer remarks
    resolved_at = Column(DateTime, nullable=True)

    clause = relationship("Clause", back_populates="verification")


class ReviewerCorrection(Base):
    """
    Phase 11: one row per reviewer decision, as its own append-only
    dataset -- (what the AI said) vs (what the human decided) + why.

    The AI side is a SNAPSHOT taken before the reviewer's edit is
    applied to the Clause row, so later edits/re-runs never overwrite
    what the model originally predicted. This table is what Phase 14
    calibration (scripts/calibrate_thresholds.py) and any future
    fine-tuning (Phase 21) read from.
    """

    __tablename__ = "reviewer_corrections"

    id = Column(String, primary_key=True, default=_uuid)
    clause_row_id = Column(String, ForeignKey("clauses.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    document_type = Column(String)
    clause_text = Column(Text)
    clause_type = Column(String)

    # --- AI prediction (snapshot) ---
    ai_risk_level = Column(String)
    ai_explanation = Column(Text)
    ai_legal_assessment = Column(Text)
    ai_recommended_action = Column(Text)
    ai_claims = Column(JSON)
    ai_retrieved_source_ids = Column(JSON)
    ai_confidence = Column(Float)
    ai_status = Column(String)
    ai_review_flags = Column(JSON)

    # --- human decision ---
    reviewer_action = Column(String)      # approve | edit | change_risk | reject
    human_risk_level = Column(String)     # final risk level after review
    human_explanation = Column(Text)      # null = unchanged
    human_recommended_action = Column(Text)
    reason = Column(Text)

    # Derived label for calibration: True only when the reviewer accepted
    # the AI output unchanged.
    ai_was_correct = Column(Boolean)
