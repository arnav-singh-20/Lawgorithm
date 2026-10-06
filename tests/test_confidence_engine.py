from backend.confidence.engine import (
    ConfidenceInputs,
    calculate_confidence,
    determine_status,
    GROUNDED,
    PARTIALLY_GROUNDED,
    INSUFFICIENT_GROUNDING,
    HUMAN_REVIEW_REQUIRED,
)


def test_calculate_confidence_all_high_gives_high_score():
    inputs = ConfidenceInputs(
        retrieval_score=1.0,
        grounding_score=1.0,
        citation_valid=True,
        consistency_score=1.0,
        llm_confidence=1.0,
    )
    assert calculate_confidence(inputs) == 1.0


def test_calculate_confidence_invalid_citation_zeroes_that_factor():
    high = ConfidenceInputs(1.0, 1.0, True, 1.0, 1.0)
    low = ConfidenceInputs(1.0, 1.0, False, 1.0, 1.0)
    assert calculate_confidence(low) < calculate_confidence(high)


def test_calculate_confidence_is_bounded_0_to_1():
    inputs = ConfidenceInputs(0.0, 0.0, False, 0.0, 0.0)
    score = calculate_confidence(inputs)
    assert 0.0 <= score <= 1.0


def test_invalid_citation_always_forces_human_review():
    status = determine_status(confidence=0.99, citation_valid=False, grounding_score=1.0)
    assert status == HUMAN_REVIEW_REQUIRED


def test_low_grounding_forces_insufficient_grounding():
    status = determine_status(confidence=0.99, citation_valid=True, grounding_score=0.2)
    assert status == INSUFFICIENT_GROUNDING


def test_high_confidence_and_grounding_is_grounded():
    status = determine_status(confidence=0.97, citation_valid=True, grounding_score=0.9)
    assert status == GROUNDED


def test_medium_confidence_is_partially_grounded():
    status = determine_status(confidence=0.85, citation_valid=True, grounding_score=0.9)
    assert status == PARTIALLY_GROUNDED


def test_low_confidence_needs_human_review():
    status = determine_status(confidence=0.5, citation_valid=True, grounding_score=0.9)
    assert status == HUMAN_REVIEW_REQUIRED
