"""
Text cleaning / normalization (Phase 3).

Goal: strip page furniture (page numbers, repeated headers/footers,
broken line-wraps) WITHOUT destroying clause numbering, since
segmentation (Phase 4) depends on numbering staying intact on its own
line, e.g.:

    4. NON-COMPETE

    The Employee shall not...

and not collapsed into:

    4. NON COMPETE The Employee shall...
"""

import re
from collections import Counter

PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$"),  # bare "3" or "- 3 -"
]

# A clause header line should never be merged with the next line.
CLAUSE_HEADER_PATTERN = re.compile(
    r"^\s*(\d+(\.\d+)*\.?\s+[A-Z].*|CLAUSE\s+\d+.*|[A-Z][A-Z \-/&]{3,})\s*$"
)


def clean_text(text: str) -> str:
    lines = text.split("\n")

    lines = _strip_page_numbers(lines)
    lines = _strip_repeated_headers_footers(lines)
    lines = _collapse_internal_whitespace(lines)
    lines = _rejoin_wrapped_lines(lines)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # no more than one blank line
    return cleaned.strip()


def _strip_page_numbers(lines: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if not any(pattern.match(line) for pattern in PAGE_NUMBER_PATTERNS)
    ]


def _strip_repeated_headers_footers(lines: list[str], min_repeats: int = 3) -> list[str]:
    """
    Any non-trivial line that repeats verbatim many times across the
    document (e.g. "CONFIDENTIAL - ACME CORP EMPLOYMENT AGREEMENT" on
    every page) is almost certainly a header/footer, not contract
    content, and gets removed.
    """
    stripped = [line.strip() for line in lines]
    counts = Counter(l for l in stripped if len(l) > 8)

    repeated = {line for line, count in counts.items() if count >= min_repeats}

    return [line for line in lines if line.strip() not in repeated]


def _collapse_internal_whitespace(lines: list[str]) -> list[str]:
    return [re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in lines]


def _rejoin_wrapped_lines(lines: list[str]) -> list[str]:
    """
    PDF extraction frequently breaks a single sentence across multiple
    lines mid-clause. Rejoin a line with the next one when the current
    line doesn't end in terminal punctuation AND isn't itself a clause
    header (headers should stay on their own line so segmentation can
    find them).
    """
    result: list[str] = []
    buffer = ""

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append("")
            continue

        if CLAUSE_HEADER_PATTERN.match(line):
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append(line)
            continue

        if buffer:
            buffer = f"{buffer} {line}"
        else:
            buffer = line

        if re.search(r"[.;:)]\s*$", buffer):
            result.append(buffer)
            buffer = ""

    if buffer:
        result.append(buffer)

    return result
