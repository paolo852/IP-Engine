"""T10: company entity-resolution key — legal-suffix stripping, spelling variants."""

from __future__ import annotations

from forge.graph import normalize_company_name


def test_strips_legal_suffixes_and_punctuation():
    assert normalize_company_name("Aurora Photonics GmbH") == "aurora photonics"
    assert normalize_company_name("Borealis Systems S.p.A.") == "borealis systems"
    assert normalize_company_name("Acme, Inc.") == "acme"
    assert normalize_company_name("The Widget Company") == "widget"


def test_dotted_and_undotted_suffix_variants_collapse():
    # The same firm written two ways resolves to the same key (name-only match).
    assert normalize_company_name("Aurora Photonics G.m.b.H.") == normalize_company_name(
        "Aurora Photonics GmbH"
    )


def test_all_suffix_name_falls_back_rather_than_emptying():
    assert normalize_company_name("Ltd") == "ltd"


def test_blank_is_empty():
    assert normalize_company_name("") == ""
    assert normalize_company_name("   ") == ""
