from backend.validation.claim_validator import grounding_score_and_status


def test_all_supported_gives_supported_status():
    verdicts = [{"verdict": "SUPPORTED", "score": 1.0}, {"verdict": "SUPPORTED", "score": 1.0}]
    score, status = grounding_score_and_status(verdicts)
    assert score == 1.0
    assert status == "supported"


def test_all_unsupported_gives_unsupported_status():
    verdicts = [{"verdict": "UNSUPPORTED", "score": 0.0}]
    score, status = grounding_score_and_status(verdicts)
    assert score == 0.0
    assert status == "unsupported"


def test_mixed_verdicts_give_partially_supported():
    verdicts = [{"verdict": "SUPPORTED", "score": 1.0}, {"verdict": "UNSUPPORTED", "score": 0.0}]
    score, status = grounding_score_and_status(verdicts)
    assert score == 0.5
    assert status == "partially_supported"


def test_no_claims_is_unsupported_by_default():
    score, status = grounding_score_and_status([])
    assert score == 0.0
    assert status == "unsupported"
