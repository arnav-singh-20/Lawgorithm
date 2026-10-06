"""
Confidence calibration (Phases 13/14).

Answers: "when the engine says 0.95, is it right ~95% of the time?"
Works on any list of (confidence, was_correct) pairs -- from the
reviewer-corrections table (Phase 11) or from an expert-labelled
evaluation run. Pure functions, no I/O.

  - expected_calibration_error / brier_score: how well confidence
    matches observed accuracy (lower is better for both).
  - reliability_bins: the per-bucket table behind ECE, for a
    reliability diagram.
  - recommend_threshold: the lowest auto-approve threshold that still
    achieves a target precision (e.g. 95%) on the observed data, with a
    minimum-support guard so a handful of reviews can't move it.
"""

from dataclasses import dataclass

DEFAULT_BINS = 10
MIN_SUPPORT_FOR_THRESHOLD = 30


@dataclass
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float


def _validate(pairs: list[tuple[float, bool]]) -> None:
    for conf, _ in pairs:
        if not 0.0 <= conf <= 1.0:
            raise ValueError(f"confidence {conf} outside [0, 1]")


def reliability_bins(pairs: list[tuple[float, bool]], n_bins: int = DEFAULT_BINS) -> list[CalibrationBin]:
    _validate(pairs)
    bins = []
    for b in range(n_bins):
        lower, upper = b / n_bins, (b + 1) / n_bins
        # last bin is closed on the right so confidence == 1.0 is counted
        members = [(c, y) for c, y in pairs if lower <= c < upper or (b == n_bins - 1 and c == 1.0)]
        if members:
            bins.append(CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_confidence=sum(c for c, _ in members) / len(members),
                accuracy=sum(1 for _, y in members if y) / len(members),
            ))
    return bins


def expected_calibration_error(pairs: list[tuple[float, bool]], n_bins: int = DEFAULT_BINS) -> float:
    if not pairs:
        return 0.0
    total = len(pairs)
    return sum(b.count / total * abs(b.accuracy - b.mean_confidence) for b in reliability_bins(pairs, n_bins))


def brier_score(pairs: list[tuple[float, bool]]) -> float:
    if not pairs:
        return 0.0
    _validate(pairs)
    return sum((c - (1.0 if y else 0.0)) ** 2 for c, y in pairs) / len(pairs)


def recommend_threshold(
    pairs: list[tuple[float, bool]],
    target_precision: float = 0.95,
    min_support: int = MIN_SUPPORT_FOR_THRESHOLD,
) -> dict:
    """
    Scans candidate thresholds (every observed confidence value) and
    returns the LOWEST one where, among items at or above it, accuracy
    >= target_precision and at least `min_support` items qualify. Lowest
    = auto-approves as much as possible without dropping below target.

    Returns {"threshold": None, ...} with a reason when no threshold
    qualifies -- the caller must keep the current value in that case,
    never fall back to a guess.
    """
    _validate(pairs)
    if len(pairs) < min_support:
        return {
            "threshold": None,
            "reason": f"only {len(pairs)} labelled decisions; need at least {min_support}",
        }

    for t in sorted({c for c, _ in pairs}):
        above = [y for c, y in pairs if c >= t]
        if len(above) < min_support:
            break
        precision = sum(above) / len(above)
        if precision >= target_precision:
            return {
                "threshold": round(t, 4),
                "precision_at_threshold": round(precision, 4),
                "coverage": round(len(above) / len(pairs), 4),
                "support": len(above),
            }

    return {
        "threshold": None,
        "reason": f"no threshold reaches {target_precision:.0%} precision with >= {min_support} items above it",
    }


def calibration_report(
    pairs: list[tuple[float, bool]],
    current_threshold: float,
    target_precision: float = 0.95,
) -> dict:
    above_current = [y for c, y in pairs if c >= current_threshold]
    return {
        "n": len(pairs),
        "overall_accuracy": round(sum(1 for _, y in pairs if y) / len(pairs), 4) if pairs else None,
        "ece": round(expected_calibration_error(pairs), 4),
        "brier": round(brier_score(pairs), 4),
        "current_threshold": current_threshold,
        "precision_at_current_threshold": (
            round(sum(above_current) / len(above_current), 4) if above_current else None
        ),
        "coverage_at_current_threshold": round(len(above_current) / len(pairs), 4) if pairs else None,
        "recommendation": recommend_threshold(pairs, target_precision),
        "bins": [b.__dict__ for b in reliability_bins(pairs)],
    }
