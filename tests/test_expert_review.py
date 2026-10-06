"""
Expert review -- the human in the loop (expert_review/, api/routes_expert.py).
Uses the local JSON store in a temp folder; no network.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from backend.expert_review import service
from backend.main import app
from backend.services import jobs

KEY = "k" * 24
DOC_ID = "doc123"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "EXPERT_REVIEW_STORE", "local")
    monkeypatch.setattr(service, "EXPERT_REVIEW_DIR", str(tmp_path))
    monkeypatch.setattr(service, "REVIEWER_KEYS", f"Adv. Test Reviewer={KEY}")
    service.reset_for_tests()
    clauses = [
        {"clause_row_id": "c1", "clause_id": "4", "clause_title": "SECURITY DEPOSIT",
         "clause_text": "Deposit of ten months. Call 9876543210.", "plain_explanation": "You pay 10 months.",
         "risk_level": "red", "legal_assessment": "Unclear.", "recommended_action": "Ask to reduce.",
         "decision": "expert", "confidence": 0.34, "status": "human_review_required",
         "review_flags": ["unbacked_legal_reference"], "claims": [], "cited_sources": []},
        {"clause_row_id": "c2", "clause_id": "3", "clause_title": "RENT", "clause_text": "Rent Rs 28,000.",
         "plain_explanation": "You pay rent.", "risk_level": "green", "decision": "no_lawyer"},
    ]
    with jobs._lock:
        jobs._jobs["job1"] = {"job_id": "job1", "status": "done", "created_at": "2026-01-01",
                              "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              "result": {"document_id": DOC_ID, "document_type": "rental",
                                         "jurisdiction_states": ["Karnataka"], "clauses": clauses}}
    yield TestClient(app)
    with jobs._lock:
        jobs._jobs.pop("job1", None)
    service.reset_for_tests()


def _send(api, consent=True, ids=("c1",)):
    return api.post("/expert-review", json={"document_id": DOC_ID, "clause_row_ids": list(ids), "consent": consent})


def test_config_reports_expert_review(api):
    cfg = api.get("/config").json()
    assert cfg["expert_review_enabled"] is True and cfg["free_legal_aid"] == "15100"


def test_nothing_is_sent_without_consent(api, tmp_path):
    assert _send(api, consent=False).status_code == 400
    assert list(tmp_path.glob("*.json")) == []


def test_only_chosen_clauses_are_sent_redacted(api):
    res = _send(api)
    assert res.status_code == 201
    ticket = res.json()
    assert len(ticket["id"]) >= 24 and ticket["status"] == "waiting"
    assert [c["clause_row_id"] for c in ticket["clauses"]] == ["c1"]
    assert "9876543210" not in ticket["clauses"][0]["clause_text"]
    assert ticket["jurisdiction_states"] == ["Karnataka"]
    # sending again for the same analysis returns the same ticket
    assert _send(api).json()["id"] == ticket["id"]


def test_reviewer_needs_a_valid_key(api):
    _send(api)
    assert api.get("/expert-review/reviewer/queue").status_code == 401
    assert api.get("/expert-review/reviewer/queue", headers={"X-Reviewer-Key": "wrong" * 5}).status_code == 401
    queue = api.get("/expert-review/reviewer/queue", headers={"X-Reviewer-Key": KEY}).json()
    assert queue["reviewer"] == "Adv. Test Reviewer" and queue["count"] == 1


def test_review_reaches_the_person(api):
    ticket_id = _send(api).json()["id"]
    body = {"decision": "lawyer", "risk_level": "red", "note": "Karnataka practice is 2 months.",
            "consequence": "If you don't fix it, You could lose most of your Rs 2,80,000 deposit."}
    assert api.post(f"/expert-review/{ticket_id}/clauses/c1", json=body).status_code == 401
    res = api.post(f"/expert-review/{ticket_id}/clauses/c1", json=body, headers={"X-Reviewer-Key": KEY})
    assert res.status_code == 200
    seen = api.get(f"/expert-review/{ticket_id}").json()
    assert seen["status"] == "reviewed"
    review = seen["clauses"][0]["review"]
    assert review["decision"] == "lawyer" and review["reviewer"] == "Adv. Test Reviewer"
    assert review["consequence"] == "you could lose most of your Rs 2,80,000 deposit"
    assert api.get("/expert-review/reviewer/queue", headers={"X-Reviewer-Key": KEY}).json()["count"] == 0


def test_review_needs_a_consequence_and_a_valid_decision(api):
    ticket_id = _send(api).json()["id"]
    h = {"X-Reviewer-Key": KEY}
    url = f"/expert-review/{ticket_id}/clauses/c1"
    assert api.post(url, json={"decision": "lawyer", "risk_level": "red", "note": "see a lawyer"}, headers=h).status_code == 400
    assert api.post(url, json={"decision": "no_lawyer", "risk_level": "green", "note": " "}, headers=h).status_code == 400
    assert api.post(f"/expert-review/{ticket_id}/clauses/c1", json={"decision": "maybe", "risk_level": "red", "note": "x"}, headers=h).status_code == 400


def test_person_can_erase_it(api, tmp_path):
    ticket_id = _send(api).json()["id"]
    assert api.delete(f"/expert-review/{ticket_id}").json() == {"deleted": True}
    assert api.get(f"/expert-review/{ticket_id}").status_code == 404
    assert list(tmp_path.glob("*.json")) == []


def test_old_tickets_are_deleted(api, monkeypatch):
    ticket_id = _send(api).json()["id"]
    store = service.get_store()
    ticket = store.get(ticket_id)
    ticket["created_at"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)).isoformat()
    store.put(ticket)
    assert service.prune() == 1
    assert api.get(f"/expert-review/{ticket_id}").status_code == 404


def test_reviewed_tickets_are_deleted_after_keep_days(api):
    ticket_id = _send(api).json()["id"]
    api.post(f"/expert-review/{ticket_id}/clauses/c1", json={"decision": "negotiate", "risk_level": "amber", "consequence": "rent can rise every year"},
             headers={"X-Reviewer-Key": KEY})
    store = service.get_store()
    ticket = store.get(ticket_id)
    ticket["reviewed_at"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=8)).isoformat()
    store.put(ticket)
    assert service.prune() == 1


def test_disabled_without_reviewers(api, monkeypatch):
    monkeypatch.setattr(service, "REVIEWER_KEYS", "")
    assert api.get("/config").json()["expert_review_enabled"] is False
    assert _send(api).status_code == 503


def test_expired_analysis_cannot_be_sent(api):
    res = api.post("/expert-review", json={"document_id": "gone", "clause_row_ids": ["c1"], "consent": True})
    assert res.status_code == 404


# ── managing reviewers from the site (owner only) ──

def test_owner_invites_a_reviewer_who_can_then_review(api, tmp_path):
    owner = {"X-Reviewer-Key": KEY}
    assert api.get("/expert-review/reviewer/me", headers=owner).json() == {"name": "Adv. Test Reviewer", "role": "owner"}
    res = api.post("/expert-review/reviewers", json={"name": "  Priya   Sharma "}, headers=owner)
    assert res.status_code == 201
    invite = res.json()
    assert invite["name"] == "Priya Sharma" and len(invite["key"]) >= 24
    # only a hash is stored
    stored = (tmp_path / "meta" / "reviewers.json").read_text()
    assert invite["key"] not in stored and "key_hash" in stored

    guest = {"X-Reviewer-Key": invite["key"]}
    assert api.get("/expert-review/reviewer/me", headers=guest).json() == {"name": "Priya Sharma", "role": "reviewer"}
    ticket_id = _send(api).json()["id"]
    body = {"decision": "lawyer", "risk_level": "red", "consequence": "you could lose your deposit"}
    assert api.post(f"/expert-review/{ticket_id}/clauses/c1", json=body, headers=guest).status_code == 200
    assert api.get(f"/expert-review/{ticket_id}").json()["clauses"][0]["review"]["reviewer"] == "Priya Sharma"


def test_reviewers_cannot_manage_reviewers(api):
    invite = api.post("/expert-review/reviewers", json={"name": "Priya"}, headers={"X-Reviewer-Key": KEY}).json()
    guest = {"X-Reviewer-Key": invite["key"]}
    assert api.get("/expert-review/reviewers", headers=guest).status_code == 403
    assert api.post("/expert-review/reviewers", json={"name": "Mallory"}, headers=guest).status_code == 403
    assert api.get("/expert-review/reviewers").status_code == 401


def test_removing_a_reviewer_revokes_at_once(api):
    owner = {"X-Reviewer-Key": KEY}
    invite = api.post("/expert-review/reviewers", json={"name": "Priya"}, headers=owner).json()
    listed = api.get("/expert-review/reviewers", headers=owner).json()["reviewers"]
    assert [r["name"] for r in listed] == ["Adv. Test Reviewer", "Priya"]
    assert all("key" not in r and "key_hash" not in r for r in listed)
    assert api.delete(f"/expert-review/reviewers/{invite['id']}", headers=owner).json() == {"removed": True}
    assert api.get("/expert-review/reviewer/queue", headers={"X-Reviewer-Key": invite["key"]}).status_code == 401


def test_duplicate_and_empty_names_are_refused(api):
    owner = {"X-Reviewer-Key": KEY}
    assert api.post("/expert-review/reviewers", json={"name": "Priya"}, headers=owner).status_code == 201
    assert api.post("/expert-review/reviewers", json={"name": "priya"}, headers=owner).status_code == 400
    assert api.post("/expert-review/reviewers", json={"name": "   "}, headers=owner).status_code == 400


# ── contact / grievances (api/routes_contact.py) ──

def test_contact_message_reaches_only_the_owner(api):
    assert api.post("/contact", json={"topic": "grievance", "message": "Please delete my data.", "reply_to": "me@example.com"}).status_code == 201
    assert api.post("/contact", json={"topic": "spam", "message": "hello there"}).status_code == 400
    assert api.post("/contact", json={"topic": "question", "message": "hi", "website": "bot"}).json() == {"received": True}
    owner = {"X-Reviewer-Key": KEY}
    msgs = api.get("/contact/messages", headers=owner).json()["messages"]
    assert [(m["topic"], m["reply_to"]) for m in msgs] == [("grievance", "me@example.com")]   # the bot's was dropped
    guest_key = api.post("/expert-review/reviewers", json={"name": "Priya"}, headers=owner).json()["key"]
    assert api.get("/contact/messages", headers={"X-Reviewer-Key": guest_key}).status_code == 403
    assert api.get("/contact/messages").status_code == 401
    assert api.delete(f"/contact/messages/{msgs[0]['id']}", headers=owner).json() == {"deleted": True}
    assert api.get("/contact/messages", headers=owner).json()["messages"] == []
