"""
Phase 2 / TODAY-TODO items 5-10: exercise the actual ReAct loop
mechanics -- tool calling, multi-turn evidence gathering, and the
3-search cutoff -- using a scripted fake provider (tests/fakes/) since
this sandbox has no network access to a live Gemini call. Also
monkeypatches the retrieval layer so results are deterministic and
these tests don't depend on embedding quality or a pre-built index.

Covers the three scenarios explicitly called out in the roadmap:
  1. One search is enough -> FINAL
  2. Search #1 weak, search #2 better -> FINAL
  3. Search #1, #2, #3 still insufficient -> cutoff -> ABSTAIN

Also verifies the agent never guesses with zero evidence, and that a
model which ignores the cutoff instruction and keeps requesting tools
anyway still gets forced to a final answer rather than the loop
silently giving up (this second part failed before a fix made during
this session -- see the dedicated test below).
"""

import json

import pytest

from backend.agent.agent import run_agent
from backend.agent.tools import MAX_TOOL_CALLS
from backend.llm.base import ToolCall, TurnResult
from tests.fakes.scripted_provider import ScriptedProvider


def _tool_call(call_id: str, query: str) -> ToolCall:
    return ToolCall(id=call_id, name="search_legal_reference", arguments={"query": query})


def _final_json(**overrides) -> str:
    payload = {
        "plain_explanation": "You may not be able to join a competing company for 12 months after leaving.",
        "risk_level": "amber",
        "legal_assessment": "This restricts post-employment activity and may conflict with Indian contract law.",
        "claims": [{"claim": "The clause restrains a lawful trade or business.", "supporting_source_ids": ["src_27"]}],
        "llm_confidence": 0.8,
    }
    payload.update(overrides)
    return json.dumps(payload)


ONE_SOURCE = [
    {
        "id": "src_27",
        "law": "Indian Contract Act, 1872",
        "section": "27",
        "title": "Restraint of trade",
        "domain": "employment",
        "topics": ["employment"],
        "text": "Every agreement restraining a lawful profession, trade or business is void.",
        "distance": 0.1,
    }
]


@pytest.fixture(autouse=True)
def deterministic_grounding(monkeypatch):
    """
    The grounding verifier (claim_validator._call_verifier) makes its
    own separate LLM call, which would try to hit the real network in
    these tests. Force a fixed verdict so these tests are about the
    ReAct loop's mechanics, not the verifier's LLM behavior (that's
    covered separately in tests/test_claim_validator.py).
    """
    monkeypatch.setattr(
        "backend.validation.claim_validator._call_verifier",
        lambda prompt_claims: {c["claim_index"]: "SUPPORTED" for c in prompt_claims},
    )


def test_single_search_is_enough(monkeypatch):
    monkeypatch.setattr(
        "backend.agent.tools.search_legal_reference_structured",
        lambda query, domain=None: ONE_SOURCE,
    )

    provider = ScriptedProvider(
        [
            TurnResult(tool_calls=[_tool_call("c1", "non-compete restraint of trade")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[], final_text=_final_json(), raw_state=None),
        ]
    )

    result = run_agent("The employee shall not work for a competitor for 12 months.", clause_id="4", provider=provider)

    assert "error" not in result
    assert provider.calls_made == 2  # exactly one search round-trip
    assert result["retrieved_source_ids"] == ["src_27"]
    assert result["citation_valid"] is True
    assert result["status"] in {"grounded", "partially_grounded"}
    assert 0.0 <= result["confidence"] <= 1.0


def test_weak_then_better_evidence(monkeypatch):
    """
    Search #1 returns something only tangentially related; the model
    (per the script) decides that's not enough and searches again with
    a refined query, and the second search returns the real answer.
    """
    call_log = []

    def fake_search(query, domain=None):
        call_log.append(query)
        if len(call_log) == 1:
            return [{**ONE_SOURCE[0], "id": "src_weak", "distance": 0.9, "title": "Loosely related"}]
        return ONE_SOURCE

    monkeypatch.setattr("backend.agent.tools.search_legal_reference_structured", fake_search)

    provider = ScriptedProvider(
        [
            TurnResult(tool_calls=[_tool_call("c1", "non-compete")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[_tool_call("c2", "post-employment restraint of trade Indian Contract Act")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[], final_text=_final_json(), raw_state=None),
        ]
    )

    result = run_agent("The employee shall not work for a competitor for 12 months.", clause_id="4", provider=provider)

    assert "error" not in result
    assert len(call_log) == 2  # both searches actually happened
    # Both sources seen across the two searches should be tracked, even
    # though only src_27 ends up cited in the final claim.
    assert set(result["retrieved_source_ids"]) == {"src_weak", "src_27"}
    assert result["citation_valid"] is True


def test_three_searches_still_insufficient_forces_final_and_abstains(monkeypatch):
    """
    Roadmap scenario: search #1, #2, #3 all insufficient -> the model
    (well-behaved, respecting the cutoff instruction) gives up and
    reports low confidence with no claims -> system correctly abstains
    rather than letting the model guess.
    """
    monkeypatch.setattr(
        "backend.agent.tools.search_legal_reference_structured",
        lambda query, domain=None: [],  # nothing relevant, every time
    )

    provider = ScriptedProvider(
        [
            TurnResult(tool_calls=[_tool_call("c1", "q1")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[_tool_call("c2", "q2")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[_tool_call("c3", "q3")], final_text=None, raw_state=None),
            TurnResult(
                tool_calls=[],
                final_text=_final_json(
                    risk_level="amber",
                    legal_assessment="No relevant statutory provision was found after three searches.",
                    claims=[],
                    llm_confidence=0.2,
                ),
                raw_state=None,
            ),
        ]
    )

    result = run_agent("Some obscure clause with no clear statutory analogue.", clause_id="9", provider=provider)

    assert "error" not in result
    assert result["retrieved_source_ids"] == []
    assert result["status"] in {"insufficient_grounding", "human_review_required"}
    assert result["verification_status"] == "pending"


def test_model_ignoring_cutoff_still_gets_forced_to_a_final_answer(monkeypatch):
    """
    Adversarial case: the model requests a 4th search even after being
    told the maximum has been reached. The loop must still force a final
    answer from the tools=[] turn rather than silently exhausting its
    step budget and returning an unhelpful {"error": ...} with no
    result at all -- that would be worse than abstaining, because the
    caller (routes_documents.py) has no clause-level detail to show.
    """
    monkeypatch.setattr(
        "backend.agent.tools.search_legal_reference_structured",
        lambda query, domain=None: [],
    )

    provider = ScriptedProvider(
        [
            TurnResult(tool_calls=[_tool_call("c1", "q1")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[_tool_call("c2", "q2")], final_text=None, raw_state=None),
            TurnResult(tool_calls=[_tool_call("c3", "q3")], final_text=None, raw_state=None),
            # Model stubbornly asks for a 4th search despite the cutoff message:
            TurnResult(tool_calls=[_tool_call("c4", "q4")], final_text=None, raw_state=None),
            # Only after being cut off with tools=[] does it finally comply:
            TurnResult(
                tool_calls=[],
                final_text=_final_json(claims=[], llm_confidence=0.1),
                raw_state=None,
            ),
        ]
    )

    result = run_agent("Some obscure clause.", clause_id="10", provider=provider)

    assert "error" not in result, f"Loop gave up instead of forcing a final answer: {result}"
    # The cutoff continue_turn call must have been made with tools=[] --
    # otherwise the model could just keep requesting searches forever.
    cutoff_calls = [c for c in provider.continue_turn_calls if c["tools"] == []]
    assert len(cutoff_calls) >= 1


def test_never_more_than_max_tool_calls_searches_are_executed(monkeypatch):
    search_calls = []
    monkeypatch.setattr(
        "backend.agent.tools.search_legal_reference_structured",
        lambda query, domain=None: search_calls.append(query) or [],
    )

    # Script a model that would keep searching forever if allowed to.
    turns = [TurnResult(tool_calls=[_tool_call(f"c{i}", f"q{i}")], final_text=None, raw_state=None) for i in range(10)]
    turns.append(TurnResult(tool_calls=[], final_text=_final_json(claims=[]), raw_state=None))
    provider = ScriptedProvider(turns)

    run_agent("clause", clause_id="1", provider=provider)

    assert len(search_calls) == MAX_TOOL_CALLS
