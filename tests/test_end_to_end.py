"""
Phase 19 -- the whole chain as ONE path, through the real HTTP API:

  upload .docx -> extract -> clean -> segment -> clause-type hint ->
  ReAct agent (search) -> citation check -> grounding check ->
  confidence engine -> Phase 9 flags -> DB -> review queue ->
  reviewer correction (Phase 11) -> translation + back-translation check

Only the parts that need a live LLM or a pre-built index are replaced:
  - the LLM provider (a rule-based fake that answers like a careful model)
  - the grounding verifier's LLM call (fixed SUPPORTED verdict)
  - statute search, served from the REAL seed statute JSON in
    data/statutes/ via the real chunker (so ids/text are the real ones)
  - the clause-type lookup (keyword fake instead of the 63k-clause index)
Everything else -- extraction, segmentation, validators, confidence,
routing, persistence, API serialization -- is the production code.
"""

import json

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from backend.database.db import get_db, init_db
from backend.llm.base import LLMProvider, ToolCall, TurnResult
from backend.main import app
from backend.rag.chunking import chunk_statute
from backend.rag.ingest_laws import load_statute_files

S27 = "indian_contract_act__1872_section_27"
S74 = "indian_contract_act__1872_section_74"


class CarefulFakeModel(LLMProvider):
    """Searches for legally loaded clauses, cites what it found, abstains from claims otherwise."""

    def __init__(self):
        self.user_inputs = []

    def start_turn(self, system_prompt, user_input, tools):
        self.user_inputs.append(user_input)
        self._clause = user_input.split("CLAUSE TO EXPLAIN", 1)[-1].lower()
        if "compet" in self._clause or "penalty" in self._clause:
            return TurnResult(
                tool_calls=[ToolCall(id="s1", name="search_legal_reference", arguments={"query": "restraint of trade" if "compet" in self._clause else "penalty for breach"})],
                final_text=None, raw_state=None,
            )
        return TurnResult(tool_calls=[], final_text=self._answer(), raw_state=None)

    def continue_turn(self, system_prompt, previous_state, tool_results, tools):
        return TurnResult(tool_calls=[], final_text=self._answer(), raw_state=None)

    def simple_completion(self, system_prompt, user_input):
        if "summarise them for someone with no legal training" in system_prompt:
            return json.dumps({
                "document_type": "employment",
                "title": "Employment Agreement",
                "parties": ["You (the employee)", "The company (employer)"],
                "location": "Bengaluru, Karnataka",
                "key_terms": [{"term": "Monthly salary", "value": "Rs 75,000"},
                              {"term": "Penalty for breach", "value": "Rs 5,00,000"}],
                "summary": "This is your job contract. You get Rs 75,000 a month.",
            })
        if "Translate the given text into English" in system_prompt:
            return self._last_english  # faithful back-translation
        self._last_english = user_input.split("Explanation to translate:\n", 1)[-1]
        return "आप दो साल तक किसी प्रतिस्पर्धी कंपनी में शामिल नहीं हो सकते।"

    def _answer(self):
        if "compet" in self._clause:
            payload = {
                "plain_explanation": "You can't join a competitor anywhere in India for 2 years after leaving.",
                "risk_level": "red",
                "legal_assessment": "A post-employment restraint of trade is void under Indian law.",
                "recommended_action": "Ask for this clause to be removed or limited to the period of employment.",
                "claims": [{"claim": "An agreement restraining a lawful profession is void.", "supporting_source_ids": [S27]}],
                "llm_confidence": 0.9,
            }
        elif "penalty" in self._clause:
            payload = {
                "plain_explanation": "You'd owe Rs 5 lakh for any minor breach.",
                "risk_level": "amber",
                "legal_assessment": "Only reasonable compensation up to the named sum is recoverable.",
                "recommended_action": "Ask for the penalty to be tied to actual loss.",
                "claims": [{"claim": "Recovery is capped at reasonable compensation.", "supporting_source_ids": [S74]}],
                "llm_confidence": 0.8,
            }
        else:
            payload = {
                "plain_explanation": "You will be paid Rs 75,000 every month.",
                "risk_level": "green",
                "legal_assessment": "No legal question arises from a salary statement.",
                "recommended_action": "Check the amount matches your offer letter.",
                "claims": [],
                "llm_confidence": 0.95,
            }
        return json.dumps(payload)


STORE_FLAGS = [
    "backend.services.analysis_pipeline.STORE_ANALYSES",
    "backend.services.jobs.STORE_ANALYSES",
    "backend.api.routes_analysis.STORE_ANALYSES",
    "backend.api.routes_verification.STORE_ANALYSES",
]


@pytest.fixture
def storage_mode(monkeypatch):
    """Opt-in research mode (STORE_ANALYSES=true): analyses are kept for human review."""
    for flag in STORE_FLAGS:
        monkeypatch.setattr(flag, True)


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    chunks = {c["id"]: c for s in load_statute_files() for c in chunk_statute(s["law"], s["sections"])}

    def seed_search(query, domain=None):
        wanted = [S27] if "restraint" in query else [S74]
        return [{**chunks[sid], "distance": 0.05} for sid in wanted]

    model = CarefulFakeModel()
    monkeypatch.setattr("backend.agent.agent._get_provider", lambda: model)
    monkeypatch.setattr("backend.translation.translator._get_provider", lambda: model)
    monkeypatch.setattr("backend.agent.tools.search_legal_reference_structured", seed_search)
    monkeypatch.setattr(
        "backend.validation.claim_validator._call_verifier",
        lambda prompt_claims: {c["claim_index"]: "SUPPORTED" for c in prompt_claims},
    )
    monkeypatch.setattr(
        "backend.agent.agent.classify_clause_type",
        lambda text: (
            {"clause_type": "non_compete", "label": "Non-compete", "confidence": 0.87,
             "statute_query": "restraint of trade", "risk_prone": True}
            if "compet" in text.lower() else None
        ),
    )
    monkeypatch.setattr("backend.database.db.SessionLocal", TestingSession)  # background jobs
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.model = model
    yield client
    app.dependency_overrides.clear()


def _contract_docx(path):
    doc = DocxDocument()
    for line in [
        "EMPLOYMENT AGREEMENT",
        "This agreement is made at Bengaluru, Karnataka.",
        "1. POSITION AND SALARY",
        "The Employee shall receive a monthly salary of Rs 75,000.",
        "2. NON-COMPETE RESTRICTION",
        "For 2 years after termination the Employee shall not join any competing business anywhere in India.",
        "3. PENALTY FOR BREACH",
        "For any minor breach the Employee shall pay a penalty of Rs 5,00,000.",
    ]:
        doc.add_paragraph(line)
    doc.save(path)
    return path


def test_full_pipeline_upload_to_correction_to_translation(client, tmp_path, storage_mode):
    path = _contract_docx(tmp_path / "offer.docx")

    # --- upload -> full analysis ---
    with open(path, "rb") as f:
        res = client.post("/analyze-document", files={"file": ("offer.docx", f)}, data={"document_type": "employment", "consent": "true"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["failed_clauses"] == []
    assert body["overall_risk"] == "red"
    assert body["jurisdiction_states"] == ["Karnataka"]

    # step 1: whole-document summary, returned and fed to every clause run
    assert body["document_summary"]["summary"].startswith("This is your job contract")
    assert all("Monthly salary: Rs 75,000" in u for u in client.model.user_inputs)

    by_title = {c["clause_title"]: c for c in body["clauses"]}
    non_compete = by_title["NON-COMPETE RESTRICTION"]
    salary = by_title["POSITION AND SALARY"]
    penalty = by_title["PENALTY FOR BREACH"]

    # trust layer on the risky clause: real citation, routed to a human because it's RED
    assert non_compete["citation_valid"] is True
    assert non_compete["risk_level"] == "red"
    assert non_compete["verification_status"] == "pending"
    assert non_compete["cited_sources"][0]["law"] == "Indian Contract Act, 1872"
    assert non_compete["cited_sources"][0]["section"] == "27"
    assert non_compete["clause_type"]["clause_type"] == "non_compete"
    assert non_compete["recommended_action"].startswith("Ask for this clause")
    assert "restrained" in non_compete["clause_text"] or "competing" in non_compete["clause_text"]

    # factual clause: no claims needed, auto-approved, still gets an action
    assert salary["status"] == "grounded" and salary["verification_status"] == "auto_approved"
    assert salary["recommended_action"]

    assert penalty["cited_sources"][0]["section"] == "74"

    # --- persisted and re-readable ---
    doc = client.get(f"/document/{body['document_id']}").json()
    assert doc["document_summary"] == body["document_summary"]
    assert {c["clause_title"] for c in doc["clauses"]} >= set(by_title)
    stored = next(c for c in doc["clauses"] if c["clause_title"] == "NON-COMPETE RESTRICTION")
    assert stored["recommended_action"] == non_compete["recommended_action"]
    assert stored["cited_sources"][0]["id"] == S27

    # --- review queue shows why ---
    pending = client.get("/verification/pending").json()
    item = next(i for i in pending["items"] if i["clause_title"] == "NON-COMPETE RESTRICTION")
    assert "RED" in item["flag_reason"]

    # --- reviewer corrects it -> correction dataset ---
    res = client.post(f"/verification/{item['clause_row_id']}", json={
        "action": "edit",
        "edited_explanation": "This non-compete is very likely unenforceable after you leave.",
        "edited_risk_level": "red",
        "reviewer_notes": "explanation should say it's likely void, not just restrictive",
    })
    assert res.status_code == 200, res.text
    assert res.json()["verification_status"] == "human_verified"

    corrections = client.get("/verification/corrections").json()
    assert corrections["count"] == 1
    correction = corrections["items"][0]
    assert correction["ai"]["explanation"] == non_compete["plain_explanation"]
    assert correction["human"]["explanation"].startswith("This non-compete")
    assert correction["ai_was_correct"] is False
    assert correction["document_type"] == "employment"

    # --- translation with back-translation check ---
    res = client.post("/translate", json={
        "text": non_compete["plain_explanation"], "target_language": "hindi", "validate_translation": True,
    })
    assert res.status_code == 200, res.text
    translated = res.json()
    assert translated["validated"] is True
    assert translated["similarity_score"] > 0.99


def test_sample_txt_upload_is_accepted(client, tmp_path):
    """The frontend's 'Load Sample' buttons upload .txt files."""
    path = tmp_path / "sample.txt"
    path.write_text("1. POSITION AND SALARY\nThe Employee shall receive a monthly salary of Rs 75,000.\n")
    with open(path, "rb") as f:
        res = client.post("/analyze-document", files={"file": ("sample.txt", f)}, data={"document_type": "employment", "consent": "true"})
    assert res.status_code == 200, res.text
    assert res.json()["clauses"][0]["risk_level"] == "green"


def test_llm_outage_returns_clear_503_and_stores_nothing(client, tmp_path, monkeypatch, storage_mode):
    from backend.llm.base import LLMUnavailableError

    def down(*args, **kwargs):
        raise LLMUnavailableError("The AI service's usage quota is exhausted (HTTP 429).", "quota")

    monkeypatch.setattr(client.model, "simple_completion", down)
    path = _contract_docx(tmp_path / "offer.docx")
    with open(path, "rb") as f:
        res = client.post("/analyze-document", files={"file": ("offer.docx", f)}, data={"document_type": "employment", "consent": "true"})

    assert res.status_code == 503
    assert "quota" in res.json()["detail"]
    assert client.get("/verification/pending").json()["count"] == 0


def test_unreadable_upload_gets_actionable_422(client, tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("   \n\n  ")
    with open(path, "rb") as f:
        res = client.post("/analyze-document", files={"file": ("blank.txt", f)}, data={"document_type": "rental", "consent": "true"})
    assert res.status_code == 422
    assert "photo" in res.json()["detail"]


def test_background_job_streams_progress_and_result(client, tmp_path, storage_mode):
    import time

    path = _contract_docx(tmp_path / "offer.docx")
    with open(path, "rb") as f:
        res = client.post("/analyze-document/start", files={"file": ("offer.docx", f)},
                          data={"document_type": "employment", "consent": "true"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    seen_stages = set()
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        seen_stages.add(job["stage"])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)

    assert job["status"] == "done", job["error"]
    assert job["total"] == 3 and job["done"] == 3      # salary, non-compete, penalty
    assert len(job["clauses"]) == 3                      # streamed one by one
    assert job["summary"]["summary"].startswith("This is your job contract")
    assert job["result"]["overall_risk"] == "red"
    assert client.get(f"/document/{job['result']['document_id']}").status_code == 200


def test_job_rejects_unsupported_file_up_front(client, tmp_path):
    path = tmp_path / "contract.xlsx"
    path.write_bytes(b"not a contract")
    with open(path, "rb") as f:
        res = client.post("/analyze-document/start", files={"file": ("contract.xlsx", f)},
                          data={"document_type": "rental", "consent": "true"})
    assert res.status_code == 415


def test_unknown_job_is_404(client):
    assert client.get("/jobs/nope").status_code == 404
