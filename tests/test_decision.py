"""Every clause and document gets one plain decision (risk/decision.py)."""

from backend.risk.decision import clause_decision, document_decision


def r(risk, status="grounded", flags=(), valid=True, verification="auto_approved"):
    return {"risk_level": risk, "status": status, "review_flags": list(flags),
            "citation_valid": valid, "verification_status": verification}


def test_green_needs_no_lawyer_even_when_no_law_was_needed():
    assert clause_decision(r("green")) == "no_lawyer"
    assert clause_decision(r("green", status="insufficient_grounding")) == "no_lawyer"


def test_green_that_skipped_a_risky_check_goes_to_an_expert():
    assert clause_decision(r("green", flags=["skipped_legal_check"])) == "expert"


def test_confirmed_red_means_lawyer_confirmed_amber_means_negotiate():
    assert clause_decision(r("red")) == "lawyer"
    assert clause_decision(r("red", status="partially_grounded")) == "lawyer"
    assert clause_decision(r("amber")) == "negotiate"


def test_unconfirmed_answers_go_to_a_human_expert():
    assert clause_decision(r("red", status="insufficient_grounding")) == "expert"
    assert clause_decision(r("red", status="human_review_required")) == "expert"
    assert clause_decision(r("amber", flags=["jurisdiction_uncertain"])) == "expert"
    assert clause_decision(r("red", valid=False)) == "expert"


def test_reviewer_approval_confirms_the_clause():
    assert clause_decision(r("red", status="insufficient_grounding", verification="human_verified")) == "lawyer"


def test_document_decision_takes_the_most_serious_and_counts():
    clauses = [r("green"), r("amber"), r("red", status="human_review_required"), r("red")]
    out = document_decision(clauses)
    assert out["decision"] == "lawyer"
    assert out["counts"] == {"no_lawyer": 1, "negotiate": 1, "lawyer": 1, "expert": 1}
    assert document_decision([r("green"), r("amber", status="insufficient_grounding")])["decision"] == "expert"
    assert document_decision([r("green"), r("amber")])["decision"] == "negotiate"
    assert document_decision([r("green")])["decision"] == "sign"
    assert document_decision([])["decision"] == "sign"
