"""
Phase 14 -- calibrate the 95% auto-approve threshold against real
reviewer decisions.

Reads the reviewer_corrections table (Phase 11). Each resolved review
is one labelled data point: (the confidence the engine assigned, whether
the reviewer accepted the AI output unchanged).

    python -m scripts.calibrate_thresholds
    python -m scripts.calibrate_thresholds --target 0.97 --json

Never edits GROUNDED_THRESHOLD itself -- it prints the evidence and a
recommendation; a person changes the constant in
backend/confidence/engine.py once the support is large enough to
trust. Caveat: the review queue is a BIASED sample (only flagged
clauses get reviewed, so RED and low-confidence items are
over-represented). Treat the recommendation as a lower bound until an
unbiased expert-labelled set (eval/run_evaluation.py) exists.
"""

import argparse
import json

from backend.confidence.calibration import calibration_report
from backend.confidence.engine import GROUNDED_THRESHOLD
from backend.database.db import SessionLocal, init_db
from backend.verification.verification_service import list_corrections


def load_pairs() -> list[tuple[float, bool]]:
    init_db()
    db = SessionLocal()
    try:
        return [
            (float(c.ai_confidence), bool(c.ai_was_correct))
            for c in list_corrections(db)
            if c.ai_confidence is not None and c.ai_was_correct is not None
        ]
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=float, default=0.95, help="target precision for auto-approval")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    pairs = load_pairs()
    if not pairs:
        print("No resolved reviews yet -- nothing to calibrate against. "
              "Resolve flagged clauses in the reviewer dashboard first.")
        return

    report = calibration_report(pairs, GROUNDED_THRESHOLD, args.target)
    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Labelled decisions: {report['n']}  overall AI accuracy: {report['overall_accuracy']:.1%}")
    print(f"ECE: {report['ece']:.4f}  Brier: {report['brier']:.4f}")
    print(f"Current threshold {GROUNDED_THRESHOLD}: precision {report['precision_at_current_threshold']}, "
          f"coverage {report['coverage_at_current_threshold']}")
    rec = report["recommendation"]
    if rec["threshold"] is None:
        print(f"No recommendation: {rec['reason']}. Keep the current threshold.")
    else:
        print(f"Recommended threshold for {args.target:.0%} precision: {rec['threshold']} "
              f"(precision {rec['precision_at_threshold']:.1%}, coverage {rec['coverage']:.1%}, n={rec['support']})")
    print("\nReliability bins (confidence -> observed accuracy):")
    for b in report["bins"]:
        print(f"  [{b['lower']:.1f}, {b['upper']:.1f})  n={b['count']:4d}  "
              f"mean conf {b['mean_confidence']:.2f}  accuracy {b['accuracy']:.2f}")


if __name__ == "__main__":
    main()
