"""Groq (OpenAI-compatible) provider against a simulated API -- no key or network needed."""

import json

import httpx
import pytest

from backend.agent.tools import TOOLS
from backend.llm import openai_compat
from backend.llm.base import LLMUnavailableError
from backend.llm.openai_compat import OpenAICompatibleProvider


@pytest.fixture(autouse=True)
def fresh_model_bench():
    openai_compat._benched_until.clear()
    yield
    openai_compat._benched_until.clear()


def _provider(handler, fallbacks=None):
    p = OpenAICompatibleProvider("https://api.test/v1", "key", "openai/gpt-oss-120b", name="Groq",
                                 fallback_models=fallbacks)
    p._client = httpx.Client(base_url="https://api.test/v1", transport=httpx.MockTransport(handler))
    return p


def _message(**msg):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", **msg}}]})


def test_tool_call_round_trip():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return _message(content=None, tool_calls=[{"id": "call_1", "type": "function", "function": {
                "name": "search_legal_reference", "arguments": '{"query": "restraint of trade"}'}}])
        return _message(content='{"risk_level": "red"}')

    p = _provider(handler)
    turn = p.start_turn("sys", "clause", TOOLS)
    assert turn.tool_calls[0].arguments == {"query": "restraint of trade"}
    assert sent[0]["tools"][0]["function"]["name"] == "search_legal_reference"
    assert sent[0]["reasoning_effort"] == "medium"

    final = p.continue_turn("sys", turn.raw_state, [{"name": "search_legal_reference", "call_id": "call_1",
                                                      "result": [{"type": "text", "text": "[source_id: s27] ..."}]}], tools=[])
    assert final.final_text == '{"risk_level": "red"}'
    tool_msg = sent[1]["messages"][-1]
    assert tool_msg == {"role": "tool", "tool_call_id": "call_1", "name": "search_legal_reference",
                        "content": "[source_id: s27] ..."}
    assert sent[1]["messages"][-2]["tool_calls"][0]["id"] == "call_1"
    assert "tools" not in sent[1]


def test_minute_rate_limit_is_waited_out(monkeypatch):
    waits = []
    monkeypatch.setattr(openai_compat.time, "sleep", waits.append)
    calls = iter([httpx.Response(429, headers={"retry-after": "7"}), _message(content="OK")])
    assert _provider(lambda r: next(calls)).simple_completion("s", "u") == "OK"
    assert waits == [7.5]


def _tpd(retry_after="965"):
    return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": {"message":
        "Rate limit reached for model on tokens per day (TPD): Limit 200000, Used 199982, Requested 2251."}})


def _tpm(retry_after="20"):
    return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": {"message":
        "Rate limit reached for model on tokens per minute (TPM): Limit 8000, Used 6948, Requested 3773."}})


def test_daily_cap_reports_quota_without_naming_the_vendor():
    with pytest.raises(LLMUnavailableError) as exc:
        _provider(lambda r: _tpd()).simple_completion("s", "u")
    assert exc.value.reason == "quota" and "free capacity" in str(exc.value)
    assert "Groq" not in str(exc.value)


def test_daily_cap_switches_to_the_fallback_model():
    models = []

    def handler(request):
        model = json.loads(request.content)["model"]
        models.append(model)
        return _tpd() if model == "openai/gpt-oss-120b" else _message(content="OK")

    p = _provider(handler, fallbacks=["openai/gpt-oss-20b"])
    assert p.simple_completion("s", "u") == "OK"
    assert p.simple_completion("s", "u") == "OK"
    # the exhausted model is benched: the second call goes straight to the fallback
    assert models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"]


def test_all_models_exhausted_reports_quota():
    with pytest.raises(LLMUnavailableError) as exc:
        _provider(lambda r: _tpd(), fallbacks=["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]).simple_completion("s", "u")
    assert exc.value.reason == "quota"


def test_minute_limit_with_long_wait_is_waited_not_benched(monkeypatch):
    """A TPM message is a per-minute limit even if retry-after looks long."""
    waits = []
    monkeypatch.setattr(openai_compat.time, "sleep", waits.append)
    calls = iter([_tpm("70"), _message(content="OK")])
    assert _provider(lambda r: next(calls), fallbacks=["openai/gpt-oss-20b"]).simple_completion("s", "u") == "OK"
    assert waits == [70.5] and not openai_compat._benched_until


def test_reasoning_effort_only_sent_to_gpt_oss():
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return _tpd() if body["model"] == "openai/gpt-oss-120b" else _message(content="OK")

    _provider(handler, fallbacks=["qwen/qwen3.8-27b"]).simple_completion("s", "u")
    assert sent[0]["reasoning_effort"] == "medium" and "reasoning_effort" not in sent[1]


def test_bad_key_reports_auth():
    with pytest.raises(LLMUnavailableError) as exc:
        _provider(lambda r: httpx.Response(401, json={"error": "invalid key"})).simple_completion("s", "u")
    assert exc.value.reason == "auth"


def test_missing_key_is_clear():
    with pytest.raises(LLMUnavailableError) as exc:
        OpenAICompatibleProvider("https://api.test/v1", "", "m", name="Groq")
    assert "GROQ_API_KEY" in str(exc.value)


def test_fake_json_tool_call_is_recovered_as_the_answer():
    """Seen live: gpt-oss 'called' a tool named json with its final answer."""
    answer = {"plain_explanation": "You pay Rs 25,000 by the 5th.", "risk_level": "green",
              "legal_assessment": "Standard.", "claims": [], "llm_confidence": 0.9}
    err = {"error": {"code": "tool_use_failed", "message": "attempted to call tool 'json' which was not in request.tools",
                     "failed_generation": json.dumps({"name": "json", "arguments": answer})}}
    turn = _provider(lambda r: httpx.Response(400, json=err)).start_turn("s", "u", TOOLS)
    assert turn.tool_calls == [] and json.loads(turn.final_text) == answer


def test_unrecoverable_tool_failure_retries_without_tools():
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if "tools" in body:
            return httpx.Response(400, json={"error": {"code": "tool_use_failed", "message": "bad", "failed_generation": "garbage"}})
        return _message(content='{"plain_explanation": "ok"}')

    turn = _provider(handler).start_turn("s", "u", TOOLS)
    assert turn.final_text == '{"plain_explanation": "ok"}'
    assert "tools" in sent[0] and "tools" not in sent[-1]
