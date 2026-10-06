"""
Expert review -- the human in the loop.

When Lawgorithm can't confirm its own answer for a clause (decision
"expert", see risk/decision.py) it doesn't guess. The person can choose to
send those clauses to a partner reviewer (a lawyer or law student):

    results page --(consent)--> create_ticket() --> store (private)
                                                      |
    reviewer desk <-- pending() <---------------------+
         |
         +--> record_review(decision, risk, note) --> ticket page shows it

DPDP Act, 2023:
  - consent: nothing is sent without an explicit tick (s.6);
  - minimisation: only the chosen clauses travel -- their text is already
    redacted (privacy/redaction.py) -- plus the AI's analysis; no file,
    no summary, no names of the person;
  - storage limitation: deleted EXPERT_REVIEW_KEEP_DAYS after the review,
    and never kept beyond EXPERT_REVIEW_MAX_DAYS (prune());
  - erasure: the person can delete the ticket at any time (delete()).

The ticket id is a long random secret: whoever holds the link can see
the result, nobody can guess it.

Reviewers: the OWNER keys come from REVIEWER_KEYS (.env / Space secret).
An owner adds and removes reviewers on the reviewer page; each gets an
invite link carrying a fresh key. Only a SHA-256 hash of that key is
stored (meta "reviewers" in the store), and removal works instantly.
"""

import datetime
import hashlib
import hmac
import logging
import secrets
import threading

from backend.config import (
    EXPERT_REVIEW_DIR,
    EXPERT_REVIEW_KEEP_DAYS,
    EXPERT_REVIEW_MAX_DAYS,
    EXPERT_REVIEW_STORE,
    HF_REVIEW_TOKEN,
    REVIEW_DATASET,
    REVIEWER_KEYS,
)
from backend.privacy.redaction import redact
from backend.risk.decision import LAWYER, NEGOTIATE, NO_LAWYER

logger = logging.getLogger(__name__)

REVIEW_DECISIONS = (NO_LAWYER, NEGOTIATE, LAWYER)
MAX_REVIEWERS = 50
OWNER, REVIEWER = "owner", "reviewer"
MAX_CLAUSES_PER_TICKET = 25
MAX_NOTE_CHARS = 2000

_store = None
_store_lock = threading.Lock()
_ticket_for_document: dict[str, str] = {}   # one ticket per analysis


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def reviewers() -> dict[str, str]:
    """OWNER keys: {key: name} from REVIEWER_KEYS ("Name=key;Name2=key2")."""
    out = {}
    for entry in REVIEWER_KEYS.split(";"):
        name, _, key = entry.strip().rpartition("=")
        if name.strip() and len(key.strip()) >= 16:
            out[key.strip()] = name.strip()
    return out


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            if EXPERT_REVIEW_STORE == "local":
                from backend.expert_review.store import LocalStore
                _store = LocalStore(EXPERT_REVIEW_DIR)
            elif EXPERT_REVIEW_STORE == "hf" and REVIEW_DATASET and HF_REVIEW_TOKEN:
                from backend.expert_review.store import HFDatasetStore
                try:
                    _store = HFDatasetStore(REVIEW_DATASET, HF_REVIEW_TOKEN)
                except Exception as exc:
                    logger.error("Expert review store unavailable: %s", type(exc).__name__)
                    return None
        return _store


def enabled() -> bool:
    """On only when there's somewhere to keep tickets AND someone to review them."""
    if not reviewers():
        return False
    if EXPERT_REVIEW_STORE == "local":
        return True
    return EXPERT_REVIEW_STORE == "hf" and bool(REVIEW_DATASET and HF_REVIEW_TOKEN)


def _require_store():
    store = get_store() if enabled() else None
    if store is None:
        raise ReviewError(503, "Expert review isn't available right now.")
    return store


def _expired(ticket: dict, now: datetime.datetime) -> bool:
    created = datetime.datetime.fromisoformat(ticket["created_at"])
    if now - created > datetime.timedelta(days=EXPERT_REVIEW_MAX_DAYS):
        return True
    reviewed = ticket.get("reviewed_at")
    return bool(reviewed) and now - datetime.datetime.fromisoformat(reviewed) > datetime.timedelta(days=EXPERT_REVIEW_KEEP_DAYS)


def prune() -> int:
    store = get_store() if enabled() else None
    if store is None:
        return 0
    now, removed = _now(), 0
    for ticket in store.all():
        if _expired(ticket, now):
            store.delete(ticket["id"])
            removed += 1
    return removed


def _public_view(ticket: dict) -> dict:
    """What the ticket link shows: everything except reviewer identities' keys (never stored)."""
    return {**ticket, "keep_days": EXPERT_REVIEW_KEEP_DAYS, "max_days": EXPERT_REVIEW_MAX_DAYS}


def create_ticket(document: dict, clause_row_ids: list[str], consent: bool) -> dict:
    if not consent:
        raise ReviewError(400, "Please tick the box to agree before sending clauses for an expert check.")
    store = _require_store()
    existing = _ticket_for_document.get(document["document_id"])
    if existing and store.get(existing):
        return _public_view(store.get(existing))

    wanted = set(clause_row_ids or [])
    chosen = [c for c in document.get("clauses", []) if c.get("clause_row_id") in wanted]
    if not chosen:
        raise ReviewError(400, "Choose at least one clause to send.")
    if len(chosen) > MAX_CLAUSES_PER_TICKET:
        raise ReviewError(400, f"At most {MAX_CLAUSES_PER_TICKET} clauses can be sent at once.")

    prune()
    now = _now().isoformat()
    ticket = {
        "id": secrets.token_urlsafe(18),
        "created_at": now,
        "reviewed_at": None,
        "status": "waiting",                       # waiting | reviewed
        "document_type": document.get("document_type"),
        "jurisdiction_states": document.get("jurisdiction_states") or [],
        "clauses": [_clause_for_review(c) for c in chosen],
    }
    store.put(ticket)
    _ticket_for_document[document["document_id"]] = ticket["id"]
    logger.info("Expert review: ticket created with %d clause(s)", len(chosen))   # never content
    return _public_view(ticket)


def has_ticket(document_id: str) -> bool:
    """Sending again for the same analysis returns the existing ticket -- never charge twice."""
    store = get_store() if enabled() else None
    tid = _ticket_for_document.get(document_id)
    return bool(store and tid and store.get(tid))


def _clause_for_review(c: dict) -> dict:
    text, _ = redact(c.get("clause_text") or "")       # belt and braces: already redacted upstream
    return {
        "clause_row_id": c.get("clause_row_id"),
        "clause_id": c.get("clause_id"),
        "clause_title": c.get("clause_title"),
        "clause_text": text,
        "ai": {
            "plain_explanation": c.get("plain_explanation"),
            "risk_level": c.get("risk_level"),
            "legal_assessment": c.get("legal_assessment"),
            "recommended_action": c.get("recommended_action"),
            "consequence": c.get("consequence") or "",
            "decision": c.get("decision"),
            "confidence": c.get("confidence"),
            "status": c.get("status"),
            "review_flags": c.get("review_flags") or [],
            "claims": [cl.get("claim") for cl in (c.get("claims") or []) if isinstance(cl, dict)],
            "cited_sources": [
                {k: s.get(k) for k in ("id", "law", "section", "title", "official_source")}
                for s in (c.get("cited_sources") or [])
            ],
        },
        "review": None,
    }


def get_ticket(ticket_id: str) -> dict:
    store = _require_store()
    ticket = store.get(ticket_id)
    if ticket is None or _expired(ticket, _now()):
        raise ReviewError(404, "This expert check was deleted or has expired.")
    return _public_view(ticket)


def delete_ticket(ticket_id: str) -> bool:
    store = _require_store()
    if store.get(ticket_id) is None:
        return False
    store.delete(ticket_id)
    for doc_id, tid in list(_ticket_for_document.items()):
        if tid == ticket_id:
            _ticket_for_document.pop(doc_id, None)
    return True


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _invited() -> list[dict]:
    store = get_store() if enabled() else None
    return (store.get_meta("reviewers", []) if store else []) or []


def identify(key: str | None) -> dict:
    """{"name", "role": owner|reviewer, "id"} for a valid key, else 401."""
    if key:
        for known, name in reviewers().items():
            if hmac.compare_digest(key.encode(), known.encode()):
                return {"name": name, "role": OWNER, "id": None}
        digest = _hash(key)
        for r in _invited():
            if hmac.compare_digest(digest, r["key_hash"]):
                return {"name": r["name"], "role": REVIEWER, "id": r["id"]}
    raise ReviewError(401, "Unknown reviewer key.")


def reviewer_name(key: str | None) -> str:
    return identify(key)["name"]


def _require_owner(key: str | None) -> dict:
    who = identify(key)
    if who["role"] != OWNER:
        raise ReviewError(403, "Only the owner can manage reviewers.")
    return who


def list_reviewers(owner_key: str | None) -> list[dict]:
    _require_owner(owner_key)
    owners = [{"id": None, "name": name, "role": OWNER} for name in reviewers().values()]
    invited = [{"id": r["id"], "name": r["name"], "role": REVIEWER, "added_at": r["added_at"], "added_by": r["added_by"]}
               for r in _invited()]
    return owners + invited


def add_reviewer(owner_key: str | None, name: str) -> dict:
    """Returns the new reviewer with their key -- shown ONCE, inside the invite link."""
    owner = _require_owner(owner_key)
    store = _require_store()
    name = " ".join((name or "").split())
    if not name or len(name) > 60:
        raise ReviewError(400, "Give the reviewer's name (up to 60 characters).")
    current = _invited()
    if any(r["name"].lower() == name.lower() for r in current) or name.lower() in (n.lower() for n in reviewers().values()):
        raise ReviewError(400, "There's already a reviewer with that name.")
    if len(current) >= MAX_REVIEWERS:
        raise ReviewError(400, f"At most {MAX_REVIEWERS} reviewers.")
    key = secrets.token_urlsafe(24)
    entry = {"id": secrets.token_hex(6), "name": name, "key_hash": _hash(key),
             "added_at": _now().isoformat(), "added_by": owner["name"]}
    store.put_meta("reviewers", current + [entry])
    logger.info("Expert review: reviewer added")
    return {"id": entry["id"], "name": name, "key": key}


def remove_reviewer(owner_key: str | None, reviewer_id: str) -> bool:
    _require_owner(owner_key)
    store = _require_store()
    current = _invited()
    remaining = [r for r in current if r["id"] != reviewer_id]
    if len(remaining) == len(current):
        return False
    store.put_meta("reviewers", remaining)
    logger.info("Expert review: reviewer removed")
    return True


def pending() -> list[dict]:
    """Every clause still waiting for a reviewer, oldest ticket first."""
    store = _require_store()
    prune()
    items = []
    for ticket in sorted(store.all(), key=lambda t: t["created_at"]):
        for clause in ticket["clauses"]:
            if clause.get("review") is None:
                items.append({"ticket_id": ticket["id"], "created_at": ticket["created_at"],
                              "document_type": ticket.get("document_type"),
                              "jurisdiction_states": ticket.get("jurisdiction_states") or [], **clause})
    return items


def record_review(ticket_id: str, clause_row_id: str, reviewer: str, decision: str,
                  risk_level: str, note: str = "", consequence: str = "") -> dict:
    """
    The person reads, for anything but "no lawyer needed": "This clause is
    important. If you don't fix it, <consequence>. For more detail, talk to
    a lawyer." -- so the consequence is required there; the note is extra.
    """
    from backend.agent.agent import clean_consequence

    if decision not in REVIEW_DECISIONS:
        raise ReviewError(400, f"decision must be one of {REVIEW_DECISIONS}.")
    if risk_level not in ("red", "amber", "green"):
        raise ReviewError(400, "risk_level must be red, amber or green.")
    note = (note or "").strip()
    consequence = clean_consequence(consequence) if decision != NO_LAWYER else ""
    if decision != NO_LAWYER and not consequence:
        raise ReviewError(400, "Say what happens if they don't fix it -- it completes \"If you don't fix it, ...\".")
    if decision == NO_LAWYER and not note:
        raise ReviewError(400, "Write a short note for the person -- it's what they'll read.")
    store = _require_store()
    ticket = store.get(ticket_id)
    if ticket is None:
        raise ReviewError(404, "This expert check was deleted or has expired.")
    clause = next((c for c in ticket["clauses"] if c["clause_row_id"] == clause_row_id), None)
    if clause is None:
        raise ReviewError(404, "Clause not found in this expert check.")

    now = _now().isoformat()
    clause["review"] = {
        "decision": decision,
        "risk_level": risk_level,
        "note": note[:MAX_NOTE_CHARS],
        "consequence": consequence,
        "reviewer": reviewer,
        "reviewed_at": now,
        "agrees_with_ai": decision == clause["ai"].get("decision") or risk_level == clause["ai"].get("risk_level"),
    }
    if all(c.get("review") for c in ticket["clauses"]):
        ticket["status"], ticket["reviewed_at"] = "reviewed", now
    store.put(ticket)
    logger.info("Expert review: clause reviewed")
    return _public_view(ticket)


def reset_for_tests() -> None:
    global _store
    with _store_lock:
        _store = None
    _ticket_for_document.clear()
