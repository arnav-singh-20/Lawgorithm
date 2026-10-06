from backend.validation.citation_validator import validate_citations, find_invalid_citations


def test_valid_citation_passes():
    claims = [{"claim": "X", "supporting_source_ids": ["ica_1872_section_27"]}]
    retrieved = {"ica_1872_section_27", "ica_1872_section_74"}
    assert validate_citations(claims, retrieved) is True


def test_fabricated_citation_fails():
    claims = [{"claim": "X", "supporting_source_ids": ["ica_1872_section_999"]}]
    retrieved = {"ica_1872_section_27"}
    assert validate_citations(claims, retrieved) is False


def test_empty_claims_list_is_valid():
    assert validate_citations([], {"ica_1872_section_27"}) is True


def test_claim_with_no_sources_is_valid_for_citation_check():
    # Citation validator only checks fabrication, not whether a claim
    # has any support at all -- that's grounding validation's job.
    claims = [{"claim": "X", "supporting_source_ids": []}]
    assert validate_citations(claims, {"ica_1872_section_27"}) is True


def test_find_invalid_citations_reports_the_offender():
    claims = [{"claim": "Bad claim", "supporting_source_ids": ["fake_section"]}]
    retrieved = {"ica_1872_section_27"}
    invalid = find_invalid_citations(claims, retrieved)
    assert len(invalid) == 1
    assert invalid[0]["invalid_source_id"] == "fake_section"
