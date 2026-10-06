"""
Personal-data redaction (Digital Personal Data Protection Act, 2023:
data minimisation).

Runs on the extracted contract text BEFORE anything is sent to an AI
service or shown back, so identifiers that aren't needed to explain the
contract never leave the server: email addresses, Indian mobile/landline
numbers, PAN, Aadhaar, IFSC codes, bank account / card numbers, GSTIN and
passport numbers.

Deliberately conservative about amounts: money in contracts is written
with commas ("Rs 2,50,000") or is short, so the digit-run rules require
long unbroken runs (9-18 digits) that rent, salary and notice periods
never have. Names and street addresses can't be detected reliably with
rules -- the privacy notice tells users so.
"""

import re

_RULES: list[tuple[str, re.Pattern]] = [
    ("[EMAIL]", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("[GSTIN]", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    ("[PAN]", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("[IFSC]", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("[PASSPORT]", re.compile(r"\b[A-PR-WY][1-9]\d\s?\d{4}[1-9]\b")),
    # Aadhaar: 12 digits, usually grouped 4-4-4, never starting with 0/1
    ("[AADHAAR]", re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")),
    # phone: +91 / 0 prefixes, 10-digit mobiles starting 6-9, landlines with STD code
    ("[PHONE]", re.compile(r"(?<![\w,])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}\b")),
    ("[PHONE]", re.compile(r"(?<![\w,])0\d{2,4}[\s-]\d{6,8}\b")),
    # bank account / card numbers: long unbroken digit runs
    ("[ACCOUNT_NO]", re.compile(r"(?<![\w,.])\d{9,18}(?![\w,])")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Returns (redacted_text, {label: count}) -- counts only, never the values."""
    counts: dict[str, int] = {}
    for label, pattern in _RULES:
        text, n = pattern.subn(label, text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return text, counts
