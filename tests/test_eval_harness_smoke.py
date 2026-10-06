"""
Phase 12/13/16 harness test: runs eval/run_evaluation.py's full
pipeline (gold data -> agent -> validators -> confidence engine ->
metrics) against the real gold_clauses.json, using an oracle provider
that already knows the expected answer.

This does NOT measure real model accuracy -- an oracle scores near-
perfect by construction, that's the point. What it proves is that the
plumbing works: gold data loads, run_agent processes every clause
without crashing, citation/grounding validation runs, the confidence
engine produces sane numbers, and eval/metrics.py's functions compute
without errors against real (if synthetic) predictions. This is the
mechanical proof called for when live model access isn't available;
real accuracy numbers still require Sprint/Phase 16 with a live model.
"""

from eval.run_evaluation import run
from tests.fakes.oracle_provider import OracleProvider, fake_search_matching_gold_item


def test_eval_harness_runs_against_real_gold_data_end_to_end(monkeypatch):
    current = {"item": None}

    def get_current():
        return current["item"]

    monkeypatch.setattr(
        "backend.agent.tools.search_legal_reference_structured",
        fake_search_matching_gold_item(get_current),
    )
    monkeypatch.setattr(
        "backend.validation.claim_validator._call_verifier",
        lambda prompt_claims: {c["claim_index"]: "SUPPORTED" for c in prompt_claims},
    )

    from eval import run_evaluation

    original_load_gold = run_evaluation.load_gold
    gold_items = original_load_gold()
    assert len(gold_items) >= 10, "gold dataset should have a real, non-trivial number of clauses"

    # Wrap run_agent-per-item so `current["item"]` tracks which gold
    # item is active -- the oracle provider and fake search both read
    # this to answer correctly for whichever clause is currently running.
    import backend.agent.agent as agent_module

    real_run_agent = agent_module.run_agent

    def tracking_run_agent(clause_text, clause_id=None, clause_title=None, provider=None):
        current["item"] = next(g for g in gold_items if g["clause_id"] == clause_id)
        return real_run_agent(clause_text, clause_id=clause_id, clause_title=clause_title, provider=provider)

    monkeypatch.setattr(run_evaluation, "run_agent", tracking_run_agent)

    metrics = run(provider=OracleProvider(get_current))

    assert metrics["num_gold"] == len(gold_items)
    assert metrics["num_predictions"] == len(gold_items), (
        f"Every gold clause should produce a prediction with no agent errors; skipped: {metrics['skipped_clause_ids']}"
    )

    # An oracle that cites exactly the expected sources should achieve
    # perfect grounding precision and zero fabricated citations -- if
    # this ever isn't 100%, something in the citation/grounding wiring
    # broke, not the "model".
    assert metrics["grounding_precision"] == 1.0
    assert metrics["fabricated_citation_rate"] == 0.0

    # The abstention cases (expected_status="insufficient_grounding")
    # should be correctly identified as such, since the oracle reports
    # zero claims for exactly those clauses.
    assert metrics["abstention_accuracy"] == 1.0
