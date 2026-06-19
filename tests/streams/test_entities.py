"""E4: deterministic, config-driven citing-entity classification."""

from __future__ import annotations

from forge.streams.entities import (
    ACADEMIC,
    CORPORATE,
    OTHER,
    classify_entity,
    markers_from_config,
)


def test_corporate_names_are_classified_corporate():
    for name in ["Acme Corp", "Siemens AG", "Nokia Oyj Technologies",
                 "BrightPhotonics GmbH", "Acme Inc.", "TSMC Co., Ltd."]:
        assert classify_entity(name) == CORPORATE, name


def test_academic_names_are_classified_academic():
    for name in ["Stanford University", "Fraunhofer-Gesellschaft",
                 "Politecnico di Milano", "CNRS", "Massachusetts Institute of Technology",
                 "Max Planck Society"]:
        assert classify_entity(name) == ACADEMIC, name


def test_word_boundary_avoids_false_positives():
    # "inc" must not match inside "Increment"; "co" not inside "Cobalt".
    assert classify_entity("Increment Labs") == OTHER
    assert classify_entity("Cobalt Research Studio") == OTHER


def test_academic_wins_over_corporate_for_mixed_names():
    # A university-owned vehicle reads as academic lineage (the conservative call).
    assert classify_entity("University of Tokyo Holdings") == ACADEMIC


def test_blank_or_missing_is_other():
    assert classify_entity(None) == OTHER
    assert classify_entity("   ") == OTHER


def test_markers_are_config_driven():
    cfg = {"entity_classification": {"academic_markers": ["spinlab"],
                                     "corporate_markers": ["widgetworks"]}}
    academic, corporate = markers_from_config(cfg)
    assert classify_entity("Acme SpinLab", academic_markers=academic,
                           corporate_markers=corporate) == ACADEMIC
    assert classify_entity("Acme WidgetWorks", academic_markers=academic,
                           corporate_markers=corporate) == CORPORATE
    # A default-corporate token is no longer corporate under the narrowed config.
    assert classify_entity("Acme GmbH", academic_markers=academic,
                           corporate_markers=corporate) == OTHER


def test_markers_from_config_falls_back_to_defaults():
    academic, corporate = markers_from_config({})
    assert "university" in academic and "gmbh" in corporate
