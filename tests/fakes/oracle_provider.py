"""
An "oracle" fake LLMProvider that answers according to what the gold
dataset says it should find -- used only to prove the evaluation
harness (eval/run_evaluation.py) and its metrics actually compute
correctly, since this sandbox has no live Gemini access to produce
real predictions. This is NOT a substitute for real accuracy numbers;
an oracle that already knows the answer will always score near-perfect
by construction. Its only purpose is mechanical: confirm the plumbing
from gold data -> agent -> validators -> confidence engine -> metrics
doesn't silently break.
"""

import json

from backend.llm.base import LLMProvider, ToolCall, TurnResult


class OracleProvider(LLMProvider):
    """
    Must be paired with a monkeypatch of
    backend.agent.tools.search_legal_reference_structured that returns
    fabricated-but-plausible source records for whatever
    expected_sources the currently-active gold item specifies (see
    `current_gold_item` below) -- the oracle's tool call triggers that
    monkeypatch, then the oracle's final answer cites exactly those ids.
    """

    def __init__(self, get_current_gold_item):
        self._get_current_gold_item = get_current_gold_item
        self._awaiting_final = False

    def start_turn(self, system_prompt, user_input, tools):
        item = self._get_current_gold_item()

        if not item.get("expected_sources"):
            # Oracle knows (because the gold item says so) that no
            # relevant law exists -- answer immediately with no claims,
            # exactly like Issue 4's "no legal question" or a genuine
            # abstention case.
            self._awaiting_final = False
            return TurnResult(tool_calls=[], final_text=self._final_json(item), raw_state=None)

        self._awaiting_final = True
        return TurnResult(
            tool_calls=[ToolCall(id="oracle_call_1", name="search_legal_reference", arguments={"query": item["clause_text"][:60]})],
            final_text=None,
            raw_state=None,
        )

    def continue_turn(self, system_prompt, previous_state, tool_results, tools):
        item = self._get_current_gold_item()
        return TurnResult(tool_calls=[], final_text=self._final_json(item), raw_state=None)

    def simple_completion(self, system_prompt, user_input):
        return ""

    def _final_json(self, item: dict) -> str:
        expected_sources = item.get("expected_sources", [])
        claims = (
            [{"claim": f"This clause is addressed by {', '.join(expected_sources)}.", "supporting_source_ids": expected_sources}]
            if expected_sources
            else []
        )
        return json.dumps(
            {
                "plain_explanation": f"[oracle explanation for {item['clause_id']}]",
                "risk_level": item.get("risk_label", "amber"),
                "legal_assessment": "[oracle legal assessment]",
                "claims": claims,
                "llm_confidence": 0.9 if expected_sources else 0.3,
            }
        )


def fake_search_matching_gold_item(get_current_gold_item):
    """
    Returns a search_legal_reference_structured-compatible function that
    fabricates plausible-looking source records for whatever
    expected_sources the current gold item specifies. Text content is
    fabricated (not the real statute text) -- fine for this mechanical
    test, since the grounding verifier is also stubbed out in these
    tests (see the deterministic_grounding fixture pattern used in
    tests/test_agent_react_loop.py).
    """

    def _search(query, domain=None):
        item = get_current_gold_item()
        return [
            {
                "id": source_id,
                "law": source_id.rsplit("_section_", 1)[0].replace("_", " ").title(),
                "section": source_id.rsplit("_section_", 1)[-1],
                "title": "",
                "domain": "general",
                "topics": [],
                "text": f"[fabricated statute text standing in for {source_id}]",
                "distance": 0.1,
            }
            for source_id in item.get("expected_sources", [])
        ]

    return _search
