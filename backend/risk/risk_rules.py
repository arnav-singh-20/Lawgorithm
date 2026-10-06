"""
Risk tier definitions (Phase 9) and human-review routing (Phase 10).

Verification routing used to be a flat "confidence < threshold" check.
It's now driven by the confidence engine's abstention status
(backend/confidence/engine.py) instead -- see should_send_for_verification
below. CONFIDENCE_THRESHOLD in config.py is kept for backward
compatibility with anything still reading it from .env, but the actual
gating logic no longer uses it directly; GROUNDED_THRESHOLD /
PARTIALLY_GROUNDED_THRESHOLD in confidence/engine.py are the real knobs now.
"""

from backend.confidence.engine import GROUNDED

RED = "red"
AMBER = "amber"
GREEN = "green"

RISK_ORDER = {GREEN: 0, AMBER: 1, RED: 2}

RISK_DEFINITIONS = {
    GREEN: "Low concern. Normal contractual clause, no obvious major imbalance.",
    AMBER: "Requires attention. May have financial/legal consequences; context dependent.",
    RED: (
        "High potential impact. Potentially unfair, highly restrictive, severe "
        "financial consequences, or possible statutory conflict."
    ),
}


def should_send_for_verification(result: dict) -> bool:
    """
    result: a finalized ClauseAnalysisResult dict, expected to have
    "status" (grounded/partially_grounded/insufficient_grounding/
    human_review_required) and "risk_level" (red/amber/green).

    Rule (Phase 10, updated for the confidence engine / abstention system):
        status != "grounded"   -> verify
        any review_flags       -> verify (Phase 9 routing conditions)
        risk_level == "red"    -> verify, even if fully grounded --
                                   high-impact findings always get a
                                   second set of eyes
        otherwise               -> show directly to user
    """
    status = result.get("status")
    risk_level = result.get("risk_level")

    if status != GROUNDED:
        return True

    if result.get("review_flags"):
        # Phase 9: conflicting sources / jurisdiction uncertainty /
        # unverified source -- a confident answer built on the wrong
        # state's law is still wrong.
        return True

    if risk_level == RED:
        return True

    return False


def get_overall_document_risk(clause_results: list[dict]) -> str:
    """
    Document-level risk = the highest risk tier found among its clauses.
    Used for the "Overall Risk: RED/AMBER/GREEN" banner on the analysis page.
    """
    if not clause_results:
        return GREEN

    levels = [r.get("risk_level", GREEN) for r in clause_results]
    return max(levels, key=lambda level: RISK_ORDER.get(level, 0))
