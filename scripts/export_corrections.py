"""
Phase 11 -- export the reviewer-correction dataset.

    python -m scripts.export_corrections
    python -m scripts.export_corrections --out data/processed/my_export.jsonl

One JSON line per reviewer decision: the AI's original prediction, the
human's final decision, the reason, and ai_was_correct. This is the
input for threshold calibration (scripts/calibrate_thresholds.py) and,
eventually, fine-tuning data (Phase 21).
"""

import argparse
import json
from pathlib import Path

from backend.config import PROCESSED_DIR
from backend.database.db import SessionLocal, init_db
from backend.verification.verification_service import correction_to_dict, list_corrections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=PROCESSED_DIR / "reviewer_corrections.jsonl")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        corrections = list_corrections(db)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            for c in corrections:
                f.write(json.dumps(correction_to_dict(c), ensure_ascii=False) + "\n")
    finally:
        db.close()

    correct = sum(1 for c in corrections if c.ai_was_correct)
    print(f"Exported {len(corrections)} correction(s) to {args.out} ({correct} where the AI was accepted unchanged).")


if __name__ == "__main__":
    main()
