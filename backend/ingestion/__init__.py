"""
Document ingestion dispatcher (Phase 2).

    PDF / DOCX / PNG / JPG / TXT
            |
            v
     extract_document()
            |
            v
       raw text string
"""

from pathlib import Path
from typing import Union

from backend.ingestion.pdf_reader import extract_pdf
from backend.ingestion.docx_reader import extract_docx
from backend.ingestion.ocr import extract_with_ocr

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt"}


def extract_document(file_path: Union[Path, str]) -> str:
    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file format: {extension}")

    if extension == ".pdf":
        text = extract_pdf(file_path)
        if text:
            return text
        # Native text layer was empty/insufficient -> scanned PDF -> OCR.
        return extract_with_ocr(file_path)

    if extension == ".docx":
        return extract_docx(file_path)

    if extension == ".txt":
        # Plain text: the frontend's built-in sample contracts are
        # uploaded this way.
        return file_path.read_text(encoding="utf-8", errors="replace")

    # .png / .jpg / .jpeg
    return extract_with_ocr(file_path)
