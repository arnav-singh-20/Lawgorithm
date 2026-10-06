"""BM25 half of hybrid retrieval: exact legal phrases must rank."""

from backend.rag.keyword_index import BM25Index, tokenize

CHUNKS = [
    {"id": "ica_27", "title": "Agreement in restraint of trade, void",
     "text": "Every agreement by which any one is restrained from exercising a lawful profession, trade or business is void."},
    {"id": "ica_74", "title": "Compensation for breach of contract where penalty stipulated for",
     "text": "When a contract has been broken, if a sum is named in the contract as the amount to be paid in case of such breach..."},
    {"id": "tpa_106", "title": "Duration of certain leases in absence of written contract",
     "text": "A lease of immoveable property for residential purposes shall be deemed to be a lease from month to month."},
]


def test_terms_of_art_rank_first():
    index = BM25Index(CHUNKS)
    assert index.search("non-compete restraint of trade")[0][0] == "ica_27"
    assert index.search("penalty for breach")[0][0] == "ica_74"
    assert index.search("month to month residential lease")[0][0] == "tpa_106"


def test_no_overlap_returns_nothing():
    assert BM25Index(CHUNKS).search("zebra quantum") == []


def test_stopwords_dropped():
    assert tokenize("The tenant shall pay the rent") == ["tenant", "pay", "rent"]


def test_excerpt_keeps_opening_and_relevant_paragraphs():
    from backend.rag.retrieval import excerpt

    text = "Rights of lessee.—Preamble line.\n" + "\n".join(f"({i}) filler clause about drainage number {i}." for i in range(80)) \
        + "\n(z) the lessee must give fifteen days notice before vacating the premises."
    out = excerpt(text, "notice before vacating", max_chars=400)
    assert out.startswith("Rights of lessee.")
    assert "fifteen days notice before vacating" in out
    assert "[...]" in out and len(out) < 650
    assert excerpt("short section", "anything") == "short section"
