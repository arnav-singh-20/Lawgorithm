"""
Clause-precedent index: "what kind of clause is this?"

A second Chroma collection, deliberately separate from the statute
collection in vector_store.py. It holds example contract clauses from
the team's clause dataset (built by scripts/build_clause_corpus.py),
each tagged with a canonical clause type (rag/clause_taxonomy.py).

Why separate, and why it is never citable:
  The precedent clauses are mostly US SEC-filed contracts. They are good
  evidence of what TYPE a clause is ("this reads like a non-compete")
  and useless -- actively misleading -- as evidence of what Indian LAW
  says. So this index:
    - is only queried by classify_clause_type(), never by the agent's
      search_legal_reference tool,
    - never adds anything to context["retrieved_sources"], so the
      citation validator rejects any claim that tries to cite a
      precedent id.
  The agent receives the predicted type as a hint (plus a statute
  search suggestion) and still has to find real statutory grounding.

Classification = k-nearest-neighbour vote, weighted by similarity. The
vote share of the winning type is reported as the type confidence; if
it's below CLAUSE_TYPE_MIN_CONFIDENCE the type is reported as unknown
rather than guessed.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import chromadb

from backend.config import (
    CHROMA_PERSIST_DIR,
    CLAUSE_COLLECTION_NAME,
    CLAUSE_CORPUS_DIR,
    CLAUSE_TYPE_MIN_CONFIDENCE,
)
from backend.rag.clause_classifier import ClauseClassifier
from backend.rag.clause_taxonomy import OTHER, get_clause_type
from backend.rag.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)

DEFAULT_K = 15
EMBED_BATCH_SIZE = 256


class ClauseIndex:
    _instance = None

    def __init__(self):
        self._client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name=CLAUSE_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        self._embedder = EmbeddingModel.get()

    @classmethod
    def get(cls) -> "ClauseIndex":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def count(self) -> int:
        return self._collection.count()

    def add(self, records: list[dict]) -> None:
        if not records:
            return
        self._collection.upsert(
            ids=[r["id"] for r in records],
            documents=[r["clause_text"] for r in records],
            metadatas=[
                {"clause_type": r["clause_type"], "raw_label": r.get("raw_label", ""), "domain": r.get("domain", "general")}
                for r in records
            ],
            embeddings=self._embedder.embed([r["clause_text"] for r in records]),
        )

    def query(self, text: str, k: int = DEFAULT_K) -> list[dict]:
        if self.count() == 0:
            return []
        raw = self._collection.query(query_embeddings=self._embedder.embed([text]), n_results=k)
        return [
            {"id": i, "text": d, "distance": dist, **m}
            for i, d, dist, m in zip(raw["ids"][0], raw["documents"][0], raw["distances"][0], raw["metadatas"][0])
        ]

    def query_many(self, texts: list[str], k: int = DEFAULT_K) -> list[list[dict]]:
        """Batched query() -- one embedding pass and one index call for many texts (evaluation)."""
        if self.count() == 0 or not texts:
            return [[] for _ in texts]
        raw = self._collection.query(query_embeddings=self._embedder.embed(texts), n_results=k)
        return [
            [{"id": i, "text": d, "distance": dist, **m} for i, d, dist, m in zip(ids, docs, dists, metas)]
            for ids, docs, dists, metas in zip(raw["ids"], raw["documents"], raw["distances"], raw["metadatas"])
        ]

    def reset(self) -> None:
        self._client.delete_collection(CLAUSE_COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=CLAUSE_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )


def vote(neighbours: list[dict], min_confidence: float = CLAUSE_TYPE_MIN_CONFIDENCE) -> dict:
    """
    Similarity-weighted kNN vote over precedent neighbours. Pure function
    (no index access) so it can be unit-tested and reused by the eval.
    Cosine distance d -> similarity (1 - d), floored at 0.
    """
    scores: dict[str, float] = defaultdict(float)
    for n in neighbours:
        scores[n["clause_type"]] += max(0.0, 1.0 - float(n["distance"]))

    total = sum(scores.values())
    if not total:
        return {"clause_type": None, "confidence": 0.0, "ranked": []}

    ranked = sorted(((t, s / total) for t, s in scores.items()), key=lambda x: -x[1])
    best_type, best_share = ranked[0]
    accepted = best_share >= min_confidence and best_type != OTHER
    return {
        "clause_type": best_type if accepted else None,
        "confidence": round(best_share, 4),
        "ranked": [(t, round(s, 4)) for t, s in ranked[:3]],
    }


def classify_clause_type(clause_text: str, k: int = DEFAULT_K) -> Optional[dict]:
    """
    Returns None when the precedent index hasn't been built (so the
    pipeline behaves exactly as before), otherwise:
        {clause_type, label, domain, confidence, statute_query, risk_prone,
         ranked: [(type, share), ...], precedents: [{id, clause_type, raw_label, similarity, snippet}]}
    clause_type is None when the vote is too split (or lands on "other").
    """
    classifier = ClauseClassifier.get()
    try:
        # With the trained classifier, the 63k-example index only supplies
        # "similar clause" snippets -- optional, so deployments can ship
        # without it (it's ~500 MB).
        index = ClauseIndex.get()
        neighbours = index.query(clause_text, k=k) if (index.count() or classifier is None) else []
    except Exception:
        if classifier is None:
            logger.exception("Clause-type lookup failed; continuing without a clause-type hint.")
            return None
        neighbours = []

    if classifier is not None:
        ranked = classifier.predict(clause_text)
        best_type, best_prob = ranked[0]
        accepted = best_prob >= CLAUSE_TYPE_MIN_CONFIDENCE and best_type != OTHER
        result = {
            "clause_type": best_type if accepted else None,
            "confidence": round(best_prob, 4),
            "ranked": [(t, round(p, 4)) for t, p in ranked[:3]],
            "method": "classifier",
        }
    elif not neighbours:
        return None
    else:
        result = {**vote(neighbours), "method": "knn"}
    clause_type = get_clause_type(result["clause_type"])
    return {
        **result,
        "label": clause_type.label if clause_type else None,
        "domain": clause_type.domain if clause_type else None,
        "statute_query": clause_type.statute_query if clause_type else None,
        "risk_prone": clause_type.risk_prone if clause_type else False,
        "precedents": [
            {
                "id": n["id"],
                "clause_type": n["clause_type"],
                "raw_label": n.get("raw_label", ""),
                "similarity": round(max(0.0, 1.0 - float(n["distance"])), 4),
                "snippet": n["text"][:240],
            }
            for n in neighbours[:3]
        ],
    }


def build_clause_index(corpus_path: Optional[Path] = None, reset: bool = False, limit: Optional[int] = None) -> int:
    corpus_path = corpus_path or CLAUSE_CORPUS_DIR / "train.jsonl"
    if not corpus_path.exists():
        logger.warning("No clause corpus at %s -- run scripts.build_clause_corpus first.", corpus_path)
        return 0

    index = ClauseIndex.get()
    if reset:
        index.reset()

    batch, total = [], 0
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            batch.append(json.loads(line))
            if len(batch) >= EMBED_BATCH_SIZE:
                index.add(batch)
                total += len(batch)
                batch = []
                if total % (EMBED_BATCH_SIZE * 20) == 0:
                    logger.info("Indexed %d precedent clauses", total)
            if limit and total + len(batch) >= limit:
                break
    index.add(batch)
    total += len(batch)
    logger.info("Clause precedent index: %d clauses", index.count())
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_clause_index(reset=True)
