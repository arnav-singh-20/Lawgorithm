"""
Pay-per-use with Razorpay (UPI, cards, netbanking).

    contract check          PRICE_ANALYSIS_PAISE        (default Rs 10)
    human expert check      EXPERT_REVIEW_PRICE_PAISE   (default free -- see config)
    sample contracts        always free

Flow (Razorpay Standard Checkout + Orders API):

    page --POST /payments/order--> create_order()   -> Razorpay order
    page opens Razorpay Checkout; the person pays
    page --upload + {order_id, payment_id, signature}--> redeem()
          1. HMAC-SHA256(order_id|payment_id, key_secret) == signature
          2. Razorpay says: the order is ours, for this purpose and price,
             and the payment is captured (authorized ones are captured here)
          3. not used before -- recorded ON THE PAYMENT ITSELF (its notes),
             so a restart can't make a payment usable twice
    analysis fails on our side  -> refund() in full, automatically

Payments are off (everything free) until RAZORPAY_KEY_ID and
RAZORPAY_KEY_SECRET are set -- test keys work before KYC. The secret is
used only server-side and never logged or sent to the page.

DPDP: Lawgorithm never sees card/UPI details (Razorpay's checkout handles
them); it keeps no payment records of its own.
"""

import hashlib
import hmac
import logging
import secrets
import threading
from pathlib import Path

import httpx

from backend.config import (
    EXPERT_REVIEW_PRICE_PAISE,
    PRICE_ANALYSIS_PAISE,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
)

logger = logging.getLogger(__name__)

API = "https://api.razorpay.com/v1"
PURPOSES = ("analysis", "expert")
USED_NOTE = "lawgorithm_used"

_used: set[str] = set()          # this process's view; Razorpay notes are the real record
_lock = threading.Lock()

# Sample contracts are free: recognised byte-for-byte, not by file name.
_SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "samples"
_SAMPLE_HASHES = {hashlib.sha256(p.read_bytes()).hexdigest() for p in _SAMPLES_DIR.glob("*.txt")} \
    if _SAMPLES_DIR.exists() else set()


class PaymentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def enabled() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def price(purpose: str) -> int:
    """Price in paise; 0 means free."""
    if not enabled():
        return 0
    return {"analysis": PRICE_ANALYSIS_PAISE, "expert": EXPERT_REVIEW_PRICE_PAISE}.get(purpose, 0)


def is_sample(content: bytes) -> bool:
    return hashlib.sha256(content).hexdigest() in _SAMPLE_HASHES


def _api(method: str, path: str, **kwargs) -> dict:
    try:
        response = httpx.request(method, API + path, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), timeout=30, **kwargs)
    except httpx.HTTPError as exc:
        raise PaymentError(503, "The payment service couldn’t be reached. You haven’t been charged — please try again in a minute.") from exc
    if response.status_code >= 400:
        try:
            reason = response.json().get("error", {}).get("description", "")
        except Exception:
            reason = ""
        logger.warning("Razorpay %s %s -> %s %s", method, path.split("/")[1], response.status_code, reason[:120])
        raise PaymentError(502, "The payment service isn't available right now. You haven’t been charged — please try again in a minute.")
    return response.json()


def create_order(purpose: str) -> dict:
    if purpose not in PURPOSES:
        raise PaymentError(400, "Unknown purchase.")
    amount = price(purpose)
    if amount <= 0:
        raise PaymentError(400, "This is free — no payment needed.")
    order = _api("POST", "/orders", json={
        "amount": amount, "currency": "INR", "receipt": f"lg_{secrets.token_hex(6)}",
        "notes": {"purpose": purpose},
    })
    return {"order_id": order["id"], "amount": order["amount"], "currency": "INR", "key_id": RAZORPAY_KEY_ID}


def _signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def redeem(purpose: str, order_id: str | None, payment_id: str | None, signature: str | None, use_ref: str) -> str:
    """
    Check a payment covers `purpose` and mark it used. Returns the payment
    id (for a refund if our side fails). Raises PaymentError(402) when
    missing or invalid.
    """
    if not (order_id and payment_id and signature):
        raise PaymentError(402, f"Please pay ₹{price(purpose) // 100} first.")
    if not _signature_ok(order_id, payment_id, signature):
        raise PaymentError(402, "That payment couldn't be verified.")
    with _lock:
        if payment_id in _used:
            raise PaymentError(402, "This payment has already been used.")
        order = _api("GET", f"/orders/{order_id}")
        payment = _api("GET", f"/payments/{payment_id}")
        if (order.get("notes") or {}).get("purpose") != purpose or order.get("amount", 0) < price(purpose):
            raise PaymentError(402, "That payment was for something else.")
        if payment.get("order_id") != order_id:
            raise PaymentError(402, "That payment couldn't be verified.")
        if (payment.get("notes") or {}).get(USED_NOTE):
            raise PaymentError(402, "This payment has already been used.")
        if payment.get("status") == "authorized":
            payment = _api("POST", f"/payments/{payment_id}/capture", json={"amount": payment["amount"], "currency": "INR"})
        if payment.get("status") != "captured":
            raise PaymentError(402, "The payment hasn't gone through yet. Please try again.")
        _api("PATCH", f"/payments/{payment_id}", json={"notes": {**(payment.get("notes") or {}), USED_NOTE: use_ref[:40]}})
        _used.add(payment_id)
    logger.info("Payment redeemed for %s", purpose)        # never the ids or amounts of a person
    return payment_id


def refund(payment_id: str | None, reason: str) -> bool:
    """Full refund when Lawgorithm couldn't deliver. Never raises."""
    if not payment_id or not enabled():
        return False
    try:
        _api("POST", f"/payments/{payment_id}/refund", json={"notes": {"reason": reason[:200]}})
        logger.info("Refunded a payment (%s)", reason[:60])
        return True
    except PaymentError:
        logger.error("Automatic refund FAILED -- refund it from the Razorpay dashboard")
        return False


def reset_for_tests() -> None:
    _used.clear()
