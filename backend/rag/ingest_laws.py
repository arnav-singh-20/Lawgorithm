"""
Loads every *.json file in data/statutes/ into the vector store
(Phase 5/6/7).

Run directly to (re)build the index:

    python -m backend.rag.ingest_laws

Right now data/statutes/ only has sample_statutes.json (a handful of
real but illustrative sections) so the agent has something real to
retrieve while the actual dataset is pending. Once you drop the full
bare-act corpus in here (same JSON shape: {"statutes": [{"law": ...,
"sections": [...]}]}), re-run this script -- no other code changes
needed.
"""

import json
import logging

from backend.config import STATUTES_DIR
from backend.rag.chunking import chunk_statute
from backend.rag.vector_store import LegalVectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_statute_files() -> list[dict]:
    if not STATUTES_DIR.exists():
        return []

    all_statutes = []
    for path in sorted(STATUTES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        all_statutes.extend(data.get("statutes", []))

    return all_statutes


def build_index(reset: bool = False) -> int:
    store = LegalVectorStore.get()

    if reset:
        store.reset()

    statutes = load_statute_files()
    if not statutes:
        logger.warning("No statute JSON files found in %s -- index will be empty.", STATUTES_DIR)
        return 0

    total_chunks = 0
    for statute in statutes:
        chunks = chunk_statute(statute["law"], statute["sections"])
        store.add_chunks(chunks)
        total_chunks += len(chunks)
        logger.info("Indexed %d section(s) from %s", len(chunks), statute["law"])

    logger.info("Total chunks indexed: %d", total_chunks)
    return total_chunks


if __name__ == "__main__":
    build_index(reset=True)
