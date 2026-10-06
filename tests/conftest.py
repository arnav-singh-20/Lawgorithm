"""
Shared fixtures.

run_agent() looks up the clause type in the on-disk precedent index
before every ReAct loop. Tests shouldn't depend on whether that index
happens to be built on this machine (or on embedding speed), so it's
stubbed to "no index" by default. Tests that exercise the hint path
monkeypatch backend.agent.agent.classify_clause_type themselves.
"""

import pytest


@pytest.fixture(autouse=True)
def no_clause_index(monkeypatch):
    monkeypatch.setattr("backend.agent.agent.classify_clause_type", lambda clause_text: None)


@pytest.fixture(autouse=True)
def llm_translation_engine(monkeypatch):
    """Tests drive translation through a fake LLM provider; never load the real NLLB model."""
    monkeypatch.setattr("backend.translation.translator.ENGINE", "llm")


@pytest.fixture(autouse=True)
def react_agent_mode(monkeypatch):
    """
    Most agent tests drive the multi-turn ReAct loop with scripted tool
    calls, so they run in "react" mode. Prefetch mode (the production
    default) has its own tests in test_agent_prefetch.py.
    """
    monkeypatch.setattr("backend.agent.agent.AGENT_MODE", "react")
