"""
Phase C: Structured output validation, parsing robustness, and fallback tests.
"""

from backend.agent.agent import _parse_final_answer, _finalize, _sanitize_model_payload


def test_clean_json_parsing():
    raw = '{"plain_explanation": "Simple terms", "risk_level": "green", "legal_assessment": "None", "claims": [], "llm_confidence": 0.9}'
    parsed = _parse_final_answer(raw)
    assert parsed["risk_level"] == "green"
    assert parsed["llm_confidence"] == 0.9
    assert parsed["plain_explanation"] == "Simple terms"


def test_markdown_fence_json_parsing():
    raw = '```json\n{"plain_explanation": "Simple terms", "risk_level": "red", "legal_assessment": "Section 27", "claims": [], "llm_confidence": 0.8}\n```'
    parsed = _parse_final_answer(raw)
    assert parsed["risk_level"] == "red"
    assert parsed["llm_confidence"] == 0.8


def test_embedded_json_in_conversational_text():
    raw = 'Here is the analysis you requested:\n{"plain_explanation": "Restricts trade", "risk_level": "amber", "legal_assessment": "May violate law", "claims": [{"claim": "Restraint of trade", "supporting_source_ids": ["src_1"]}], "llm_confidence": 0.7}\nHope this helps!'
    parsed = _parse_final_answer(raw)
    assert parsed["risk_level"] == "amber"
    assert len(parsed["claims"]) == 1
    assert parsed["claims"][0]["supporting_source_ids"] == ["src_1"]


def test_risk_level_normalization():
    # "High" -> "red"
    p1 = _sanitize_model_payload({"risk_level": "High", "plain_explanation": "Test"})
    assert p1["risk_level"] == "red"

    # "Medium" -> "amber"
    p2 = _sanitize_model_payload({"risk_level": "Moderate", "plain_explanation": "Test"})
    assert p2["risk_level"] == "amber"

    # "Low" -> "green"
    p3 = _sanitize_model_payload({"risk_level": "Low", "plain_explanation": "Test"})
    assert p3["risk_level"] == "green"


def test_malformed_unparseable_output_fallback():
    raw = "I cannot give legal advice on this matter because I am an AI."
    parsed = _parse_final_answer(raw)
    assert parsed["risk_level"] == "amber"
    assert "cannot give legal advice" in parsed["plain_explanation"]
    assert parsed["llm_confidence"] == 0.2

    # Finalize should not crash, but route to verification
    context = {"retrieved_sources": []}
    result = _finalize(parsed, context, clause_id="malformed_1", clause_title="ERROR")
    assert "error" not in result
    assert result["verification_status"] == "pending"
    assert result["status"] in {"insufficient_grounding", "human_review_required"}


def test_missing_fields_and_invalid_types():
    # confidence as string "0.75" and missing claims
    p = _sanitize_model_payload({"plain_explanation": "OK", "risk_level": "green", "llm_confidence": "0.75"})
    assert p["llm_confidence"] == 0.75
    assert p["claims"] == []
