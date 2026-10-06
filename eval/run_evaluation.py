"""
Runs the agent against the expert-labelled gold set
(data/evaluation/gold_clauses.json) and reports Phase 15/16 metrics.

Expected gold_clauses.json shape:

[
  {
    "clause_id": "test_001",
    "clause_text": "...",
    "risk_label": "amber",
    "expected_sources": ["ica_1872_section_27"],
    "expected_status": "grounded"   # or "insufficient_grounding" for
                                      # clauses deliberately designed to
                                      # test whether the system abstains
  },
  ...
]

Include some clauses where expected_status is "insufficient_grounding"
-- clauses with no real answer in the corpus -- otherwise you'll never
find out whether the system knows when NOT to answer (Phase 8/16).

Not runnable in a meaningful way until the gold set exists -- this is
the harness, wired up and ready to go the moment it does.
"""

import json

from backend.config import EVALUATION_DIR
from backend.agent.agent import run_agent
from backend.confidence.calibration import brier_score, expected_calibration_error
from eval.metrics import (
    risk_accuracy,
    grounding_precision,
    hallucination_rate,
    claim_level_hallucination_rate,
    abstention_accuracy,
    readability_improvement,
)


def load_gold():
    path = EVALUATION_DIR / "gold_clauses.json"
    if not path.exists():
        print(f"No gold set found at {path} yet. Nothing to evaluate.")
        return []

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(provider=None):
    """
    `provider` is an optional LLMProvider override -- see
    backend/agent/agent.py::run_agent. Lets this harness be exercised
    with a scripted/oracle provider (tests/fakes/) when no live Gemini
    access is available, to prove the metrics pipeline itself works
    correctly. Production runs should omit it.

    Returns the computed metrics dict (in addition to printing them) so
    callers -- including tests -- can assert on the numbers rather than
    just eyeballing stdout.
    """
    gold = load_gold()
    if not gold:
        return {}

    predictions = []
    skipped = []
    for item in gold:
        result = run_agent(item["clause_text"], clause_id=item["clause_id"], provider=provider)
        if "error" in result:
            skipped.append(item["clause_id"])
            continue
        result["clause_id"] = item["clause_id"]
        predictions.append(result)

    if skipped:
        print(f"Warning: {len(skipped)} clause(s) failed and were excluded from scoring: {skipped}")

    # Match by clause_id, not list position -- a single agent failure
    # partway through would otherwise shift every later pairing by one
    # and silently corrupt every metric after it.
    predictions_by_id = {p["clause_id"]: p for p in predictions}

    metrics = {
        "risk_accuracy": risk_accuracy(predictions, gold),
        "grounding_precision": grounding_precision(predictions, gold),
        "fabricated_citation_rate": hallucination_rate(predictions),
        "claim_level_hallucination_rate": claim_level_hallucination_rate(predictions),
        "abstention_accuracy": abstention_accuracy(predictions, gold),
        "skipped_clause_ids": skipped,
        "num_predictions": len(predictions),
        "num_gold": len(gold),
    }

    print("Risk accuracy:                    %.1f%%" % (metrics["risk_accuracy"] * 100))
    print("Grounding precision:               %.1f%%" % (metrics["grounding_precision"] * 100))
    print("Fabricated-citation rate:          %.1f%%" % (metrics["fabricated_citation_rate"] * 100))
    print("Claim-level hallucination rate:    %.1f%%" % (metrics["claim_level_hallucination_rate"] * 100))
    print("Abstention accuracy:               %.1f%%" % (metrics["abstention_accuracy"] * 100))

    # Phase 13/14 calibration: is the engine's confidence honest? A
    # prediction counts as correct when the risk tier matches AND every
    # expected source was actually cited (or none were expected and
    # none were cited).
    calibration_pairs = [
        (p["confidence"], _is_correct(p, gold_item))
        for gold_item in gold
        if (p := predictions_by_id.get(gold_item["clause_id"])) is not None
    ]
    metrics["ece"] = expected_calibration_error(calibration_pairs)
    metrics["brier"] = brier_score(calibration_pairs)
    print("Expected Calibration Error:        %.4f" % metrics["ece"])
    print("Brier score:                       %.4f" % metrics["brier"])

    readability_deltas = []
    for gold_item in gold:
        prediction = predictions_by_id.get(gold_item["clause_id"])
        if prediction is None:
            continue
        readability_deltas.append(
            readability_improvement(gold_item["clause_text"], prediction["plain_explanation"])
        )

    if readability_deltas:
        avg_fk = sum(d["flesch_kincaid_grade_improvement"] for d in readability_deltas) / len(readability_deltas)
        metrics["avg_flesch_kincaid_grade_improvement"] = avg_fk
        print("Avg. Flesch-Kincaid grade-level improvement: %.2f" % avg_fk)

    return metrics


def _is_correct(prediction: dict, gold_item: dict) -> bool:
    expected = set(gold_item.get("expected_sources", []))
    cited = {sid for c in prediction.get("claims", []) for sid in c.get("supporting_source_ids", [])}
    sources_ok = expected <= cited if expected else not cited
    return prediction.get("risk_level") == gold_item.get("risk_label") and sources_ok


if __name__ == "__main__":
    run()
