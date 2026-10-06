"""
Phase 1 dataset understanding.

Once you drop the real dataset into data/raw/employment/ and
data/raw/rental/, run:

    python -m scripts.inspect_dataset

This answers the basic questions before any ML code gets written:
file formats present, doc counts per type, and a rough scan for
personal-information indicators (PAN-like patterns, email addresses,
phone numbers) so you know what needs redaction before anything
touches the LLM.
"""

import re
from collections import Counter

from backend.config import RAW_DIR

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")  # common Indian mobile number shape
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def inspect():
    if not RAW_DIR.exists():
        print(f"No data found yet at {RAW_DIR}. Drop the dataset there and re-run.")
        return

    extension_counts = Counter()
    doc_type_counts = Counter()
    pii_hits = Counter()

    for doc_type_dir in RAW_DIR.iterdir():
        if not doc_type_dir.is_dir():
            continue

        for file_path in doc_type_dir.rglob("*"):
            if not file_path.is_file():
                continue

            extension_counts[file_path.suffix.lower()] += 1
            doc_type_counts[doc_type_dir.name] += 1

            if file_path.suffix.lower() in {".txt", ".md"}:
                text = file_path.read_text(errors="ignore")
                if EMAIL_RE.search(text):
                    pii_hits["email"] += 1
                if PHONE_RE.search(text):
                    pii_hits["phone"] += 1
                if PAN_RE.search(text):
                    pii_hits["pan_like"] += 1

    print("File formats found:", dict(extension_counts))
    print("Documents per type:", dict(doc_type_counts))
    print("Possible PII indicators (plain-text files only):", dict(pii_hits))
    print(
        "\nNote: PDFs/DOCX weren't text-scanned here for PII -- run them through "
        "backend.ingestion.extract_document first if you need a full sweep."
    )


if __name__ == "__main__":
    inspect()
