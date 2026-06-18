"""Document ingestion: text extraction, patent/result classification, fields."""

from __future__ import annotations

import pytest

from forge.db.models import AssetType
from forge.documents import (
    DocumentError,
    classify_document,
    extract_fields,
    extract_text,
    parse_document,
)

PATENT_TEXT = """United States Patent
(54) Title of Invention: Solid-state lithium battery with sulfide electrolyte
(73) Assignee: Example Research Institute
(57) Abstract
A solid-state lithium battery reduces dendrite formation at high current density.
The cell improves cycle life for stationary grid storage.

What is claimed is:
1. A battery cell comprising a sulfide glass electrolyte and a lithium-stabilising
additive arranged between a cathode and an anode.
"""

RESULT_TEXT = """Deliverable D3.2 — Work Package 3
A scalable enzymatic process for depolymerising mixed plastic waste

Abstract
This paper presents an enzymatic process that depolymerises mixed plastic waste
into reusable monomers at moderate temperature.

Introduction
Mechanical recycling degrades polymer quality over cycles.

References
[1] doi:10.1000/example.2021
"""


def test_classifies_patent_with_reasons():
    c = classify_document(PATENT_TEXT)
    assert c.asset_type is AssetType.patent
    assert c.label == "patent"
    assert any("claim" in r or "INID" in r or "patent" in r for r in c.reasons)


def test_classifies_unpatented_result():
    c = classify_document(RESULT_TEXT)
    assert c.asset_type is AssetType.project_result
    assert c.label == "unpatented result"
    assert c.reasons  # explains why (deliverable / DOI / references)


def test_extract_fields_from_patent():
    fields = extract_fields(PATENT_TEXT, AssetType.patent)
    assert "lithium" in fields["title"].lower()
    assert "dendrite" in fields["abstract"].lower()
    assert "sulfide glass electrolyte" in fields["claims_or_description"].lower()


def test_title_strips_patent_front_page_boilerplate():
    # A messy USPTO front-page text layer (INID codes, applicant, CPC run together).
    messy = (
        "NANOSCALE SCANNING SENSORS @ ( 71 ) Applicant : PRESIDENT AND FELLOWS OF "
        "HARVARD COLLEGE , Cambridge , MA ( US ) ( 52 ) U . S . Cl . CPC ..... G01Q\n"
        "(57) Abstract\nA nanoscale sensor detects magnetic fields.\n"
    )
    fields = extract_fields(messy, AssetType.patent)
    assert fields["title"] == "NANOSCALE SCANNING SENSORS"
    assert "Applicant" not in fields["title"] and "(" not in fields["title"]


def test_extract_fields_from_result():
    fields = extract_fields(RESULT_TEXT, AssetType.project_result)
    assert "abstract" in fields
    assert "enzymatic" in (fields.get("title", "") + fields["abstract"]).lower()


def test_parse_plain_text_patent():
    parsed = parse_document("patent.txt", PATENT_TEXT.encode("utf-8"))
    assert parsed.asset_type is AssetType.patent
    assert parsed.fields["title"]
    assert parsed.char_count > 0


def test_extract_text_decodes_plain_bytes():
    assert "hello" in extract_text("notes.txt", b"hello world").lower()


def test_parse_empty_document_raises():
    with pytest.raises(DocumentError):
        parse_document("empty.txt", b"   ")


def test_parse_real_pdf_patent():
    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in PATENT_TEXT.splitlines():
        pdf.cell(0, 6, line[:90], new_x="LMARGIN", new_y="NEXT")
    raw = bytes(pdf.output())

    parsed = parse_document("patent.pdf", raw)
    assert parsed.asset_type is AssetType.patent
    assert parsed.fields  # extracted at least one field from the PDF text layer
