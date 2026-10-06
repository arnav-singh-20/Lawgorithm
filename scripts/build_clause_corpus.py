"""
Build the clause-precedent corpus from the team's clause dataset.

Input: lawgorithm_train.jsonl -- 1.85M rows of
    {"task": "classify_clause", "input": "<classify_clause> ...", "label": "<section heading>"}
(plus 2 "summarize" rows: a CUAD readme, and a compilation of 18 Indian
legal templates -- the latter is exported to data/raw/indian_templates/).

What this dataset IS: real contract clauses (overwhelmingly US SEC
filings) labelled with their section heading. What it is NOT: Indian
law. So it feeds the clause_precedents index (clause-type
identification), never the statute index the agent cites from.

Steps:
  1. normalize each raw heading and map it to a canonical clause type
     (backend/rag/clause_taxonomy.py)
  2. drop exact duplicate clause texts (~42% of rows are duplicates)
  3. drop very short/long texts (headings-only fragments, whole-agreement dumps)
  4. deterministic hash-based train/test split (same clause always lands
     in the same split, across re-runs)
  5. per-type reservoir sampling so the index isn't 40% "governing law"
     boilerplate and embedding stays tractable on a laptop

    python -m scripts.build_clause_corpus lawgorithm_train.jsonl
    python -m scripts.build_clause_corpus lawgorithm_train.jsonl --per-type 3000 --test-per-type 300

Writes data/processed/clause_corpus/{train,test}.jsonl and stats.json.
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from backend.config import CLAUSE_CORPUS_DIR, RAW_DIR
from backend.rag.clause_taxonomy import CLAUSE_TYPES, OTHER, canonical_type, normalize_label

INPUT_TAG = re.compile(r"^\s*<\w+>\s*")
MIN_CHARS = 60
MAX_CHARS = 4000
TEST_BUCKET_MODULO = 10  # 1 in 10 unique clauses -> held-out test split


def _clause_hash(text: str) -> bytes:
    return hashlib.md5(re.sub(r"\s+", " ", text.lower()).encode("utf-8")).digest()


class _Reservoir:
    """Fixed-size uniform sample per key, single pass, bounded memory."""

    def __init__(self, cap_for, seed: int):
        self._cap_for = cap_for
        self._rng = random.Random(seed)
        self.items: dict[str, list] = defaultdict(list)
        self.seen: Counter = Counter()

    def add(self, key: str, item: dict) -> None:
        self.seen[key] += 1
        bucket, cap = self.items[key], self._cap_for(key)
        if len(bucket) < cap:
            bucket.append(item)
        else:
            j = self._rng.randrange(self.seen[key])
            if j < cap:
                bucket[j] = item


def _export_templates(text: str) -> int:
    """Split the Indian template compilation on its 'What is X?' headings."""
    out_dir = RAW_DIR / "indian_templates"
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = re.split(r"(?=What is [^?\n]{3,90}\?)", text)
    written = 0
    for part in parts:
        match = re.match(r"What is ([^?\n]{3,90})\?", part)
        if not match:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", match.group(1).lower()).strip("_")[:60]
        (out_dir / f"{slug}.txt").write_text(part.strip(), encoding="utf-8")
        written += 1
    return written


def build(input_path: Path, per_type: int, other_cap: int, test_per_type: int, seed: int) -> dict:
    cap = lambda k: other_cap if k == OTHER else per_type
    test_cap = lambda k: test_per_type
    train, test = _Reservoir(cap, seed), _Reservoir(test_cap, seed + 1)

    stats = Counter()
    seen_hashes: set[bytes] = set()
    raw_labels_per_type: dict[str, Counter] = defaultdict(Counter)
    templates_written = 0

    with open(input_path, encoding="utf-8") as f:
        for line in f:
            stats["rows"] += 1
            row = json.loads(line)

            if row.get("task") != "classify_clause":
                if "What is Lease Deed" in row.get("input", ""):
                    templates_written = _export_templates(INPUT_TAG.sub("", row["input"]))
                stats["non_classify_rows"] += 1
                continue

            text = INPUT_TAG.sub("", row.get("input", "")).strip()
            if not (MIN_CHARS <= len(text) <= MAX_CHARS):
                stats["length_filtered"] += 1
                continue

            digest = _clause_hash(text)
            if digest in seen_hashes:
                stats["duplicates"] += 1
                continue
            seen_hashes.add(digest)

            raw_label = normalize_label(row.get("label", ""))
            clause_type = canonical_type(raw_label)
            raw_labels_per_type[clause_type][raw_label] += 1

            item = {"clause_text": text, "raw_label": raw_label, "clause_type": clause_type}
            if digest[0] % TEST_BUCKET_MODULO == 0:
                test.add(clause_type, item)
            else:
                train.add(clause_type, item)

    CLAUSE_CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    for split_name, reservoir, prefix in (("train", train, "CP"), ("test", test, "CT")):
        with open(CLAUSE_CORPUS_DIR / f"{split_name}.jsonl", "w", encoding="utf-8") as out:
            n = 0
            for clause_type in sorted(reservoir.items):
                for item in reservoir.items[clause_type]:
                    n += 1
                    record = {"id": f"{prefix}_{n:07d}", "domain": CLAUSE_TYPES[clause_type].domain, **item}
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats[f"{split_name}_written"] = n

    summary = {
        "source": str(input_path),
        "counts": dict(stats),
        "unique_clauses": len(seen_hashes),
        "indian_templates_exported": templates_written,
        "per_type": {
            t: {
                "available_train": train.seen[t],
                "available_test": test.seen[t],
                "indexed": len(train.items[t]),
                "held_out": len(test.items[t]),
                "top_raw_labels": raw_labels_per_type[t].most_common(8),
            }
            for t in sorted(CLAUSE_TYPES, key=lambda t: -(train.seen[t] + test.seen[t]))
        },
    }
    with open(CLAUSE_CORPUS_DIR / "stats.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("--per-type", type=int, default=1500, help="max indexed clauses per canonical type")
    parser.add_argument("--other-cap", type=int, default=4000, help="max indexed clauses for 'other'")
    parser.add_argument("--test-per-type", type=int, default=200)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    summary = build(args.input, args.per_type, args.other_cap, args.test_per_type, args.seed)
    c = summary["counts"]
    print(f"Rows read: {c['rows']:,}  unique clauses: {summary['unique_clauses']:,}  "
          f"duplicates: {c.get('duplicates', 0):,}  length-filtered: {c.get('length_filtered', 0):,}")
    print(f"Indexed (train): {c['train_written']:,}  held-out (test): {c['test_written']:,}  "
          f"Indian templates exported: {summary['indian_templates_exported']}")
    print(f"\n{'clause type':28s} {'available':>10s} {'indexed':>8s} {'test':>6s}")
    for t, s in summary["per_type"].items():
        print(f"{t:28s} {s['available_train'] + s['available_test']:>10,d} {s['indexed']:>8d} {s['held_out']:>6d}")


if __name__ == "__main__":
    main()
