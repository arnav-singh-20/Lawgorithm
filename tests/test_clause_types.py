"""
Clause-precedent layer: taxonomy mapping of raw dataset headings, the
kNN vote, how the hint reaches the agent -- and, most importantly,
that a precedent clause can never be cited as legal grounding.
"""

import json

import pytest

from backend.agent.agent import run_agent, _build_user_input
from backend.llm.base import ToolCall, TurnResult
from backend.rag.clause_index import vote
from backend.rag.clause_taxonomy import CLAUSE_TYPES, OTHER, canonical_type
from tests.fakes.scripted_provider import ScriptedProvider


@pytest.mark.parametrize(
    "raw_label, expected",
    [
        ("Non-Competition", "non_compete"),
        ("covenant not to compete", "non_compete"),
        ("Non-Solicitation of Employees", "non_solicitation"),
        ("termination for cause", "termination_for_cause"),
        ("termination without cause", "termination_notice"),
        ("security deposit", "security_deposit"),
        ("deposit accounts", OTHER),            # banking, not rental
        ("designation of a different lending office", OTHER),  # "rent" inside "different"
        ("base rent", "rent_payment"),
        ("press releases", OTHER),              # not a release of claims
        ("general release", "release_waiver_of_claims"),
        ("waiver of jury trial", "jury_waiver"),
        ("governing law and jurisdiction", "governing_law"),
        ("liquidated damages", "liquidated_damages_penalty"),
        ("exclusive remedy", OTHER),            # not employment exclusivity
        ("", OTHER),
    ],
)
def test_canonical_type_mapping(raw_label, expected):
    assert canonical_type(raw_label) == expected


def test_every_rule_target_is_a_known_type():
    from backend.rag.clause_taxonomy import LABEL_RULES

    assert {t for _, t in LABEL_RULES} <= set(CLAUSE_TYPES)


def _n(clause_type, distance):
    return {"clause_type": clause_type, "distance": distance}


def test_vote_picks_weighted_majority():
    result = vote([_n("non_compete", 0.1), _n("non_compete", 0.2), _n("confidentiality", 0.15)])
    assert result["clause_type"] == "non_compete"
    assert 0.6 < result["confidence"] < 0.7


def test_vote_abstains_when_split():
    result = vote([_n("a_type", 0.1), _n("b_type", 0.1), _n("c_type", 0.1)], min_confidence=0.45)
    assert result["clause_type"] is None


def test_vote_never_hints_other():
    result = vote([_n(OTHER, 0.05)] * 5)
    assert result["clause_type"] is None


def test_hint_is_added_to_prompt_and_marked_non_citable():
    info = {"clause_type": "non_compete", "label": "Non-compete", "confidence": 0.8,
            "statute_query": "restraint of trade", "risk_prone": True}
    text = _build_user_input("Employee shall not compete.", info)
    assert "Non-compete" in text and "NOT a legal source" in text and "restraint of trade" in text
    assert _build_user_input("x", None) == "CLAUSE TO EXPLAIN (explain only this clause):\n\nx"
    # the clause always comes last, after any background
    assert _build_user_input("the clause", info, "Summary: a lease").endswith("the clause")


def test_precedent_ids_cannot_be_cited(monkeypatch):
    """
    Even if the model copies a precedent id from the hint into a claim,
    the citation validator must reject it: precedents never enter
    retrieved_sources.
    """
    monkeypatch.setattr(
        "backend.agent.agent.classify_clause_type",
        lambda text: {"clause_type": "non_compete", "label": "Non-compete", "confidence": 0.9,
                      "statute_query": "restraint of trade", "risk_prone": True,
                      "precedents": [{"id": "CP_0000042"}]},
    )
    monkeypatch.setattr("backend.agent.tools.search_legal_reference_structured", lambda query, domain=None: [])
    monkeypatch.setattr(
        "backend.validation.claim_validator._call_verifier",
        lambda prompt_claims: {c["claim_index"]: "SUPPORTED" for c in prompt_claims},
    )
    final = json.dumps({
        "plain_explanation": "You can't work for competitors.",
        "risk_level": "amber",
        "legal_assessment": "Similar clauses are common.",
        "claims": [{"claim": "This is enforceable.", "supporting_source_ids": ["CP_0000042"]}],
        "llm_confidence": 0.9,
    })
    provider = ScriptedProvider([
        TurnResult(tool_calls=[ToolCall(id="c1", name="search_legal_reference", arguments={"query": "non compete"})],
                   final_text=None, raw_state=None),
        TurnResult(tool_calls=[], final_text=final, raw_state=None),
    ])

    result = run_agent("Employee shall not compete for 2 years.", clause_id="3", provider=provider)

    assert result["citation_valid"] is False
    assert result["status"] == "human_review_required"
    assert result["clause_type"]["clause_type"] == "non_compete"
