"""Parsing CORDIS result JSON (E10) — tolerant, degrades over missing fields."""

from __future__ import annotations

from pathlib import Path

from forge.connectors.cordis import parse_results
from forge.connectors.cordis.parser import parse_project

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_single_result_lifts_all_fields():
    [r] = parse_results((FIXTURES / "cordis_result_single.json").read_bytes())
    assert r.result_id == "464190"
    assert r.title.startswith("Photonic neuromorphic")
    assert r.abstract.startswith("A low-power photonic")
    assert r.description.startswith("Key Exploitable Result")
    assert r.owners == ["SYNTHETIC RESEARCH ORG", "SYNTHETIC UNIVERSITY"]
    assert r.end_date == "2022-09-30"
    assert r.project_id == "101001234"
    assert r.project_acronym == "PHOTON-EDGE"
    assert "photonics" in r.keywords


def test_parse_multi_normalises_date_and_string_keywords():
    results = parse_results((FIXTURES / "cordis_results_multi.json").read_bytes())
    assert len(results) == 2  # both objects parsed (empty one filtered by the connector)
    first = results[0]
    assert first.end_date == "2021-12-31"  # ISO date trimmed from a timestamp
    assert first.owners == ["SYNTHETIC MATERIALS INSTITUTE"]  # bare-string org
    assert first.keywords == ["batteries", "materials characterisation", "solid-state"]


def test_parse_handles_a_bare_list_and_missing_pieces():
    results = parse_results(b'[{"id": "1", "title": "Only a title"}]')
    assert len(results) == 1
    r = results[0]
    assert r.title == "Only a title"
    assert r.owners == [] and r.end_date is None and r.description is None


def test_parse_project_lifts_orgs_and_flags_industrial():
    project = parse_project((FIXTURES / "cordis_project_single.json").read_bytes())
    assert project.project_id == "101001234"
    assert project.acronym == "PHOTON-EDGE"
    assert project.start_date == "2019-01-01" and project.end_date == "2022-12-31"
    assert len(project.organizations) == 4

    industrial = [o for o in project.organizations if o.is_industrial]
    assert {o.name for o in industrial} == {"Aurora Photonics GmbH", "Borealis Systems S.p.A."}
    aurora = next(o for o in industrial if o.name.startswith("Aurora"))
    assert aurora.is_sme and aurora.registry_id == "999900003" and aurora.country == "DE"
    university = next(o for o in project.organizations if o.activity_type == "HES")
    assert not university.is_industrial
