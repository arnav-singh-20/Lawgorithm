from backend.ingestion.cleaner import clean_text


def test_removes_page_numbers():
    text = "4. NON-COMPETE\n\nThe Employee shall not compete.\n\nPage 3\n\n5. TERMINATION"
    cleaned = clean_text(text)
    assert "Page 3" not in cleaned
    assert "4. NON-COMPETE" in cleaned
    assert "5. TERMINATION" in cleaned


def test_removes_repeated_headers():
    header = "CONFIDENTIAL - ACME CORP EMPLOYMENT AGREEMENT"
    text = "\n".join([header, "1. DEFINITIONS", "Some text.", header, "2. TERM", "More text.", header])
    cleaned = clean_text(text)
    assert cleaned.count(header) == 0


def test_keeps_clause_headers_on_own_line():
    text = "4. NON-COMPETE\nThe Employee shall not\nengage in competing work."
    cleaned = clean_text(text)
    lines = cleaned.split("\n")
    assert any(line.strip() == "4. NON-COMPETE" for line in lines)
