"""DPDP data minimisation: identifiers are removed, contract terms are not."""

from backend.privacy.redaction import redact

SAMPLE = """Tenant: Rahul, PAN ABCDE1234F, Aadhaar 2345 6789 0123, phone +91 98765 43210,
email rahul.k@example.com. Rent Rs 25,000 payable to account 123456789012 (IFSC HDFC0001234).
Deposit Rs 2,50,000. Notice period 90 days. Lease from 1 November 2026 for 11 months.
Landline 080-41234567. GSTIN 29ABCDE1234F1Z5."""


def test_identifiers_are_removed():
    out, counts = redact(SAMPLE)
    for leaked in ["ABCDE1234F", "2345 6789 0123", "98765 43210", "rahul.k@example.com",
                   "123456789012", "HDFC0001234", "080-41234567", "29ABCDE1234F1Z5"]:
        assert leaked not in out, leaked
    assert counts["[PAN]"] == 1 and counts["[EMAIL]"] == 1 and counts["[PHONE]"] == 2


def test_contract_terms_survive():
    out, _ = redact(SAMPLE)
    for kept in ["Rs 25,000", "Rs 2,50,000", "90 days", "1 November 2026", "11 months", "Rahul"]:
        assert kept in out, kept


def test_plain_amounts_and_years_are_not_redacted():
    text = "Pay Rs 250000 by 2026. Penalty INR 500000. Section 27 of the Act, 1872."
    assert redact(text)[0] == text
