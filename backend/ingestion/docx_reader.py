"""
DOCX ingestion (Phase 2).
"""

from pathlib import Path

import docx


def extract_docx(file_path: Path) -> str:
    """
    Extract text from a .docx file, preserving paragraph order
    (including text inside tables, which contracts often use for
    signature blocks / schedules).
    """
    document = docx.Document(str(file_path))

    chunks = []

    for para in document.paragraphs:
        if para.text.strip():
            chunks.append(para.text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                chunks.append(" | ".join(cells))

    return "\n".join(chunks)
