"""
Vector store wrapper (Phase 6).

ChromaDB, persisted to disk. Easy to run locally now; if you outgrow it
later, everything that touches Chroma lives in this one file, so
swapping to FAISS/Qdrant/Pinecone means rewriting this file only --
retrieval.py and the agent tools don't need to change.
"""

from typing import List, Optional

import chromadb

from backend.config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME
from backend.rag.chunking import PROVENANCE_FIELDS
from backend.rag.embeddings import EmbeddingModel


class LegalVectorStore:
    _instance = None

    def __init__(self):
        self._client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME
        )
        self._embedder = EmbeddingModel.get()

    @classmethod
    def get(cls) -> "LegalVectorStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_empty(self) -> bool:
        return self._collection.count() == 0

    def add_chunks(self, chunks: List[dict]) -> None:
        if not chunks:
            return

        ids = [c["id"] for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "law": c["law"],
                "section": c["section"],
                "title": c.get("title", ""),
                "domain": c.get("domain", "general"),
                "jurisdiction": c.get("jurisdiction", "India"),
                # Chroma metadata values must be str/int/float/bool -- lists
                # get flattened to a comma-joined string.
                "topics": ",".join(c.get("topics", [])),
                "verified": bool(c.get("verified", True)),
                "source_type": c.get("source_type", "statute"),
                **{field: c.get(field, "") for field in PROVENANCE_FIELDS},
            }
            for c in chunks
        ]
        embeddings = self._embedder.embed(documents)

        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def query(self, query_text: str, domain: Optional[str] = None, top_k: int = 3) -> dict:
        """
        Deliberately does NOT hard-filter by domain. A clause tagged
        "employment" can still be legally grounded in a statute tagged
        "contract" (e.g. Indian Contract Act s.27/74 apply to employment
        non-competes and penalty clauses even though they're filed under
        "contract" generally). Hard-filtering on domain excludes exactly
        that kind of cross-cutting statute.

        `domain` is accepted for a future hybrid rerank (domain-specific
        results boosted, not domain-exclusive) but currently unused --
        we always search the whole corpus and let semantic similarity
        decide relevance.
        """
        embedding = self._embedder.embed([query_text])[0]

        return self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
        )

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed([text])[0]

    def get_with_distances(self, ids: list[str], query_embedding: list[float]) -> list[dict]:
        """
        Rows for specific ids plus their distance to the query, in the same
        metric query() uses (Chroma's default squared L2) -- so a hit found
        by keyword search gets a comparable retrieval score.
        """
        if not ids:
            return []
        raw = self._collection.get(ids=ids, include=["documents", "metadatas", "embeddings"])
        rows = []
        for source_id, doc, meta, emb in zip(raw["ids"], raw["documents"], raw["metadatas"], raw["embeddings"]):
            distance = sum((float(a) - float(b)) ** 2 for a, b in zip(emb, query_embedding))
            rows.append({"id": source_id, "document": doc, "metadata": meta, "distance": distance})
        return rows

    def reset(self) -> None:
        """Danger: wipes the collection. Useful when re-ingesting a new dataset."""
        self._client.delete_collection(CHROMA_COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME
        )
