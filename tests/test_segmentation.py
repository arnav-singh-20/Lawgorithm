from backend.segmentation.clause_segmenter import segment_clauses


def test_segments_numbered_clauses():
    text = (
        "1. DEFINITIONS\n"
        "In this agreement, 'Company' means Acme Pvt Ltd.\n\n"
        "2. NON-COMPETE\n"
        "The Employee shall not compete with the Company for 12 months.\n\n"
        "3. TERMINATION\n"
        "Either party may terminate with 30 days notice."
    )

    clauses = segment_clauses(text)

    assert len(clauses) == 3
    assert clauses[0]["clause_id"] == "1"
    assert clauses[0]["title"] == "DEFINITIONS"
    assert "Acme Pvt Ltd" in clauses[0]["text"]
    assert clauses[1]["title"] == "NON-COMPETE"
    assert clauses[2]["title"] == "TERMINATION"


def test_preamble_is_captured():
    text = "This agreement is made on 1 Jan 2026.\n\n1. TERM\nThe term is 2 years."
    clauses = segment_clauses(text)
    assert clauses[0]["clause_id"] == "0"
    assert clauses[0]["title"] == "PREAMBLE"
    assert clauses[1]["title"] == "TERM"


def test_no_headers_returns_full_document():
    text = "This is just a plain paragraph with no clause structure at all."
    clauses = segment_clauses(text)
    assert len(clauses) == 1
    assert clauses[0]["title"] == "FULL DOCUMENT"


def test_signature_block_is_not_a_clause():
    text = ("1. RENT\nThe Tenant shall pay Rs 28,000 per month.\n\n"
            "2. NOTICE\nEither party may give one month's notice.\n\n"
            "LANDLORD\nRamesh Kumar Gowda\n\nTENANT\nPriya Sharma\n")
    clauses = segment_clauses(text)
    real = [c["title"] for c in clauses if c.get("kind") != "signature"]
    assert real == ["RENT", "NOTICE"]
    assert any(c.get("kind") == "signature" for c in clauses)          # kept, not silently dropped
    # a real clause that happens to start with a party word is untouched
    assert all(c.get("kind") != "signature" for c in segment_clauses("1. LANDLORD'S OBLIGATIONS\nThe Landlord shall repair the roof.\n"))
