"""
Phase 4 -- provenance check for the statute corpus.

Every section the agent can cite should say where its text came from
and when someone last checked it. This lists every section in
data/statutes/*.json that is missing any provenance field, so the
team's dataset research has a concrete to-do list instead of a vague
"verify the corpus".

    python -m scripts.validate_statutes
    python -m scripts.validate_statutes --strict   # exit 1 if anything is missing (for CI)
"""

import argparse
import json
import re
import sys

from backend.config import STATUTES_DIR
from backend.rag.chunking import PROVENANCE_FIELDS

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check() -> list[dict]:
    problems = []
    for path in sorted(STATUTES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for statute in data.get("statutes", []):
            for section in statute.get("sections", []):
                missing = [f for f in PROVENANCE_FIELDS if not section.get(f)]
                bad_dates = [
                    f for f in ("effective_date", "last_verified")
                    if section.get(f) and not DATE_RE.match(str(section[f]))
                ]
                if section.get("verified") is False:
                    missing.append("verified=false")
                if missing or bad_dates:
                    problems.append({
                        "file": path.name,
                        "law": statute["law"],
                        "section": section.get("section"),
                        "missing": missing,
                        "bad_dates": bad_dates,
                    })
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    problems = check()
    for p in problems:
        detail = ", ".join(p["missing"] + [f"{f} not YYYY-MM-DD" for f in p["bad_dates"]])
        print(f"{p['file']}: {p['law']} s.{p['section']} -> {detail}")
    print(f"\n{len(problems)} section(s) with incomplete provenance.")
    if args.strict and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
