"""
Phase 9 named routing conditions: conflicting sources, jurisdiction
uncertainty, unverified source -- and that any of them forces review
even for an otherwise fully grounded, green clause.
"""

from backend.agent.agent import _finalize
from backend.risk.risk_rules import should_send_for_verification
from backend.risk.routing_flags import compute_review_flags, detect_states


def _src(sid, jurisdiction="India", **extra):
    return {"id": sid, "law": sid, "section": "1", "jurisdiction": jurisdiction, "text": "...", **extra}


def _claims(*ids):
    return [{"claim": "c", "supporting_source_ids": list(ids)}]


def test_detect_states_by_name_and_city():
    assert detect_states("Flat No. 4, Koramangala, Bengaluru 560034") == {"Karnataka"}
    assert detect_states("situated at New Delhi and Mumbai") == {"Delhi", "Maharashtra"}
    assert detect_states("no place named here") == set()


def test_central_law_only_raises_no_flags():
    sources = [_src("ica_27"), _src("tpa_108")]
    assert compute_review_flags(_claims("ica_27", "tpa_108"), sources) == []


def test_state_law_without_matching_state_is_uncertain():
    sources = [_src("drca_14", "Delhi")]
    assert compute_review_flags(_claims("drca_14"), sources, clause_text="Flat in Pune") == ["jurisdiction_uncertain"]


def test_state_law_with_matching_document_state_is_fine():
    sources = [_src("drca_14", "Delhi")]
    assert compute_review_flags(_claims("drca_14"), sources, known_states={"Delhi"}) == []


def test_central_plus_one_state_is_not_a_conflict():
    sources = [_src("tpa_108"), _src("drca_14", "Delhi")]
    flags = compute_review_flags(_claims("tpa_108", "drca_14"), sources, known_states={"Delhi"})
    assert "conflicting_sources" not in flags


def test_two_state_regimes_conflict():
    sources = [_src("drca_14", "Delhi"), _src("mta_11", "Model Act (applies only where adopted by a state)")]
    flags = compute_review_flags(_claims("drca_14", "mta_11"), sources, known_states={"Delhi"})
    assert "conflicting_sources" in flags
    assert "jurisdiction_uncertain" in flags  # the model act isn't established for Delhi


def test_only_cited_sources_count():
    """A state law that was retrieved but not relied on raises nothing."""
    sources = [_src("ica_27"), _src("drca_14", "Delhi")]
    assert compute_review_flags(_claims("ica_27"), sources) == []


def test_unverified_source_flag():
    sources = [_src("ica_27", verified=False)]
    assert compute_review_flags(_claims("ica_27"), sources) == ["unverified_source"]


def test_any_flag_forces_review():
    assert should_send_for_verification({"status": "grounded", "risk_level": "green", "review_flags": ["jurisdiction_uncertain"]})
    assert not should_send_for_verification({"status": "grounded", "risk_level": "green", "review_flags": []})


def test_finalize_routes_flagged_clause_to_review(monkeypatch):
    monkeypatch.setattr(
        "backend.validation.claim_validator._call_verifier",
        lambda prompt_claims: {c["claim_index"]: "SUPPORTED" for c in prompt_claims},
    )
    source = {**_src("drca_14", "Delhi"), "law": "Delhi Rent Control Act, 1958", "section": "14", "distance": 0.0}
    parsed = {
        "plain_explanation": "The landlord can evict you on these grounds.",
        "risk_level": "green",
        "legal_assessment": "Eviction grounds are governed by statute.",
        "recommended_action": "Nothing to do.",
        "claims": [{"claim": "Eviction requires statutory grounds.", "supporting_source_ids": ["drca_14"]}],
        "llm_confidence": 1.0,
    }
    context = {"retrieved_sources": [source], "clause_text": "Premises at Indiranagar, Bengaluru", "known_states": set()}

    result = _finalize(parsed, context, clause_id="5")

    assert result["status"] == "grounded"
    assert result["review_flags"] == ["jurisdiction_uncertain"]
    assert result["verification_status"] == "pending"
    assert result["cited_sources"][0]["law"] == "Delhi Rent Control Act, 1958"


# --- legal references in free text ---------------------------------------

from backend.validation.citation_validator import find_unbacked_references

ICA27 = {"law": "Indian Contract Act, 1872", "section": "27"}


def test_live_local_model_failure_is_caught():
    """The actual legal_assessment qwen2.5:3b produced for a non-compete clause."""
    text = ("Section 27 of the Indian Contract Act, 1872, states that agreements restraining a person are void. "
            "However, Section 39 of the same act allows the promisee to terminate the contract. Additionally, "
            "Section 23 of the Model Tenancy Act, 2021, discusses termination of tenancies.")
    assert find_unbacked_references(text, [ICA27]) == ["Section 39", "Section 23", "Model Tenancy Act, 2021"]


def test_backed_references_pass():
    text = "Under Section 27 of the Indian Contract Act, 1872 (the Contract Act), this restraint is void. See s. 27."
    assert find_unbacked_references(text, [ICA27]) == []


def test_no_citations_but_statute_named():
    assert find_unbacked_references("This violates the Payment of Wages Act, 1936.", []) == ["Payment of Wages Act, 1936"]


def test_plain_text_without_law_is_fine():
    assert find_unbacked_references("No legal question arises from a salary statement.", []) == []


def test_unbacked_reference_forces_review():
    flags = compute_review_flags([], [], legal_assessment="Section 23 of the Model Tenancy Act applies.")
    assert flags == ["unbacked_legal_reference"]
    assert should_send_for_verification({"status": "grounded", "risk_level": "green", "review_flags": flags})



def test_risky_clause_cannot_skip_the_legal_check():
    """Seen live: 'repossess without court proceedings' came back green with no search."""
    parsed = {
        "plain_explanation": "The landlord can take back the flat without going to court if rent is 15 days late.",
        "risk_level": "green", "legal_assessment": "Standard.", "claims": [], "llm_confidence": 0.9,
    }
    risky = {"retrieved_sources": [], "clause_type_info": {"clause_type": "eviction_default", "risk_prone": True}}
    result = _finalize(parsed, risky, clause_id="5")
    assert "skipped_legal_check" in result["review_flags"]
    assert result["verification_status"] == "pending"
    assert result["status"] != "grounded"

    # a genuinely factual clause type keeps the shortcut
    plain = {"retrieved_sources": [], "clause_type_info": {"clause_type": "salary_compensation", "risk_prone": False}}
    result = _finalize(dict(parsed, plain_explanation="You get Rs 50,000 a month."), plain, clause_id="1")
    assert result["status"] == "grounded" and result["verification_status"] == "auto_approved"
