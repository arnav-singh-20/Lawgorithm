from backend.risk.risk_rules import should_send_for_verification, get_overall_document_risk


def test_non_grounded_status_triggers_verification():
    result = {"status": "partially_grounded", "risk_level": "green"}
    assert should_send_for_verification(result) is True


def test_insufficient_grounding_triggers_verification():
    result = {"status": "insufficient_grounding", "risk_level": "amber"}
    assert should_send_for_verification(result) is True


def test_red_risk_always_triggers_verification_even_when_grounded():
    result = {"status": "grounded", "risk_level": "red"}
    assert should_send_for_verification(result) is True


def test_grounded_non_red_skips_verification():
    result = {"status": "grounded", "risk_level": "amber"}
    assert should_send_for_verification(result) is False


def test_overall_document_risk_is_the_max():
    results = [{"risk_level": "green"}, {"risk_level": "amber"}, {"risk_level": "green"}]
    assert get_overall_document_risk(results) == "amber"

    results = [{"risk_level": "red"}, {"risk_level": "green"}]
    assert get_overall_document_risk(results) == "red"

    assert get_overall_document_risk([]) == "green"
