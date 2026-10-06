"""
Phase 13 -- measure the clause-precedent retrieval/classifier on the
held-out split (data/processed/clause_corpus/test.jsonl).

Unlike eval/run_evaluation.py (needs a live LLM + expert gold set), this
produces REAL numbers locally: the held-out clauses never entered the
index (hash-based split in scripts/build_clause_corpus.py), and their
labels come from the dataset.

Reports:
  - top-1 accuracy and macro-F1 of the kNN vote (all types)
  - coverage / selective accuracy: how often the vote clears
    CLAUSE_TYPE_MIN_CONFIDENCE, and how accurate it is when it does
    (that's the number that matters -- below the bar the agent gets no hint)
  - retrieval precision@K and recall@K (any neighbour of the right
    type in the top K) and MRR of the first correct-type neighbour
  - per-type precision / recall / F1

    python -m eval.eval_clause_types
    python -m eval.eval_clause_types --limit 1000 --json

Caveat: labels are section headings mapped to types by rules
(rag/clause_taxonomy.py), so some "errors" are label noise (e.g. a
"Miscellaneous" heading over a governing-law clause).
"""

import argparse
import json
import random

from backend.config import CLAUSE_CORPUS_DIR, CLAUSE_TYPE_MIN_CONFIDENCE
from backend.rag.clause_index import DEFAULT_K, ClauseIndex, vote
from eval.clause_type_metrics import classification_report

QUERY_BATCH = 256


def evaluate(records: list[dict], index: ClauseIndex, k: int = DEFAULT_K) -> dict:
    all_neighbours = []
    for start in range(0, len(records), QUERY_BATCH):
        all_neighbours.extend(index.query_many([r["clause_text"] for r in records[start:start + QUERY_BATCH]], k=k))

    predicted, confidence = [], []
    precision_sum = recall_hits = rr_sum = 0.0
    for r, neighbours in zip(records, all_neighbours):
        truth = r["clause_type"]
        result = vote(neighbours, min_confidence=0.0)  # raw top-1, no abstention
        predicted.append(result["ranked"][0][0] if result["ranked"] else None)
        confidence.append(result["confidence"])

        types = [n["clause_type"] for n in neighbours]
        precision_sum += sum(t == truth for t in types) / max(len(types), 1)
        if truth in types:
            recall_hits += 1
            rr_sum += 1.0 / (types.index(truth) + 1)

    n = len(records)
    report = classification_report(
        truth=[r["clause_type"] for r in records],
        predicted=predicted,
        confidence=confidence,
        min_confidence=CLAUSE_TYPE_MIN_CONFIDENCE,
    )
    report.update({
        "k": k,
        f"precision@{k}": round(precision_sum / n, 4),
        f"recall@{k}": round(recall_hits / n, 4),
        "mrr": round(rr_sum / n, 4),
    })
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="random sample of the test split (faster)")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    path = CLAUSE_CORPUS_DIR / "test.jsonl"
    if not path.exists():
        print(f"No held-out split at {path} -- run scripts.build_clause_corpus first.")
        return
    records = [json.loads(line) for line in open(path, encoding="utf-8")]
    if args.limit:
        records = random.Random(args.seed).sample(records, min(args.limit, len(records)))

    index = ClauseIndex.get()
    if index.count() == 0:
        print("Clause precedent index is empty -- run `python -m backend.rag.clause_index` first.")
        return

    report = evaluate(records, index, k=args.k)
    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Held-out clauses: {report['n']}  (index size {index.count():,}, k={report['k']})")
    print(f"Top-1 accuracy: {report['top1_accuracy']:.1%}   macro-F1: {report['macro_f1']:.3f}")
    print(f"Hint coverage (vote >= {report['min_confidence']}, not 'other'): {report['coverage']:.1%}  "
          f"accuracy when hinted: {report['selective_accuracy']:.1%}")
    print(f"precision@{args.k}: {report[f'precision@{args.k}']:.3f}  recall@{args.k}: "
          f"{report[f'recall@{args.k}']:.3f}  MRR: {report['mrr']:.3f}")
    print(f"\n{'type':28s} {'prec':>6s} {'rec':>6s} {'f1':>6s} {'n':>5s}")
    for t, v in sorted(report["per_type"].items(), key=lambda x: -x[1]["f1"]):
        print(f"{t:28s} {v['precision']:6.2f} {v['recall']:6.2f} {v['f1']:6.2f} {v['support']:5d}")


if __name__ == "__main__":
    main()
