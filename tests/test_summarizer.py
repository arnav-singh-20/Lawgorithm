"""Whole-document summary step: parsing, graceful degradation, context formatting."""

import json

import pytest

from backend.agent.summarizer import summarize_document, summary_as_context
from backend.llm.base import LLMUnavailableError


class _Fake:
    def __init__(self, reply):
        self.reply = reply

    def simple_completion(self, system_prompt, user_input):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


GOOD = {
    "document_type": "rental", "title": "Lease", "parties": ["You (tenant)", "Landlord"],
    "location": "Pune", "key_terms": [{"term": "Lease term", "value": "11 months"}],
    "summary": "You rent a flat for 11 months.",
}


def test_parses_fenced_json():
    s = summarize_document("contract", _Fake("```json\n" + json.dumps(GOOD) + "\n```"))
    assert s["location"] == "Pune" and s["key_terms"][0]["value"] == "11 months"


def test_garbage_degrades_to_none():
    assert summarize_document("contract", _Fake("sorry, I can't")) is None
    assert summarize_document("contract", _Fake(json.dumps({"title": "no summary field"}))) is None


def test_outage_is_not_swallowed():
    with pytest.raises(LLMUnavailableError):
        summarize_document("contract", _Fake(LLMUnavailableError("down", "quota")))


def test_context_block():
    ctx = summary_as_context(GOOD)
    assert "Summary: You rent a flat for 11 months." in ctx and "- Lease term: 11 months" in ctx
    assert summary_as_context(None) == ""


def test_one_bad_key_term_does_not_discard_the_summary():
    """Seen live from qwen2.5:3b: a key term whose value was null."""
    reply = dict(GOOD, key_terms=[{"term": "Lock-in", "value": None}, {"term": "Rent", "value": "Rs 25,000"}],
                 parties="Landlord and Tenant", document_type="lease")
    s = summarize_document("contract", _Fake(json.dumps(reply)))
    assert s["key_terms"] == [{"term": "Rent", "value": "Rs 25,000"}]
    assert s["parties"] == ["Landlord and Tenant"] and s["document_type"] == "other"
