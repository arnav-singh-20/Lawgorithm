"""
Phase 15 evaluation metrics.

Targets from the project proposal:
    Risk classification agreement  >= 90%
    Statutory grounding precision  >= 90%
    Hallucination rate             < 5%

These operate on the agent's predictions vs. the expert-labelled gold
set (data/evaluation/gold_clauses.json), once it exists.
"""

from typing import List, Dict

import textstat


def risk_accuracy(predictions: List[dict], gold: List[dict]) -> float:
    """
    predictions/gold: aligned lists of {"clause_id": ..., "risk_level": ...}
    Returns the fraction where predicted risk_level == gold risk_label.
    """
    gold_by_id = {g["clause_id"]: g["risk_label"] for g in gold}

    correct = 0
    total = 0
    for pred in predictions:
        gold_label = gold_by_id.get(pred["clause_id"])
        if gold_label is None:
            continue
        total += 1
        if pred["risk_level"] == gold_label:
            correct += 1

    return correct / total if total else 0.0


def grounding_precision(predictions: List[dict], gold: List[dict]) -> float:
    """
    Fraction of cited source_ids that appear in the gold clause's
    expected_sources list. Measures "did we cite real, relevant law"
    rather than hallucinated/irrelevant sections.

    gold items: {"clause_id": ..., "expected_sources": ["ica_1872_section_27", ...]}
    predictions: {"clause_id": ..., "retrieved_source_ids": [...]}
      (or, for claim-level precision, iterate claims' supporting_source_ids instead --
      retrieved_source_ids includes everything seen, cited or not)
    """
    gold_by_id = {g["clause_id"]: set(g.get("expected_sources", [])) for g in gold}

    correct = 0
    total = 0
    for pred in predictions:
        expected_sources = gold_by_id.get(pred["clause_id"])
        if expected_sources is None:
            continue

        cited_source_ids = {
            sid
            for claim in pred.get("claims", [])
            for sid in claim.get("supporting_source_ids", [])
        }

        for source_id in cited_source_ids:
            total += 1
            if source_id in expected_sources:
                correct += 1

    return correct / total if total else 0.0


def hallucination_rate(predictions: List[dict], valid_law_names: set = None) -> float:
    """
    Fraction of predictions where citation_valid is False -- i.e. the
    agent cited a source_id that was never actually retrieved during
    that clause's search loop (a fabricated citation). This mirrors
    what backend/validation/citation_validator.py already computes at
    generation time; this function just aggregates it across a batch
    for reporting. `valid_law_names` is accepted but unused -- kept for
    call-site compatibility with older gold sets built before the
    claims/source_id schema existed.

    IMPORTANT: citation_valid=True only means "this source_id was really
    retrieved", not "the retrieved text actually supports the claim".
    That distinction is claim_level_hallucination_rate() below, which
    uses the grounding verifier's verdicts instead of citation validity
    alone. Treat the two as complementary:
      hallucination_rate            = "did it cite a source that was never retrieved"
      claim_level_hallucination_rate = "did the retrieved source actually support the claim"
      grounding_precision            = "did it cite the *expected* source for this clause"
    None of these substitute for periodic manual expert review.
    """
    total = len(predictions)
    if total == 0:
        return 0.0

    fabricated = sum(1 for pred in predictions if pred.get("citation_valid") is False)
    return fabricated / total


def claim_level_hallucination_rate(predictions: List[dict]) -> float:
    """
    Phase 16 claim-level hallucination: unsupported claims / total
    claims, using each prediction's own grounding verdicts (i.e. what
    backend/validation/claim_validator.py already decided). This is a
    tighter, more honest hallucination measure than
    hallucination_rate() above -- it catches "cited a real law that
    doesn't actually say this" as well as "invented a law that doesn't
    exist", because both end up UNSUPPORTED after grounding verification.
    """
    total = 0
    unsupported = 0

    for pred in predictions:
        for claim in pred.get("claims", []):
            total += 1
            # A claim is only as good as its supporting sources; if the
            # clause's overall grounding_status is "unsupported" we count
            # every claim in it as unsupported for this metric.
            if pred.get("grounding_status") == "unsupported":
                unsupported += 1

    return unsupported / total if total else 0.0


def abstention_accuracy(predictions: List[dict], gold: List[dict]) -> float:
    """
    Phase 16 abstention metric: when the gold set says the correct
    answer was INSUFFICIENT_GROUNDING (i.e. there's deliberately no
    good statutory answer for this clause), did the system correctly
    land on "insufficient_grounding" / "human_review_required" instead
    of confidently guessing?

    gold items expected to have "expected_status": "insufficient_grounding"
    for the clauses specifically designed to test this. Only those
    clauses are scored here -- this metric answers "does the system know
    when NOT to answer", not general status accuracy.
    """
    predictions_by_id = {p["clause_id"]: p for p in predictions}

    abstain_worthy = [g for g in gold if g.get("expected_status") == "insufficient_grounding"]
    if not abstain_worthy:
        return 0.0

    correctly_abstained = 0
    for gold_item in abstain_worthy:
        prediction = predictions_by_id.get(gold_item["clause_id"])
        if prediction is None:
            continue
        if prediction.get("status") in {"insufficient_grounding", "human_review_required"}:
            correctly_abstained += 1

    return correctly_abstained / len(abstain_worthy)


def readability_scores(text: str) -> Dict[str, float]:
    return {
        "flesch_kincaid_grade": textstat.flesch_kincaid_grade(text),
        "dale_chall_score": textstat.dale_chall_readability_score(text),
    }


def readability_improvement(original_clause: str, plain_explanation: str) -> Dict[str, float]:
    """
    Positive delta = explanation is easier to read than the original
    legal clause (lower grade level / lower Dale-Chall score is easier).
    """
    original = readability_scores(original_clause)
    simplified = readability_scores(plain_explanation)

    return {
        "flesch_kincaid_grade_improvement": original["flesch_kincaid_grade"]
        - simplified["flesch_kincaid_grade"],
        "dale_chall_score_improvement": original["dale_chall_score"]
        - simplified["dale_chall_score"],
    }
