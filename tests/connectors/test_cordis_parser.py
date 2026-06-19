"""Parsing CORDIS result JSON (E10) — tolerant, degrades over missing fields."""

from __future__ import annotations

from pathlib import Path

from forge.connectors.cordis import parse_results

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
