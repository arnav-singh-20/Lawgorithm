"""
PDF ingestion (Phase 2).

Strategy: try the native text layer first (cheap, accurate for
digitally-generated contracts). The caller decides whether the result
is "sufficient" and falls back to OCR (ocr.py) if not — see
ingestion/__init__.py:extract_document.
"""

from pathlib import Path

from pypdf import PdfReader

from backend.config import MIN_TEXT_CHARS_PER_PAGE


def extract_pdf(file_path: Path) -> str:
    """
    Extract text from a PDF using its embedded text layer.

    Returns an empty string (not an exception) when the PDF appears to
    be scanned / image-only, so the caller can trigger OCR fallback.
    """
    reader = PdfReader(str(file_path))

    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)

    full_text = "\n\n".join(pages_text)

    if not is_text_sufficient(pages_text):
        return ""

    if _lacks_line_structure(full_text):
        # Some PDF generators position each line absolutely, and the
        # default extractor then returns one giant space-padded line --
        # which leaves clause segmentation nothing to split on. Layout
        # mode reconstructs the visual lines.
        layout_text = "\n\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
        if not _lacks_line_structure(layout_text):
            return layout_text

    return full_text


def _lacks_line_structure(text: str, min_chars_per_line_break: int = 300) -> bool:
    """True when there's less than one line break per ~300 characters of text."""
    stripped = text.strip()
    return len(stripped) > min_chars_per_line_break and stripped.count("\n") < len(stripped) / min_chars_per_line_break


def is_text_sufficient(pages_text: list[str]) -> bool:
    """
    Heuristic: if the average extracted characters per page is below a
    threshold, this is very likely a scanned document with little or no
    real text layer, and OCR should be used instead.
    """
    if not pages_text:
        return False

    total_chars = sum(len(p.strip()) for p in pages_text)
    avg_chars_per_page = total_chars / len(pages_text)

    return avg_chars_per_page >= MIN_TEXT_CHARS_PER_PAGE
