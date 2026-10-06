"""
DPDP privacy mode (the default): contracts are never written to the
database, need consent, have identifiers stripped before any AI call,
can be deleted at once, and expire on their own.
"""

import time

import pytest

from backend.database.models import Clause, Document, VerificationRecord
from backend.services import jobs
from tests.test_end_to_end import _contract_docx, client  # noqa: F401  (fixture)


def _upload_and_wait(client, path, consent="true"):
    with open(path, "rb") as f:
        res = client.post("/analyze-document/start", files={"file": (path.name, f)},
                          data={"document_type": "employment", "consent": consent})
    if res.status_code != 202:
        return res, None
    job_id = res.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return res, job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _db_rows(client):
    from backend.database import db as db_module
    session = db_module.SessionLocal()
    try:
        return session.query(Document).count(), session.query(Clause).count(), session.query(VerificationRecord).count()
    finally:
        session.close()


def test_nothing_is_written_to_the_database(client, tmp_path):
    _, job = _upload_and_wait(client, _contract_docx(tmp_path / "offer.docx"))
    assert job["status"] == "done" and job["result"]["stored"] is False
    assert len(job["result"]["clauses"]) == 3
    assert _db_rows(client) == (0, 0, 0)


def test_result_is_readable_from_memory_then_deletable(client, tmp_path):
    _, job = _upload_and_wait(client, _contract_docx(tmp_path / "offer.docx"))
    doc_id = job["result"]["document_id"]

    assert client.get(f"/document/{doc_id}").status_code == 200
    assert client.delete(f"/document/{doc_id}").json() == {"deleted": True}
    assert client.get(f"/document/{doc_id}").status_code == 404
    assert client.get(f"/jobs/{job['job_id']}").status_code == 404


def test_results_expire(client, tmp_path, monkeypatch):
    _, job = _upload_and_wait(client, _contract_docx(tmp_path / "offer.docx"))
    monkeypatch.setattr(jobs, "RESULT_TTL_MINUTES", 0)
    assert client.get(f"/document/{job['result']['document_id']}").status_code == 404


def test_consent_is_required(client, tmp_path):
    res, _ = _upload_and_wait(client, _contract_docx(tmp_path / "offer.docx"), consent=None)
    assert res.status_code == 400 and "Consent" in res.json()["detail"]


def test_identifiers_never_reach_the_ai(client, tmp_path):
    from docx import Document as Docx
    path = tmp_path / "pii.docx"
    d = Docx()
    for line in ["1. PARTIES", "Employee Rahul, PAN ABCDE1234F, phone 98765 43210, email r@x.com.",
                 "2. NON-COMPETE RESTRICTION", "For 2 years the Employee shall not join any competing business."]:
        d.add_paragraph(line)
    d.save(path)

    _, job = _upload_and_wait(client, path)
    sent_to_ai = "\n".join(client.model.user_inputs)
    for leaked in ["ABCDE1234F", "98765 43210", "r@x.com"]:
        assert leaked not in sent_to_ai
        assert all(leaked not in c["clause_text"] for c in job["result"]["clauses"])
    assert job["result"]["redactions"] == {"[EMAIL]": 1, "[PAN]": 1, "[PHONE]": 1}


def test_reviewer_desk_is_off_and_config_says_so(client):
    assert client.get("/verification/pending").json()["review_enabled"] is False
    cfg = client.get("/config").json()
    assert cfg["store_analyses"] is False and cfg["retention_minutes"] == 60
