from backend.rag.chunking import chunk_statute, make_chunk_id


def test_chunk_id_is_slugified():
    chunk_id = make_chunk_id("Indian Contract Act, 1872", "27")
    assert chunk_id == "indian_contract_act__1872_section_27"


def test_chunk_statute_preserves_metadata():
    sections = [
        {"section": "27", "title": "Restraint of trade", "domain": "employment", "text": "Every agreement..."}
    ]
    chunks = chunk_statute("Indian Contract Act, 1872", sections)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["law"] == "Indian Contract Act, 1872"
    assert chunk["section"] == "27"
    assert chunk["domain"] == "employment"
    assert chunk["jurisdiction"] == "India"
    assert chunk["topics"] == ["employment"]  # defaults to [domain] when unset
    assert chunk["verified"] is True
    assert chunk["source_type"] == "statute"
    assert "Every agreement" in chunk["text"]


def test_chunk_statute_honors_explicit_topics_and_verification():
    sections = [
        {
            "section": "27",
            "domain": "employment",
            "text": "...",
            "topics": ["non_compete", "restraint_of_trade"],
            "verified": False,
        }
    ]
    chunk = chunk_statute("Indian Contract Act, 1872", sections)[0]
    assert chunk["topics"] == ["non_compete", "restraint_of_trade"]
    assert chunk["verified"] is False
