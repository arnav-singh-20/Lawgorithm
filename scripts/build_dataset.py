"""
Phase 14 -- convert raw contracts into the standardized processed
format used for RAG testing / evaluation / future fine-tuning.

Reads:   data/raw/employment/*, data/raw/rental/*
Writes:  data/processed/documents.jsonl
         data/processed/clauses.jsonl

Reuses the exact same ingestion + cleaning + segmentation pipeline the
live API uses, so what you evaluate on matches what production does.

This is fully ready to run -- it just has nothing to do until the real
dataset lands in data/raw/.
"""

import json
import uuid

from backend.config import RAW_DIR, PROCESSED_DIR, SUPPORTED_DOCUMENT_TYPES
from backend.ingestion import extract_document, SUPPORTED_EXTENSIONS
from backend.ingestion.cleaner import clean_text
from backend.segmentation.clause_segmenter import segment_clauses


def build():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    documents_path = PROCESSED_DIR / "documents.jsonl"
    clauses_path = PROCESSED_DIR / "clauses.jsonl"

    doc_count = 0
    clause_count = 0

    with open(documents_path, "w", encoding="utf-8") as docs_f, open(
        clauses_path, "w", encoding="utf-8"
    ) as clauses_f:

        for document_type in SUPPORTED_DOCUMENT_TYPES:
            type_dir = RAW_DIR / document_type
            if not type_dir.exists():
                continue

            for file_path in sorted(type_dir.rglob("*")):
                if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue

                document_id = f"{document_type.upper()}_{doc_count + 1:03d}"

                raw_text = extract_document(file_path)
                cleaned = clean_text(raw_text)
                clauses = segment_clauses(cleaned)

                docs_f.write(
                    json.dumps(
                        {
                            "document_id": document_id,
                            "document_type": document_type,
                            "source": str(file_path.relative_to(RAW_DIR)),
                            "text": cleaned,
                            "clause_ids": [
                                f"{document_id}_{c['clause_id']}" for c in clauses
                            ],
                        }
                    )
                    + "\n"
                )

                for clause in clauses:
                    clauses_f.write(
                        json.dumps(
                            {
                                "clause_id": f"{document_id}_{clause['clause_id']}",
                                "document_id": document_id,
                                "document_type": document_type,
                                "clause_title": clause["title"],
                                "clause_text": clause["text"],
                                "risk_label": None,
                                "plain_explanation": None,
                                "legal_sections": [],
                            }
                        )
                        + "\n"
                    )
                    clause_count += 1

                doc_count += 1

    print(f"Wrote {doc_count} documents and {clause_count} clauses to {PROCESSED_DIR}")


if __name__ == "__main__":
    build()
