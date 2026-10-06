"""
Contact and grievances (DPDP Act, 2023: a way to raise a complaint about
how personal data is handled; also payment/refund questions).

    POST   /contact                        {topic, message, reply_to?}
    GET    /contact/messages               owner only (X-Reviewer-Key)
    DELETE /contact/messages/{id}          owner only

Messages are kept in the same private store as the expert-review queue
(meta "messages"), read on the owner's reviewer page, and deleted after
MESSAGE_KEEP_DAYS -- or as soon as the owner deletes them. The optional
reply_to (email/phone) is given by the person so we can answer; it is
used for nothing else.
"""

import datetime
import logging
import secrets
import threading

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.expert_review import service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contact")

TOPICS = ("grievance", "payment", "question", "other")
MAX_MESSAGES = 500
MESSAGE_KEEP_DAYS = 90
_lock = threading.Lock()


class ContactRequest(BaseModel):
    topic: str
    message: str
    reply_to: str = ""
    website: str = ""          # honeypot: people never fill it in, bots do


def _store():
    store = service.get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Messages can't be received right now. Please try again later.")
    return store


def _fresh(messages: list[dict]) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=MESSAGE_KEEP_DAYS)
    return [m for m in messages if datetime.datetime.fromisoformat(m["at"]) > cutoff]


@router.post("", status_code=201)
def send(request: ContactRequest):
    if request.website:
        return {"received": True}
    message = request.message.strip()
    if request.topic not in TOPICS or not (5 <= len(message) <= 2000) or len(request.reply_to) > 200:
        raise HTTPException(status_code=400, detail="Please choose a topic and write a message (up to 2000 characters).")
    store = _store()
    with _lock:
        messages = _fresh(store.get_meta("messages", []) or [])
        if len(messages) >= MAX_MESSAGES:
            raise HTTPException(status_code=503, detail="Our inbox is full right now. Please try again later.")
        messages.append({
            "id": secrets.token_hex(6), "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "topic": request.topic, "message": message, "reply_to": request.reply_to.strip(),
        })
        store.put_meta("messages", messages)
    logger.info("Contact message received (%s)", request.topic)
    return {"received": True}


def _owner(key: str | None) -> None:
    try:
        who = service.identify(key)
    except service.ReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if who["role"] != service.OWNER:
        raise HTTPException(status_code=403, detail="Only the owner can read messages.")


@router.get("/messages")
def list_messages(x_reviewer_key: str | None = Header(default=None)):
    _owner(x_reviewer_key)
    messages = _fresh(_store().get_meta("messages", []) or [])
    return {"messages": sorted(messages, key=lambda m: m["at"], reverse=True)}


@router.delete("/messages/{message_id}")
def delete_message(message_id: str, x_reviewer_key: str | None = Header(default=None)):
    _owner(x_reviewer_key)
    store = _store()
    with _lock:
        messages = store.get_meta("messages", []) or []
        remaining = [m for m in messages if m["id"] != message_id]
        if len(remaining) == len(messages):
            raise HTTPException(status_code=404, detail="Message not found.")
        store.put_meta("messages", remaining)
    return {"deleted": True}
