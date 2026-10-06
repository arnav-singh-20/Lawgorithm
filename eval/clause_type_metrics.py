"""
Shared clause-type classification metrics, so the kNN baseline
(eval/eval_clause_types.py) and fine-tuned classifiers
(scripts/train_clause_classifier.py) are scored identically.
"""

from collections import Counter

OTHER = "other"


def classification_report(
    truth: list[str],
    predicted: list[str],
    confidence: list[float],
    min_confidence: float,
) -> dict:
    """
    top1_accuracy / macro_f1: raw top-1 prediction vs label.
    coverage / selective_accuracy: the share of clauses where the
    prediction is confident enough (>= min_confidence) and not "other" --
    i.e. where the agent actually receives a hint -- and how often that
    hint is right.
    """
    tp, fp, fn = Counter(), Counter(), Counter()
    accepted = accepted_correct = 0
    for t, p, c in zip(truth, predicted, confidence):
        if p == t:
            tp[t] += 1
        else:
            fn[t] += 1
            if p:
                fp[p] += 1
        if c >= min_confidence and p != OTHER:
            accepted += 1
            accepted_correct += p == t

    per_type = {}
    for label in sorted(set(tp) | set(fn) | set(fp)):
        prec = tp[label] / (tp[label] + fp[label]) if tp[label] + fp[label] else 0.0
        rec = tp[label] / (tp[label] + fn[label]) if tp[label] + fn[label] else 0.0
        per_type[label] = {
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "support": tp[label] + fn[label],
        }
    supported = [v for v in per_type.values() if v["support"]]
    n = len(truth)
    return {
        "n": n,
        "top1_accuracy": round(sum(tp.values()) / n, 4),
        "macro_f1": round(sum(v["f1"] for v in supported) / len(supported), 4),
        "min_confidence": min_confidence,
        "coverage": round(accepted / n, 4),
        "selective_accuracy": round(accepted_correct / accepted, 4) if accepted else None,
        "per_type": per_type,
    }
