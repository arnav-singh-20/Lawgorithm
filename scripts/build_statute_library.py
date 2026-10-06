"""
Build the Indian statute library (data/statutes/*.json) from source text.

Source: the "geekyrakshit/indian-legal-acts" dataset on Hugging Face --
full text of 883 Central Acts converted from the official India Code PDFs,
each row carrying the official PDF link (kept as `official_source` on
every section). Reproducing Acts is permitted under s.52(1)(q) of the
Copyright Act, 1957.

Only Acts relevant to employment and rental contracts are imported, and
repealed laws are left out on purpose: the four Labour Codes came into
force on 21 Nov 2025 and replaced 29 central labour Acts (Payment of
Wages, Gratuity, Industrial Disputes, Standing Orders, Maternity Benefit,
Minimum Wages, EPF, ...). Citing those now would be wrong.

    python -m scripts.build_statute_library            # writes data/statutes/*.json
    python -m backend.rag.ingest_laws                  # then re-index

Every section gets provenance: official_source (India Code PDF URL),
source_version ("<dataset>@<revision>"), last_verified (build date --
meaning "text checked against the source on", NOT "a lawyer reviewed
it"; verified=false until a person does).
"""

import datetime
import json
import re
from pathlib import Path

from backend.config import STATUTES_DIR

SOURCE_DIR = Path("data/sources/indian-legal-acts/data")
DATASET = "huggingface.co/datasets/geekyrakshit/indian-legal-acts"

# short title in the dataset -> (canonical law name, domain, topics)
ACTS = {
    "The Indian Contract Act, 1872": ("Indian Contract Act, 1872", "contract", ["contract"]),
    "The Transfer of Property Act, 1882": ("Transfer of Property Act, 1882", "rental", ["lease", "property"]),
    "The Registration Act, 1908": ("Registration Act, 1908", "rental", ["registration", "lease"]),
    "The Indian Stamp Act, 1899": ("Indian Stamp Act, 1899", "rental", ["stamp duty"]),
    "The Specific Relief Act, 1963": ("Specific Relief Act, 1963", "contract", ["remedies", "possession"]),
    "The Limitation Act, 1963": ("Limitation Act, 1963", "contract", ["limitation"]),
    "The Arbitration and Conciliation Act, 1996": ("Arbitration and Conciliation Act, 1996", "contract", ["arbitration", "disputes"]),
    "The delhi rent control act, 1958": ("Delhi Rent Control Act, 1958", "rental", ["rent", "eviction", "tenancy"]),
    "The Code on Wages, 2019": ("Code on Wages, 2019", "employment", ["wages", "bonus", "deductions"]),
    "The Code on Social Security, 2020": ("Code on Social Security, 2020", "employment", ["gratuity", "provident fund", "maternity"]),
    "The Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013": (
        "Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013", "employment", ["posh"]),
    "The Copyright Act, 1957": ("Copyright Act, 1957", "employment", ["intellectual property", "work for hire"]),
    "The Information Technology Act, 2000": ("Information Technology Act, 2000", "contract", ["electronic records", "e-signature"]),
    "The Negotiable Instruments Act, 1881": ("Negotiable Instruments Act, 1881", "rental", ["cheque", "post-dated cheque"]),
    "The Consumer Protection Act, 2019": ("Consumer Protection Act, 2019", "contract", ["unfair contract"]),
    "The Apprentices Act, 1961": ("Apprentices Act, 1961", "employment", ["apprentice"]),
    "The Rights of Persons with Disabilities Act, 2016.": ("Rights of Persons with Disabilities Act, 2016", "employment", ["equal opportunity"]),
}

# "**27. Title.—body" / "**28.Title" / "**[29A. Title" / "**1[2. Title"
# at the start of a line, bold. The table of contents isn't bold.
# A footnote marker is digits immediately followed by "[" ("1[27A."); without
# requiring the "[", the optional digits swallowed "2" of "27".
# Two forms: bold "**27. Title" sections, and sections inserted/substituted
# by amendment, which carry a footnote marker and are often NOT bold:
# "1[106. Duration of certain leases...". The table of contents has neither.
SECTION_START = re.compile(
    r"^(?:\*\*\s*(?:\d+\s*\[|\[)?|\d+\s*\[)\s*(\d{1,3}[A-Z]{0,3})\s*\.\s*(?=[A-Z\[*])", re.MULTILINE)
FOOTNOTE_JUNK = re.compile(r"^\s*\d*\*?\s*(?:-\s*){2,}\*?\s*\.?\s*$", re.MULTILINE)


def _clean(text: str) -> str:
    text = text.replace("**", "")
    text = FOOTNOTE_JUNK.sub("", text)
    text = re.sub(r"(?<=\S)\n(?=[a-z(])", " ", text)        # re-join lines broken mid-sentence
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _split_title(head: str) -> tuple[str, str]:
    """'Agreement in restraint of trade, void.—Every agreement...' -> (title, body)."""
    m = re.match(r"(.{3,220}?)\s*\.?\s*[—–]\s*(.*)", head, re.S)
    if not m:
        first = head.split("\n", 1)
        return first[0].strip(" .*"), (first[1] if len(first) > 1 else "").strip()
    return m.group(1).strip(" .*[]"), m.group(2).strip()


def _toc_numbers(markdown: str) -> set[int]:
    head = markdown[: max(3000, len(markdown) // 6)]
    return {int(n) for n in re.findall(r"^\s*(\d{1,3})[A-Z]{0,3}\s*\.\s+[A-Z]", head, re.MULTILINE)}


def parse_sections(markdown: str) -> list[dict]:
    starts = list(SECTION_START.finditer(markdown))
    toc = _toc_numbers(markdown)
    # numbers far past the Act's own table of contents are footnotes/schedules
    limit = max(toc) + 5 if len(toc) >= 10 else 10_000
    sections, seen = [], set()
    for i, m in enumerate(starts):
        number = m.group(1)
        if int(re.match(r"\d+", number).group()) > limit:
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else len(markdown)
        title, body = _split_title(_clean(markdown[m.end():end]))
        if number in seen or not body or len(body) < 15:
            continue   # duplicates (schedules re-using numbers) and empty stubs
        seen.add(number)
        repealed = bool(re.match(r"^\[?\s*(repealed|omitted)", title + " " + body[:30], re.I))
        sections.append({"section": number, "title": title, "text": f"{title}.—{body}"[:6000],
                         "repealed": repealed})
    return sections


def toc_count(markdown: str) -> int:
    """Section entries in the Act's own 'ARRANGEMENT OF SECTIONS' (sanity check)."""
    head = markdown[: max(3000, len(markdown) // 6)]
    return len(set(re.findall(r"^\s*(\d{1,3}[A-Z]{0,3})\s*\.\s+[A-Z]", head, re.MULTILINE)))


# Acts not in the dataset, parsed from the Gazette text (PDFs as passed by
# Parliament, hosted by PRS Legislative Research). official_source points
# at India Code's copy of the same Act.
PDF_ACTS = {
    "data/sources/pdfs/ir_code_2020.pdf": (
        "Industrial Relations Code, 2020", "employment", ["termination", "retrenchment", "standing orders", "disputes"],
        "https://www.indiacode.nic.in/bitstream/123456789/22040/1/aa202035.pdf",
        "https://prsindia.org/files/bills_acts/acts_parliament/2020/Industrial%20Relations%20Code,%202020.pdf"),
    "data/sources/pdfs/osh_code_2020.pdf": (
        "Occupational Safety, Health and Working Conditions Code, 2020", "employment", ["working hours", "leave", "safety"],
        "https://prsindia.org/files/bills_acts/acts_parliament/2020/Occupational%20Safety,%20Health%20And%20Working%20Conditions%20Code,%202020.pdf",
        "https://prsindia.org/files/bills_acts/acts_parliament/2020/Occupational%20Safety,%20Health%20And%20Working%20Conditions%20Code,%202020.pdf"),
}


# State rent laws (Gazette PDFs hosted by PRS Legislative Research; the
# official India Code copy is linked as official_source). Scanned ones are
# OCR'd and marked verified=false -- OCR can misread words or numbers.
STATE_PDF_ACTS = {
    "data/sources/pdfs/karnataka_rent_1999.pdf": ("Karnataka Rent Act, 1999", "Karnataka",
        "https://www.indiacode.nic.in/bitstream/123456789/7810/1/34_of_2001_e.pdf",
        "https://prsindia.org/files/bills_acts/acts_states/karnataka/2001/2001KR34.pdf"),
    "data/sources/pdfs/tn_landlord_tenant_2017.pdf": (
        "Tamil Nadu Regulation of Rights and Responsibilities of Landlords and Tenants Act, 2017", "Tamil Nadu",
        "https://www.indiacode.nic.in/bitstream/123456789/13302/1/tnrrrlt-act_2017.pdf",
        "https://prsindia.org/files/bills_acts/acts_states/tamil-nadu/2017/2017TN42.pdf"),
    "data/sources/pdfs/wb_premises_tenancy_1997.pdf": ("West Bengal Premises Tenancy Act, 1997", "West Bengal",
        "https://www.indiacode.nic.in/bitstream/123456789/14542/1/1997-37.pdf",
        "https://prsindia.org/files/bills_acts/acts_states/west-bengal/1997/1997WB37.pdf"),
    "data/sources/pdfs/maharashtra_rent_1999.pdf": ("Maharashtra Rent Control Act, 1999", "Maharashtra",
        "https://www.indiacode.nic.in/bitstream/123456789/15817/3/eng_maharashtra_rent_control_ac.pdf",
        "https://prsindia.org/files/bills_acts/acts_states/maharashtra/2000/2000MH18.pdf"),
    "data/sources/pdfs/up_urban_tenancy_2021.pdf": ("Uttar Pradesh Regulation of Urban Premises Tenancy Act, 2021", "Uttar Pradesh",
        "https://www.indiacode.nic.in/bitstream/123456789/21157/1/english_16_of_2021.pdf",
        "https://prsindia.org/files/bills_acts/acts_states/uttar-pradesh/2021/Act%20No%2016%20of%202021%20UP.pdf"),
}

# State Acts available in the dataset's state splits.
STATE_DATASET_ACTS = {
    ("andhra_pradesh", "The Andhra Pradesh Shops and Establishments Act, 1988."): (
        "Andhra Pradesh Shops and Establishments Act, 1988", "Andhra Pradesh", "employment",
        ["working hours", "leave", "termination"]),
}


def pdf_text(path: str) -> str:
    """Text layer if there is one; otherwise OCR (scanned Gazettes), cached next to the PDF."""
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    if len(text.strip()) > 2000:
        return text
    cache = Path(path).with_suffix(".ocr.txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    import pytesseract
    from pdf2image import convert_from_path

    pages = convert_from_path(path, dpi=300)
    text = "\n".join(pytesseract.image_to_string(page, config="--psm 6") for page in pages)
    cache.write_text(text, encoding="utf-8")
    return text


def parse_gazette_pdf(path: str) -> list[dict]:
    """
    Gazette layout: titles only in the ARRANGEMENT OF SECTIONS, bodies start
    with a bare "70. " at the beginning of a line. Accept a body start only
    when its number follows the previous one (numbered lists inside a
    section and schedule items would otherwise split sections).
    """
    text = pdf_text(path)
    ocr = Path(path).with_suffix(".ocr.txt").exists()
    body_at = text.find("may be called")
    body_at = text.rfind("\n1.", 0, body_at) if body_at > 0 else 0
    toc, body = text[:body_at], text[body_at:]

    # entries are sometimes glued together: "8. Rent payable.9. Revision of rent."
    toc = re.sub(r"\.\s*(\d{1,3}[A-Z]?\.\s)", r".\n\1", toc)
    titles = {}
    for m in re.finditer(r"^\s*(\d{1,3}[A-Z]?)\.\s+(.+?)(?=\n\s*\d{1,3}[A-Z]?\.\s|\n\s*CHAPTER|\Z)", toc, re.M | re.S):
        titles.setdefault(m.group(1), re.sub(r"\s+", " ", m.group(2)).strip(" ."))

    starts, expected = [], 1
    # "11. (1) ..." and also "11.(1) ..." / "11.Title" (no space after the dot)
    # OCR'd scans add stray marks before the number ("e 14. (", "_ 24.") and
    # read "." as ","; the in-order check below keeps that from misfiring.
    start_re = (r"^[^\w\n]{0,3}(?:[a-z]\s)?\s*(\d{1,3})([A-Z]?)\s*[.,]\s*(?=[\(\[A-Z\u201c\"])" if ocr
                else r"^\s*(\d{1,3})([A-Z]?)\.\s*(?=[\(\[A-Z\u201c\"])")
    for m in re.finditer(start_re, body, re.M):
        n = int(m.group(1))
        # allow omitted/renumbered gaps (and, for OCR, a section number the
        # scan made unreadable) without letting a stray "45." jump ahead
        if expected <= n <= expected + (6 if ocr else 2):
            starts.append((m.start(), m.end(), m.group(1) + m.group(2)))
            expected = n + 1
    sections = []
    for i, (start, head_end, number) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        chunk = body[head_end:end]
        title = titles.get(number, "")
        if title:
            chunk = chunk.replace(title, " ")          # drop the side-note echo of the title
        chunk = re.sub(r"(?<=\S)\n(?=[a-z(])", " ", chunk)
        chunk = re.sub(r"[ \t]+", " ", chunk).strip()
        if len(chunk) >= 15:
            sections.append({"section": number, "title": title, "text": f"{title}.—{chunk}"[:6000] if title else chunk[:6000]})
    return sections


def build() -> dict:
    import pyarrow.parquet as pq

    rows = {r["Short Title"]: r for r in pq.read_table(SOURCE_DIR / "central-00000-of-00001.parquet").to_pylist()}
    today = datetime.date.today().isoformat()
    report, statutes = {}, []
    for title, (law, domain, topics) in ACTS.items():
        row = rows.get(title)
        if row is None:
            report[law] = "missing from source"
            continue
        sections = [s for s in parse_sections(row["Markdown"] or "") if not s.pop("repealed")]
        for s in sections:
            s.update({
                "domain": domain,
                "jurisdiction": "Delhi" if law.startswith("Delhi") else "India",
                "topics": topics,
                # text from the official digital text layer (not OCR); "verified"
                # means that -- NOT that a lawyer has reviewed it
                "verified": True,
                "source_type": "statute",
                "official_source": row["View"],
                "source_version": f"{DATASET} (India Code PDF text)",
                "last_verified": today,
            })
        statutes.append({"law": law, "sections": sections})
        report[law] = {"sections": len(sections), "toc": toc_count(row["Markdown"] or "")}

    for path, (law, domain, topics, official, fetched_from) in PDF_ACTS.items():
        if not Path(path).exists():
            report[law] = "PDF not downloaded"
            continue
        sections = parse_gazette_pdf(path)
        for s in sections:
            s.update({"domain": domain, "jurisdiction": "India", "topics": topics,
                      "verified": not Path(path).with_suffix(".ocr.txt").exists(),
                      "source_type": "statute", "official_source": official,
                      "source_version": f"Gazette text via {fetched_from}", "last_verified": today})
        statutes.append({"law": law, "sections": sections})
        report[law] = {"sections": len(sections)}

    for path, (law, state, official, fetched_from) in STATE_PDF_ACTS.items():
        if not Path(path).exists():
            report[law] = "PDF not downloaded"
            continue
        ocr = Path(path).with_suffix(".ocr.txt")
        sections = parse_gazette_pdf(path)
        for s in sections:
            s.update({"domain": "rental", "jurisdiction": state, "topics": ["rent", "tenancy", "eviction"],
                      "verified": not ocr.exists(), "source_type": "statute", "official_source": official,
                      "source_version": ("OCR of scanned Gazette via " if ocr.exists() else "Gazette text via ") + fetched_from,
                      "last_verified": today})
        statutes.append({"law": law, "sections": sections})
        report[law] = {"sections": len(sections), "ocr": ocr.exists()}

    for (split, title), (law, state, domain, topics) in STATE_DATASET_ACTS.items():
        rows_state = {r["Short Title"]: r for r in pq.read_table(SOURCE_DIR / f"{split}-00000-of-00001.parquet").to_pylist()}
        row = rows_state.get(title)
        if row is None:
            report[law] = "missing from source"
            continue
        sections = [s for s in parse_sections(row["Markdown"] or "") if not s.pop("repealed")]
        for s in sections:
            s.update({"domain": domain, "jurisdiction": state, "topics": topics, "verified": True,
                      "source_type": "statute", "official_source": row["View"],
                      "source_version": f"{DATASET} (India Code PDF text)", "last_verified": today})
        statutes.append({"law": law, "sections": sections})
        report[law] = {"sections": len(sections)}

    STATUTES_DIR.mkdir(parents=True, exist_ok=True)
    out = STATUTES_DIR / "indian_statutes.json"
    out.write_text(json.dumps({"_source": DATASET, "_built": today, "statutes": statutes},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    for law, info in build().items():
        print(f"{law[:70]:70s} {info}")
