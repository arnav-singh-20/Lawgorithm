"""
Clause segmentation (Phase 4).

Splits a full contract into individually-addressable clauses so we
never send a 20-page document to the LLM in one shot. Hybrid
rule-based / regex approach using common Indian contract header
conventions: numbered headers ("4. NON-COMPETE"), sub-numbered
("4.1"), explicit "CLAUSE n" markers, and ALL-CAPS section titles.
"""

import re
from dataclasses import dataclass, asdict

HEADER_PATTERNS = [
    re.compile(r"^\s*(\d+)\.\s+([A-Z][A-Za-z \-/&,()]{2,})\s*$"),        # "4. NON-COMPETE"
    re.compile(r"^\s*(\d+\.\d+)\s+([A-Z][A-Za-z \-/&,()]{2,})\s*$"),      # "4.1 Notice Period"
    re.compile(r"^\s*CLAUSE\s+(\d+)\s*[:\-]?\s*(.*)$", re.IGNORECASE),   # "CLAUSE 4: Non-Compete"
    re.compile(r"^\s*([A-Z][A-Z \-/&]{4,})\s*$"),                       # "NON-COMPETE" (all caps line)
]


@dataclass
class Clause:
    clause_id: str
    title: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


# "2. SECURITY DEPOSIT The Tenant shall..." inside a single flattened
# line -- what PDF text layers without line breaks, OCR, and photo
# transcriptions often produce. Requires an ALL-CAPS title of 2+ letters
# so ordinary "...for 2. Years" sentences don't split.
INLINE_HEADER_PATTERN = re.compile(r"(?:(?<=\s)|^)(\d{1,3}(?:\.\d{1,3})?)\.?\s+(?=[A-Z][A-Z\-/&,()]+(?:\s+[A-Z][A-Z\-/&,()]+)*\s)")


def segment_clauses(text: str) -> list[dict]:
    """
    Returns a list of {clause_id, title, text} dicts in document order.
    Content that appears before the first recognized header is kept as
    a "0" / "PREAMBLE" clause so nothing gets silently dropped. A signature
    block ("LANDLORD / Ramesh Kumar", "WITNESSES") is kept too but marked
    kind="signature" so it isn't analysed as a clause.
    """
    clauses = _segment_lines(text)
    if len(clauses) == 1 and clauses[0]["title"] == "FULL DOCUMENT":
        # No header sits on its own line -- try headers embedded inline.
        restructured = _break_inline_headers(text)
        if restructured != text:
            inline = _segment_lines(restructured)
            if len(inline) > 1:
                clauses = inline
    for clause in clauses:
        if _is_signature_block(clause):
            clause["kind"] = "signature"
    return clauses


# All-caps lines that start a signature block, not a clause. Seen live: the
# "LANDLORD" above a signature became a 14th "clause" and was analysed.
_SIGNATURE_TITLES = re.compile(
    r"^(?:(?:THE\s+)?(?:LANDLORD|TENANT|LESSOR|LESSEE|LICENSOR|LICENSEE|OWNER|EMPLOYER|EMPLOYEE|COMPANY|"
    r"WITNESS(?:ES)?|SIGNATURES?|SIGNED|SIGNATORIES|IN WITNESS WHEREOF|DATE|PLACE|ACCEPTED(?: BY)?|"
    r"FOR AND ON BEHALF OF.*)[\s:.,/&]*)+$"
)


def _is_signature_block(clause: dict) -> bool:
    title = (clause.get("title") or "").strip().upper()
    return bool(_SIGNATURE_TITLES.match(title)) and len(clause.get("text") or "") < 400


def _break_inline_headers(text: str) -> str:
    """
    Puts each inline "N. TITLE" header on its own line, with the title
    (the run of ALL-CAPS words) separated from the body that follows.
    """
    def _split(match: re.Match) -> str:
        return f"\n\n{match.group(1)}. "

    with_breaks = INLINE_HEADER_PATTERN.sub(_split, text)
    out = []
    for line in with_breaks.split("\n"):
        m = re.match(r"^(\d{1,3}(?:\.\d{1,3})?\.\s+)((?:[A-Z][A-Z\-/&,()]+\s+)*[A-Z][A-Z\-/&,()]+)\s+(.*)$", line)
        if m and m.group(3):
            out.append(f"{m.group(1)}{m.group(2)}")
            out.append(m.group(3))
        else:
            out.append(line)
    return "\n".join(out)


def _segment_lines(text: str) -> list[dict]:
    lines = text.split("\n")

    headers: list[tuple[int, str, str]] = []  # (line_index, clause_id, title)
    auto_counter = 0

    for idx, line in enumerate(lines):
        match = _match_header(line)
        if match:
            clause_id, title = match
            if clause_id is None:
                auto_counter += 1
                clause_id = str(auto_counter)
            headers.append((idx, clause_id, title.strip() or "UNTITLED"))

    if not headers:
        # No structure detected at all -- return the whole thing as one clause
        # rather than silently failing.
        return [Clause("1", "FULL DOCUMENT", text.strip()).to_dict()]

    # An un-numbered ALL-CAPS line before the first numbered clause in a
    # numbered document is the document's title ("RESIDENTIAL LEASE
    # AGREEMENT"), not clause "1" -- treating it as one collided with
    # the real "1. TERM". Fold it into the preamble instead.
    numbered = [h for h in headers if re.match(r"^\d", lines[h[0]].strip())]
    if numbered:
        first_numbered = numbered[0][0]
        headers = [h for h in headers if h[0] >= first_numbered or re.match(r"^\d", lines[h[0]].strip())]

    # Any remaining duplicate ids (e.g. a contract that restarts its
    # numbering in a schedule) get a suffix so every clause is addressable.
    seen_ids: dict[str, int] = {}
    unique_headers = []
    for line_idx, clause_id, title in headers:
        seen_ids[clause_id] = seen_ids.get(clause_id, 0) + 1
        if seen_ids[clause_id] > 1:
            clause_id = f"{clause_id}-{seen_ids[clause_id]}"
        unique_headers.append((line_idx, clause_id, title))
    headers = unique_headers

    clauses: list[Clause] = []

    # Preamble: anything before the first header.
    preamble = "\n".join(lines[: headers[0][0]]).strip()
    if preamble:
        clauses.append(Clause("0", "PREAMBLE", preamble))

    for i, (line_idx, clause_id, title) in enumerate(headers):
        start = line_idx + 1
        end = headers[i + 1][0] if i + 1 < len(headers) else len(lines)
        body = "\n".join(lines[start:end]).strip()

        if not body:
            continue  # header with no content (e.g. a stray all-caps line) -> skip

        clauses.append(Clause(clause_id, title, body))

    return [c.to_dict() for c in clauses]


def _match_header(line: str) -> tuple[str | None, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    for pattern in HEADER_PATTERNS:
        m = pattern.match(stripped)
        if not m:
            continue

        groups = m.groups()

        if len(groups) == 2 and groups[0] and re.match(r"^\d", groups[0]):
            return groups[0], groups[1]

        if len(groups) == 1:
            # ALL-CAPS-only header, no explicit number
            return None, groups[0]

        if len(groups) == 2:
            return groups[0], groups[1] or ""

    return None
