"""
Section-based chunking for the legal corpus (Phase 5B).

Deliberately NOT token-count chunking. Each chunk = one full statutory
section, so provisos/exceptions/definitions inside a section are never
split across chunks. This is what ingest_laws.py calls once the real
dataset (full bare acts) is available.
"""

import re

CHUNK_ID_SANITIZE_PATTERN = re.compile(r"[^a-z0-9_]+")

PROVENANCE_FIELDS = ("official_source", "source_version", "effective_date", "last_verified")


def make_chunk_id(law: str, section: str) -> str:
    slug = f"{law}_section_{section}".lower().replace(" ", "_")
    return CHUNK_ID_SANITIZE_PATTERN.sub("_", slug).strip("_")


def chunk_statute(law: str, sections: list[dict], domain: str | None = None) -> list[dict]:
    """
    sections: list of {"section": "27", "title": "...", "text": "...", "domain": "..."}
    Returns chunk dicts ready for the vector store, one per section.

    Optional per-section fields (Phase 10 richer schema) are passed
    through if present, with sensible defaults otherwise so existing
    minimal statute JSON keeps working unchanged:
        "topics": ["employment", "non_compete"]  (default: [domain])
        "verified": true/false                    (default: True -- hand-curated seed data)
        "source_type": "statute"                  (default: "statute")

    Provenance / versioning fields (Phase 4). Default to "" -- unknown --
    rather than a guessed value; scripts/validate_statutes.py reports
    every section still missing them:
        "official_source": URL of the official text (e.g. indiacode.nic.in)
        "source_version":  amendment / version identifier of that text
        "effective_date":  date this version of the section took effect (YYYY-MM-DD)
        "last_verified":   date a team member last checked it against the source
    """
    chunks = []

    for section in sections:
        section_number = str(section["section"])
        section_domain = section.get("domain", domain or "general")
        chunks.append(
            {
                "id": make_chunk_id(law, section_number),
                "law": law,
                "section": section_number,
                "title": section.get("title", ""),
                "domain": section_domain,
                "jurisdiction": section.get("jurisdiction", "India"),
                "topics": section.get("topics", [section_domain]),
                "verified": section.get("verified", True),
                "source_type": section.get("source_type", "statute"),
                **{field: str(section.get(field) or "") for field in PROVENANCE_FIELDS},
                "text": section["text"].strip(),
            }
        )

    return chunks
