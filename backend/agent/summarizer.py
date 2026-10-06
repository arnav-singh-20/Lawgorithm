"""
Whole-document summary -- runs once per upload, before any clause is
analysed.

    PDF / photo -> extracted text -> summarize_document() -> summary
                                                         |
           every clause's ReAct run gets the summary as context

Why: a clause read in isolation loses facts stated elsewhere in the
contract. "24-month lock-in" is only obviously unfair once you know the
lease itself is 11 months; "Rs 5 lakh penalty" reads differently against
a Rs 20,000 salary. The summary carries those facts (parties, place,
term, money amounts) into every clause's analysis, and is also shown to
the user as the "what is this contract" overview in simple English.

The summary is context only. It is never a citable legal source --
claims must still cite statutes retrieved by search_legal_reference.
"""

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from backend.llm.base import LLMUnavailableError

logger = logging.getLogger(__name__)

# Gemini handles far more, but clauses beyond this are almost always
# schedules/annexures; the head of a contract carries the key terms.
MAX_SUMMARY_INPUT_CHARS = 60_000

SUMMARY_SYSTEM_PROMPT = """
You read Indian contracts (employment agreements, rental/lease
agreements) and summarise them for someone with no legal training.

Write in simple English: short sentences, everyday words, no legal
jargon (say "the landlord can keep your deposit", not "the lessor shall
be entitled to forfeit the security"). Use "you" for the person most
likely to be reading it (the employee or the tenant).

Only state what the document itself says. Do not explain the law and do
not judge whether terms are fair -- that happens later, clause by
clause. If something isn't in the document, use null.

Return ONLY valid JSON, no markdown fences, in exactly this shape:
{
  "document_type": "employment" | "rental" | "other",
  "title": "short name of the document",
  "parties": ["who is in the contract and their role"],
  "location": "city / state named in the document, or null",
  "key_terms": [{"term": "Monthly rent", "value": "Rs 25,000"}],
  "summary": "3 to 6 short simple-English sentences: what this contract is, who it's between, and the main things you agree to."
}
"""


class KeyTerm(BaseModel):
    term: str
    value: str


class DocumentSummary(BaseModel):
    document_type: str = "other"
    title: str | None = None
    parties: list[str] = Field(default_factory=list)
    location: str | None = None
    key_terms: list[KeyTerm] = Field(default_factory=list)
    summary: str


def summarize_document(text: str, provider) -> dict | None:
    """
    Returns a DocumentSummary dict, or None when the model's answer can't
    be used -- the clause analysis still runs without it. An unusable LLM
    (quota, auth, network) raises LLMUnavailableError like everywhere else.
    """
    if not text.strip():
        return None
    try:
        raw = provider.simple_completion(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_input=f"Contract text:\n\n{text[:MAX_SUMMARY_INPUT_CHARS]}",
        )
        return DocumentSummary(**_tidy(_parse_json(raw))).model_dump()
    except LLMUnavailableError:
        raise
    except (ValueError, TypeError, ValidationError):
        logger.warning("Document summary unusable; continuing clause analysis without it.", exc_info=True)
        return None


def summary_as_context(summary: dict | None) -> str:
    """Compact text block handed to each clause's agent run."""
    if not summary:
        return ""
    lines = [f"Summary: {summary['summary']}"]
    if summary.get("location"):
        lines.append(f"Location: {summary['location']}")
    if summary.get("parties"):
        lines.append("Parties: " + "; ".join(summary["parties"]))
    for kt in summary.get("key_terms", [])[:15]:
        lines.append(f"- {kt['term']}: {kt['value']}")
    return "\n".join(lines)


def _tidy(data: dict) -> dict:
    """
    Small local models often return a mostly-good summary with one bad
    field (a key term with value null, parties as a single string). Drop
    or coerce the bad part instead of discarding the whole summary.
    """
    if not isinstance(data, dict):
        raise ValueError("summary is not a JSON object")
    terms = data.get("key_terms") or []
    data["key_terms"] = [
        {"term": str(t["term"]), "value": str(t["value"])}
        for t in terms
        if isinstance(t, dict) and t.get("term") and t.get("value") not in (None, "", "null")
    ]
    parties = data.get("parties") or []
    data["parties"] = [parties] if isinstance(parties, str) else [str(p) for p in parties if p]
    if data.get("document_type") not in ("employment", "rental", "other"):
        data["document_type"] = "other"
    return data


def _parse_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise ValueError("no JSON object in summary response")
        return json.loads(match.group(0))
