"""
Regression tests for Issue 4: a purely factual clause with no legal
claims (e.g. a salary statement) should NOT get routed to human
review just because there was nothing to ground. Deliberately exercised
via _finalize() directly with a fake context, so this runs with no
Gemini SDK installed and no network calls -- verify_grounding never
gets invoked when there are zero claims to check.
"""

from backend.agent.agent import _finalize


def test_green_clause_with_no_claims_is_grounded_not_flagged():
    parsed = {
        "plain_explanation": "You will be paid Rs 50,000 per month.",
        "risk_level": "green",
        "legal_assessment": "No legal question arises from a plain salary statement.",
        "claims": [],
        "llm_confidence": 0.95,
    }
    context = {"retrieved_sources": []}

    result = _finalize(parsed, context, clause_id="1", clause_title="SALARY")

    assert "error" not in result
    assert result["grounding_status"] == "not_applicable"
    assert result["status"] == "grounded"
    assert result["verification_status"] == "auto_approved"
    assert result["plain_explanation"] == "You will be paid Rs 50,000 per month."


def test_non_green_clause_with_no_claims_is_still_flagged():
    # An amber/red risk_level with zero supporting claims is internally
    # inconsistent -- the model is asserting a real legal problem exists
    # without backing it up. This should NOT get the "not_applicable"
    # free pass; it should still be treated as insufficiently grounded.
    parsed = {
        "plain_explanation": "This clause restricts you after leaving.",
        "risk_level": "amber",
        "legal_assessment": "Possibly restrictive but nothing was retrieved.",
        "claims": [],
        "llm_confidence": 0.6,
    }
    context = {"retrieved_sources": []}

    result = _finalize(parsed, context, clause_id="2", clause_title="NON-COMPETE")

    assert "error" not in result
    assert result["grounding_status"] != "not_applicable"
    assert result["status"] in {"insufficient_grounding", "human_review_required"}
    assert result["verification_status"] == "pending"


def test_consequence_is_cleaned_to_fit_the_sentence():
    from backend.agent.agent import clean_consequence
    assert clean_consequence("If you don't fix it, The landlord can lock you out.") == "the landlord can lock you out"
    assert clean_consequence("  you could lose your deposit  ") == "you could lose your deposit"
    assert clean_consequence("HRA is cut") == "HRA is cut"   # acronyms keep their capitals
    assert clean_consequence(None) == ""


def test_green_clauses_carry_no_consequence():
    from backend.agent.agent import _sanitize_model_payload
    out = _sanitize_model_payload({"plain_explanation": "x", "risk_level": "green", "legal_assessment": "y",
                                   "consequence": "nothing", "claims": [], "llm_confidence": 0.9})
    assert out["consequence"] == ""
    out = _sanitize_model_payload({"plain_explanation": "x", "risk_level": "red", "legal_assessment": "y",
                                   "consequence": "You can be evicted.", "claims": [], "llm_confidence": 0.9})
    assert out["consequence"] == "you can be evicted"
