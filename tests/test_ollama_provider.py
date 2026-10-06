"""
OllamaProvider wire format and failure handling, against a simulated
Ollama HTTP server (httpx.MockTransport) -- no model download needed.
"""

import json

import httpx
import pytest

from backend.agent.tools import TOOLS
from backend.llm.base import LLMUnavailableError
from backend.llm.ollama import OllamaProvider


def _provider(handler) -> OllamaProvider:
    p = OllamaProvider(model="qwen2.5:3b", host="http://ollama.test")
    p._client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return p


def test_tool_call_round_trip():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "search_legal_reference", "arguments": {"query": "restraint of trade"}}}]}})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"risk_level": "red"}'}})

    p = _provider(handler)
    turn = p.start_turn("sys", "clause", TOOLS)

    assert turn.tool_calls[0].name == "search_legal_reference"
    assert turn.tool_calls[0].arguments == {"query": "restraint of trade"}
    # our tool schema is converted to Ollama's function format
    assert seen[0]["tools"][0]["function"]["name"] == "search_legal_reference"

    final = p.continue_turn("sys", turn.raw_state, [{
        "type": "function_result", "name": "search_legal_reference", "call_id": turn.tool_calls[0].id,
        "result": [{"type": "text", "text": "[source_id: s27] ..."}],
    }], tools=[])

    assert final.final_text == '{"risk_level": "red"}'
    sent = seen[1]
    assert "tools" not in sent  # cut-off turn: no tools offered
    assert [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "tool"]
    assert sent["messages"][-1]["content"] == "[source_id: s27] ..."


def test_server_down_is_llm_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMUnavailableError) as exc:
        _provider(handler).simple_completion("s", "u")
    assert exc.value.reason == "network" and "ollama serve" in str(exc.value)


def test_missing_model_is_llm_unavailable():
    with pytest.raises(LLMUnavailableError) as exc:
        _provider(lambda r: httpx.Response(404, json={"error": "model not found"})).simple_completion("s", "u")
    assert exc.value.reason == "model" and "ollama pull" in str(exc.value)
