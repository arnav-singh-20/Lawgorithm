"""
Prefetch mode (config.AGENT_MODE="prefetch", the production default):
Lawgorithm searches the statute library itself and the model answers in
ONE request with no tools -- ~4x fewer tokens than the ReAct loop.
"""

import json

from backend.agent import agent
from backend.llm.base import TurnResult


SOURCES = {
    "restraint": {"id": "ica_1872_section_27", "law": "Indian Contract Act, 1872", "section": "27",
                  "title": "Agreement in restraint of trade, void", "distance": 0.4,
                  "text": "Every agreement by which any one is restrained from exercising a lawful profession, trade or business of any kind, is to that extent void."},
    "penalty": {"id": "ica_1872_section_74", "law": "Indian Contract Act, 1872", "section": "74",
                "title": "Compensation for breach of contract where penalty stipulated for", "distance": 0.9,
                "text": "When a contract has been broken, if a sum is named in the contract as the amount to be paid in case of such breach..."},
}


class OneShotProvider:
    """Records the single request and answers with a fixed JSON."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def start_turn(self, system_prompt, user_input, tools):
        self.calls.append({"system": system_prompt, "input": user_input, "tools": tools})
        return TurnResult(tool_calls=[], final_text=json.dumps(self.answer), raw_state=None)

    def continue_turn(self, *a, **k):
        raise AssertionError("prefetch mode must not continue the conversation")

    def simple_completion(self, system_prompt, user_input):
        return json.dumps({"verdicts": [{"claim_index": 0, "verdict": "supported"}]})


def _fake_search(monkeypatch, queries):
    def search(query, domain=None, top_k=3):
        queries.append(query)
        return [SOURCES["restraint"], SOURCES["penalty"]] if "restraint" in query else [SOURCES["restraint"]]
    monkeypatch.setattr(agent, "search_legal_reference_structured", search)
    monkeypatch.setattr(agent, "verify_grounding",
                        lambda claims, sources: [{"claim_index": 0, "verdict": "supported", "score": 1.0}] if claims else [])


def test_one_request_no_tools_law_in_message(monkeypatch):
    queries = []
    _fake_search(monkeypatch, queries)
    monkeypatch.setattr(agent, "classify_clause_type", lambda text: {
        "clause_type": "non_compete", "label": "Non-compete", "confidence": 0.9,
        "statute_query": "restraint of trade agreement void", "risk_prone": True, "domain": "employment"})
    llm = OneShotProvider({"plain_explanation": "You can't work for a rival for 2 years.", "risk_level": "red",
                           "legal_assessment": "Likely void under s.27.", "recommended_action": "Ask to remove it.",
                           "claims": [{"claim": "Restraint of trade is void.", "supporting_source_ids": ["ica_1872_section_27"]}],
                           "llm_confidence": 0.8})

    result = agent.run_agent("For 2 years after leaving you shall not join a competitor.", "7", "NON-COMPETE",
                             provider=llm, mode="prefetch")

    assert len(llm.calls) == 1 and llm.calls[0]["tools"] == []
    assert "LAW FOUND FOR THIS CLAUSE" in llm.calls[0]["input"]
    assert "[source_id: ica_1872_section_27]" in llm.calls[0]["input"]
    # the clause still comes last, after the law
    assert llm.calls[0]["input"].rstrip().endswith("join a competitor.")
    assert "search_legal_reference" not in llm.calls[0]["system"]
    # both the hint's statute query and the clause's own words were searched
    assert queries[0] == "restraint of trade agreement void" and "NON-COMPETE" in queries[1]
    # sources are de-duplicated and the citation checks still work
    assert result["retrieved_source_ids"] == ["ica_1872_section_27", "ica_1872_section_74"]
    assert result["citation_valid"] is True and result["risk_level"] == "red"


def test_invented_citation_is_still_caught(monkeypatch):
    _fake_search(monkeypatch, [])
    llm = OneShotProvider({"plain_explanation": "x", "risk_level": "amber", "legal_assessment": "y",
                           "claims": [{"claim": "z", "supporting_source_ids": ["made_up_act_section_99"]}],
                           "llm_confidence": 0.9})
    result = agent.run_agent("Some clause.", "1", "TERMS", provider=llm, mode="prefetch")
    assert result["citation_valid"] is False and result["status"] == "human_review_required"


def test_source_cap(monkeypatch):
    many = [dict(SOURCES["restraint"], id=f"s{i}") for i in range(6)]
    monkeypatch.setattr(agent, "search_legal_reference_structured", lambda q, domain=None, top_k=3: many)
    context = {}
    agent._prefetch_law("clause", "T", {"statute_query": "q"}, context)
    assert len(context["retrieved_sources"]) == agent.PREFETCH_MAX_SOURCES


def test_other_states_rent_laws_are_skipped_when_state_is_known(monkeypatch):
    rows = [
        {"id": "tn_17", "law": "Tamil Nadu Tenancy Act", "section": "17", "title": "Entry", "jurisdiction": "Tamil Nadu", "text": "t", "distance": 0.3},
        {"id": "ka_27", "law": "Karnataka Rent Act, 1999", "section": "27", "title": "Eviction", "jurisdiction": "Karnataka", "text": "k", "distance": 0.4},
        {"id": "tpa_108", "law": "Transfer of Property Act, 1882", "section": "108", "title": "Rights", "jurisdiction": "India", "text": "c", "distance": 0.5},
        {"id": "mta_10", "law": "Model Tenancy Act, 2021", "section": "10", "title": "Entry", "jurisdiction": "Model Act (applies only where adopted by a state)", "text": "m", "distance": 0.6},
    ]
    monkeypatch.setattr(agent, "search_legal_reference_structured", lambda q, domain=None, top_k=3: rows)
    context = {"known_states": {"Karnataka"}}
    agent._prefetch_law("clause", "ENTRY", None, context)
    assert [r["id"] for r in context["retrieved_sources"]] == ["ka_27", "tpa_108", "mta_10"]

    context = {"known_states": set()}   # state unknown: nothing is filtered
    agent._prefetch_law("clause", "ENTRY", None, context)
    assert "tn_17" in [r["id"] for r in context["retrieved_sources"]]
