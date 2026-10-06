"""
Real retrieval (Phase 7) -- the direct replacement for version1.py's

    MOCK_LEGAL_CORPUS + search_legal_reference(query)

Same function name and same "returns a string the LLM can read"
contract, so agent/tools.py barely has to change, but now backed by
the actual vector store instead of a keyword dict.
"""

import re
from typing import Optional

from backend.rag.chunking import PROVENANCE_FIELDS
from backend.rag.vector_store import LegalVectorStore


def search_legal_reference(query: str, domain: Optional[str] = None, top_k: int = 3) -> str:
    """
    Returns a formatted string of the top-k matching statutory sections,
    for direct use as a tool result fed back to the LLM.
    """
    results = search_legal_reference_structured(query, domain=domain, top_k=top_k)

    if not results:
        return "No matching statute found in the reference corpus for this query."

    return format_results(results, query)


CANDIDATES = 20
RRF_K = 60


def search_legal_reference_structured(
    query: str, domain: Optional[str] = None, top_k: int = 3
) -> list[dict]:
    """
    Hybrid retrieval (Phase 5): embedding search + BM25 keyword search over
    the statute library, merged with reciprocal rank fusion. Returns
    structured metadata (law, section, title, text, distance) for callers
    that store/display grounding -- the agent tool, the API, evaluation.
    """
    store = LegalVectorStore.get()
    query_embedding = store.embed_query(query)
    raw = store._collection.query(query_embeddings=[query_embedding], n_results=CANDIDATES)

    rows: dict[str, dict] = {}
    vector_rank: dict[str, int] = {}
    ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
    for rank, (source_id, doc, meta, dist) in enumerate(zip(
            ids, raw.get("documents", [[]])[0], raw.get("metadatas", [[]])[0],
            raw.get("distances", [[]])[0] if raw.get("distances") else [None] * len(ids))):
        rows[source_id] = {"id": source_id, "document": doc, "metadata": meta, "distance": dist}
        vector_rank[source_id] = rank

    keyword_rank: dict[str, int] = {}
    try:
        from backend.rag.keyword_index import BM25Index

        for rank, (source_id, _score) in enumerate(BM25Index.get().search(query, top_k=CANDIDATES)):
            keyword_rank[source_id] = rank
    except Exception:
        pass   # keyword index unavailable: plain vector search still works

    missing = [i for i in keyword_rank if i not in rows]
    for row in store.get_with_distances(missing, query_embedding):
        rows[row["id"]] = row

    def fused(source_id: str) -> float:
        score = 0.0
        if source_id in vector_rank:
            score += 1.0 / (RRF_K + vector_rank[source_id])
        if source_id in keyword_rank:
            score += 1.0 / (RRF_K + keyword_rank[source_id])
        return score

    ranked = sorted(rows, key=fused, reverse=True)[:top_k]
    results = []
    for source_id in ranked:
        row = rows[source_id]
        meta = row["metadata"] or {}
        results.append(
            {
                "id": source_id,
                "law": meta.get("law"),
                "section": meta.get("section"),
                "title": meta.get("title"),
                "domain": meta.get("domain"),
                "topics": (meta.get("topics") or "").split(",") if meta.get("topics") else [],
                "jurisdiction": meta.get("jurisdiction", "India"),
                "verified": bool(meta.get("verified", True)),
                "source_type": meta.get("source_type", "statute"),
                **{field: meta.get(field, "") for field in PROVENANCE_FIELDS},
                "text": row["document"],
                "distance": row["distance"],
            }
        )
    return results


# What the model gets per source. Long sections (TPA s.108, definitions)
# run to thousands of characters; three of them per search, over three
# searches, exceeded Groq's free-tier request size (8k tokens/min).
EXCERPT_CHARS = 1500


def excerpt(text: str, query: str = "", max_chars: int = EXCERPT_CHARS) -> str:
    """
    The section's opening (title + first lines) plus its paragraphs that
    share the most words with the query, kept in their original order and
    marked "[...]" where text was skipped. Short sections pass through.
    """
    if len(text) <= max_chars:
        return text
    from backend.rag.keyword_index import tokenize

    parts = [p.strip() for p in re.split(r"\n+|(?=\(\w{1,4}\)\s)", text) if p.strip()]
    wanted = set(tokenize(query))
    scored = sorted(range(1, len(parts)), key=lambda i: -len(wanted & set(tokenize(parts[i]))))
    keep, used = {0}, len(parts[0])
    for i in scored:
        if used + len(parts[i]) > max_chars:
            continue
        keep.add(i)
        used += len(parts[i])
    out, last = [], -1
    for i in sorted(keep):
        if i != last + 1:
            out.append("[...]")
        out.append(parts[i])
        last = i
    if last != len(parts) - 1:
        out.append("[...]")
    return " ".join(out)[: max_chars + 200]


def format_results(results: list[dict], query: str = "", max_chars: int = EXCERPT_CHARS) -> str:
    blocks = []
    for r in results:
        blocks.append(
            f"[source_id: {r['id']}] {r['law']}, Section {r['section']} ({r.get('title', '')}):\n"
            f"{excerpt(r['text'], query, max_chars)}"
        )
    return "\n\n---\n\n".join(blocks)


def best_retrieval_score(results: list[dict]) -> float:
    """
    Turns the closest (lowest-distance) match into a 0-1 relevance
    score for the confidence engine. `1 / (1 + distance)` is a simple
    monotonic transform (distance 0 -> score 1, larger distance -> score
    approaches 0) -- not a calibrated probability, just a reasonable
    stand-in until Phase 17 calibration replaces it with something
    tuned against real accuracy data.
    """
    distances = [r["distance"] for r in results if r.get("distance") is not None]
    if not distances:
        return 0.0

    best_distance = min(distances)
    return 1.0 / (1.0 + best_distance)
