"""
The plain decision a person acts on -- the human-in-the-loop outcome.

Risk colour says how bad a clause is; confidence/status say how sure
Lawgorithm is. Neither tells someone what to DO, so every clause (and the
whole document) is turned into exactly one decision:

    no_lawyer   "No lawyer needed"                    green, nothing risky skipped
    negotiate   "Ask for a change -- no lawyer needed" amber, and the law behind it is confirmed
    lawyer      "Talk to a lawyer before signing"     red, and the law behind it is confirmed
    expert      "Needs a human expert check"          the AI could not confirm its own answer

"Confirmed" means: the claims cite sections that were really retrieved,
the grounding check agrees they say so (status grounded or partially
grounded), and no routing flag fired (conflicting sources, wrong state,
unverified source, ...). A reviewer's approval also confirms a clause.
When an answer isn't confirmed, Lawgorithm doesn't guess a decision --
it hands the clause to a person. Pure functions, no I/O.
"""

NO_LAWYER, NEGOTIATE, LAWYER, EXPERT = "no_lawyer", "negotiate", "lawyer", "expert"
DECISIONS = (NO_LAWYER, NEGOTIATE, LAWYER, EXPERT)

CONFIRMED_STATUSES = {"grounded", "partially_grounded"}


def is_confirmed(result: dict) -> bool:
    if result.get("verification_status") == "human_verified":
        return True
    return (
        result.get("status") in CONFIRMED_STATUSES
        and result.get("citation_valid", True) is not False
        and not result.get("review_flags")
    )


def clause_decision(result: dict) -> str:
    risk = result.get("risk_level")
    if risk == "green":
        # a risk-prone clause marked green without any legal check is not
        # "fine", it's unchecked (routing flag skipped_legal_check)
        return EXPERT if "skipped_legal_check" in (result.get("review_flags") or []) else NO_LAWYER
    if not is_confirmed(result):
        return EXPERT
    return LAWYER if risk == "red" else NEGOTIATE


def document_decision(clause_results: list[dict]) -> dict:
    """
    The headline for the whole contract: the most serious clause decision
    wins (lawyer > expert > negotiate > no_lawyer), with per-decision counts
    so the page can say "1 for a lawyer, 3 need an expert check".
    """
    counts = {d: 0 for d in DECISIONS}
    for result in clause_results:
        counts[result.get("decision") or clause_decision(result)] += 1
    for decision in (LAWYER, EXPERT, NEGOTIATE):
        if counts[decision]:
            return {"decision": decision, "counts": counts}
    return {"decision": "sign", "counts": counts}
