"""
Pay-per-use (payments/razorpay.py) against a fake Razorpay -- no network.
"""

import hashlib
import hmac
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.payments import razorpay

SECRET = "test_secret_123"
SAMPLE = (Path(__file__).resolve().parent.parent / "frontend" / "samples" / "rental.txt").read_bytes()


class FakeRazorpay:
    def __init__(self):
        self.orders, self.payments, self.refunds = {}, {}, []

    def pay(self, purpose="analysis", amount=1000, status="captured"):
        oid, pid = f"order_{len(self.orders)}", f"pay_{len(self.payments)}"
        self.orders[oid] = {"id": oid, "amount": amount, "notes": {"purpose": purpose}}
        self.payments[pid] = {"id": pid, "order_id": oid, "amount": amount, "status": status, "notes": {}}
        sig = hmac.new(SECRET.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
        return {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sig}

    def __call__(self, method, path, **kw):
        parts = path.strip("/").split("/")
        if method == "POST" and parts == ["orders"]:
            oid = f"order_{len(self.orders)}"
            self.orders[oid] = {"id": oid, **kw["json"]}
            return self.orders[oid]
        if parts[0] == "orders":
            return self.orders[parts[1]]
        if parts[-1] == "refund":
            self.refunds.append(parts[1])
            return {"id": "rfnd_1"}
        payment = self.payments[parts[1]]
        if method == "GET":
            return payment
        if method == "PATCH":
            payment["notes"] = kw["json"]["notes"]
            return payment
        if parts[-1] == "capture":
            payment["status"] = "captured"
            return payment
        if parts[-1] == "refund":
            self.refunds.append(parts[1])
            return {"id": "rfnd_1"}
        raise AssertionError(path)


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(razorpay, "RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setattr(razorpay, "RAZORPAY_KEY_SECRET", SECRET)
    monkeypatch.setattr(razorpay, "_api", fake)
    razorpay.reset_for_tests()
    yield fake
    razorpay.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


def test_config_shows_prices(rzp, client):
    cfg = client.get("/config").json()
    assert cfg["payments_enabled"] is True and cfg["price_analysis"] == 10 and cfg["price_expert"] == 0


def test_order_for_checkout(rzp, client):
    order = client.post("/payments/order", json={"purpose": "analysis"}).json()
    assert order["amount"] == 1000 and order["currency"] == "INR" and order["key_id"] == "rzp_test_abc"
    assert "secret" not in str(order).lower()
    assert client.post("/payments/order", json={"purpose": "expert"}).status_code == 400   # free for now


def test_free_when_keys_missing(client):
    assert razorpay.price("analysis") == 0
    assert client.get("/config").json()["payments_enabled"] is False


def _upload(client, content=b"1. RENT\nThe tenant pays Rs 20,000.", **pay):
    return client.post("/analyze-document/start", files={"file": ("lease.txt", content)},
                       data={"document_type": "rental", "consent": "true", **pay})


def test_upload_needs_payment(rzp, client):
    res = _upload(client)
    assert res.status_code == 402 and "₹10" in res.json()["detail"]


def test_forged_signature_is_refused(rzp, client):
    pay = rzp.pay()
    pay["razorpay_signature"] = "0" * 64
    assert _upload(client, **pay).status_code == 402


def test_paid_upload_is_accepted_once(rzp, client, monkeypatch):
    monkeypatch.setattr("backend.services.jobs._executor.submit", lambda *a, **k: None)   # don't run the AI
    pay = rzp.pay()
    assert _upload(client, **pay).status_code == 202
    assert rzp.payments[pay["razorpay_payment_id"]]["notes"][razorpay.USED_NOTE].startswith("doc:")
    assert _upload(client, **pay).status_code == 402                       # same payment again
    razorpay.reset_for_tests()                                              # e.g. after a restart
    assert _upload(client, **pay).status_code == 402                       # still refused: Razorpay remembers


def test_payment_for_something_else_is_refused(rzp, client):
    assert _upload(client, **rzp.pay(amount=100)).status_code == 402        # Rs 1, not Rs 10
    assert _upload(client, **rzp.pay(purpose="expert")).status_code == 402


def test_authorized_payment_is_captured(rzp, client, monkeypatch):
    monkeypatch.setattr("backend.services.jobs._executor.submit", lambda *a, **k: None)
    pay = rzp.pay(status="authorized")
    assert _upload(client, **pay).status_code == 202
    assert rzp.payments[pay["razorpay_payment_id"]]["status"] == "captured"


def test_samples_are_free(rzp, client, monkeypatch):
    monkeypatch.setattr("backend.services.jobs._executor.submit", lambda *a, **k: None)
    assert _upload(client, content=SAMPLE).status_code == 202
    # renaming doesn't help -- it's the bytes that count
    assert _upload(client, content=SAMPLE + b" ").status_code == 402


def test_failed_check_is_refunded(rzp, monkeypatch, tmp_path):
    from backend.services import jobs
    from backend.services.analysis_pipeline import AnalysisError

    def boom(*a, **k):
        raise AnalysisError(503, "AI unavailable")
    monkeypatch.setattr(jobs, "analyze_file", boom)
    path = tmp_path / "x.txt"
    path.write_text("x")
    jobs._jobs["j1"] = {"job_id": "j1", "status": "queued", "clauses": [], "created_at": "2026-01-01"}
    jobs._run("j1", path, "x.txt", "rental", lambda: None, payment_id="pay_9")
    assert rzp.refunds == ["pay_9"] and jobs._jobs["j1"]["refunded"] is True
    jobs._jobs.pop("j1", None)
