"""Config loading + validation (rules 2 & 3): weights/thresholds are checked config."""

from __future__ import annotations

import textwrap

import pytest

from forge.config import (
    VENTUREABILITY_DIMENSIONS,
    ConfigError,
    load_connectors_config,
    load_corroboration_config,
    load_dormancy_config,
    load_llm_config,
    load_organisation_config,
    load_recalibration_config,
    load_scoring_config,
    load_sectors_config,
    load_streams_config,
    load_taxonomy_config,
)

REPO_SCORING = "config/scoring.yaml"
REPO_DORMANCY = "config/dormancy.yaml"
REPO_CONNECTORS = "config/connectors.yaml"
REPO_ORGANISATION = "config/organisation.yaml"
REPO_LLM = "config/llm.yaml"
REPO_STREAMS = "config/streams.yaml"
REPO_TAXONOMY = "config/taxonomy.yaml"
REPO_CORROBORATION = "config/corroboration.yaml"
REPO_RECALIBRATION = "config/recalibration.yaml"
REPO_SECTORS = "config/sectors.yaml"


def test_repo_scoring_config_is_valid():
    cfg = load_scoring_config(REPO_SCORING)
    assert set(cfg.weights) == set(VENTUREABILITY_DIMENSIONS)
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9


def test_scoring_scaling_is_loaded():
    cfg = load_scoring_config(REPO_SCORING)
    assert cfg.scaling["citation_saturation"] == 5
    assert cfg.scaling["neighbour_crowded"] == 100


def test_scoring_min_coverage_loads_and_defaults(tmp_path):
    assert 0.0 <= load_scoring_config(REPO_SCORING).min_coverage <= 1.0
    # Absent -> sensible default.
    p = tmp_path / "scoring.yaml"
    p.write_text(
        "weights:\n  technology_maturity: 0.2\n  market_pull: 0.25\n"
        "  ip_defensibility: 0.2\n  capital_intensity: 0.1\n"
        "  regulatory_pathway: 0.1\n  team_availability: 0.15\n"
    )
    assert load_scoring_config(p).min_coverage == 0.5


def test_scoring_min_coverage_out_of_range_rejected(tmp_path):
    p = tmp_path / "scoring.yaml"
    p.write_text(
        "min_coverage: 1.5\nweights:\n  technology_maturity: 0.2\n  market_pull: 0.25\n"
        "  ip_defensibility: 0.2\n  capital_intensity: 0.1\n"
        "  regulatory_pathway: 0.1\n  team_availability: 0.15\n"
    )
    with pytest.raises(ConfigError, match="min_coverage"):
        load_scoring_config(p)


def test_scoring_scaling_must_be_mapping(tmp_path):
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: 0.2
          market_pull: 0.25
          ip_defensibility: 0.2
          capital_intensity: 0.1
          regulatory_pathway: 0.1
          team_availability: 0.15
        scaling: 5
        """,
    )
    with pytest.raises(ConfigError, match="scaling"):
        load_scoring_config(p)


def test_repo_dormancy_config_is_valid():
    cfg = load_dormancy_config(REPO_DORMANCY)
    assert cfg.patents["min_age_years"] == 3
    assert cfg.project_results["max_years_since_end"] == 5
    assert "encumbrance_clear_values" in cfg.signals


def test_repo_organisation_config_is_valid():
    org = load_organisation_config(REPO_ORGANISATION)
    assert org.matches("synthetic research org")  # case-insensitive
    assert org.matches("SRO")
    assert not org.matches("Some Other Company")
    assert not org.matches(None)


def test_organisation_requires_identifiers(tmp_path):
    p = tmp_path / "organisation.yaml"
    p.write_text("organisation:\n  name: X\n")
    with pytest.raises(ConfigError, match="identifiers"):
        load_organisation_config(p)


def test_dormancy_signals_must_be_mapping(tmp_path):
    p = tmp_path / "dormancy.yaml"
    p.write_text("patents: {}\nproject_results: {}\nsignals: [1, 2]\n")
    with pytest.raises(ConfigError, match="signals"):
        load_dormancy_config(p)


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_scoring_config(tmp_path / "nope.yaml")


def test_weights_must_sum_to_one(tmp_path):
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: 0.5
          market_pull: 0.5
          ip_defensibility: 0.5
          capital_intensity: 0.5
          regulatory_pathway: 0.5
          team_availability: 0.5
        """,
    )
    with pytest.raises(ConfigError, match="sum to 1.0"):
        load_scoring_config(p)


def test_unknown_dimension_rejected(tmp_path):
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: 0.2
          market_pull: 0.2
          ip_defensibility: 0.2
          capital_intensity: 0.1
          regulatory_pathway: 0.1
          team_availability: 0.1
          buzzword_factor: 0.1
        """,
    )
    with pytest.raises(ConfigError, match="unknown"):
        load_scoring_config(p)


def test_missing_dimension_rejected(tmp_path):
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: 0.4
          market_pull: 0.3
          ip_defensibility: 0.2
          capital_intensity: 0.1
        """,
    )
    with pytest.raises(ConfigError, match="missing"):
        load_scoring_config(p)


def test_negative_weight_rejected(tmp_path):
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: -0.1
          market_pull: 0.35
          ip_defensibility: 0.25
          capital_intensity: 0.2
          regulatory_pathway: 0.2
          team_availability: 0.1
        """,
    )
    with pytest.raises(ConfigError, match="non-negative"):
        load_scoring_config(p)


def test_boolean_weight_rejected(tmp_path):
    # YAML 'true' would coerce to 1 numerically; we must reject bools explicitly.
    p = _write(
        tmp_path,
        "scoring.yaml",
        """
        weights:
          technology_maturity: true
          market_pull: 0.0
          ip_defensibility: 0.0
          capital_intensity: 0.0
          regulatory_pathway: 0.0
          team_availability: 0.0
        """,
    )
    with pytest.raises(ConfigError, match="must be a number"):
        load_scoring_config(p)


def test_dormancy_missing_section_rejected(tmp_path):
    p = _write(tmp_path, "dormancy.yaml", "patents: {min_age_years: 3}\n")
    with pytest.raises(ConfigError, match="project_results"):
        load_dormancy_config(p)


def test_repo_connectors_config_is_valid():
    cfg = load_connectors_config(REPO_CONNECTORS)
    epo = cfg.section("epo_ops")
    assert epo["base_url"].startswith("http")
    assert epo["auth_url"].startswith("http")


def test_connectors_missing_epo_section_rejected(tmp_path):
    p = _write(tmp_path, "connectors.yaml", "something_else: {}\n")
    with pytest.raises(ConfigError, match="epo_ops"):
        load_connectors_config(p)


def test_connectors_missing_required_url_rejected(tmp_path):
    p = _write(tmp_path, "connectors.yaml", "epo_ops:\n  reference_format: epodoc\n")
    with pytest.raises(ConfigError, match="base_url"):
        load_connectors_config(p)


def test_unknown_connector_section_lookup_raises():
    cfg = load_connectors_config(REPO_CONNECTORS)
    with pytest.raises(ConfigError, match="no connector config section"):
        cfg.section("does_not_exist")


def test_repo_llm_config_is_valid():
    cfg = load_llm_config(REPO_LLM)
    assert cfg.provider == "anthropic"
    assert cfg.model.startswith("claude-")  # a real Claude model (Haiku for low-cost demo)
    assert cfg.max_tokens > 0


def test_llm_config_requires_model(tmp_path):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: anthropic\n")
    with pytest.raises(ConfigError, match="model"):
        load_llm_config(p)


def test_llm_config_rejects_nonpositive_max_tokens(tmp_path):
    p = tmp_path / "llm.yaml"
    p.write_text("model: claude-opus-4-8\nmax_tokens: 0\n")
    with pytest.raises(ConfigError, match="positive"):
        load_llm_config(p)


def test_repo_streams_config_is_valid():
    cfg = load_streams_config(REPO_STREAMS)
    s2 = cfg.section("s2_patents")
    assert s2["filing_window_years"] >= 1
    assert s2["max_neighbours"] >= 1
    assert cfg.section("s3_roadmaps")["corpus_path"]


def test_streams_missing_s3_section_rejected(tmp_path):
    p = tmp_path / "streams.yaml"
    p.write_text("s2_patents: {filing_window_years: 5, max_neighbours: 10}\n")
    with pytest.raises(ConfigError, match="s3_roadmaps"):
        load_streams_config(p)


def test_streams_missing_s1_section_rejected(tmp_path):
    p = tmp_path / "streams.yaml"
    p.write_text(
        "s2_patents: {filing_window_years: 5, max_neighbours: 10}\n"
        "s3_roadmaps: {corpus_path: data/s3_corpus.jsonl}\n"
    )
    with pytest.raises(ConfigError, match="s1_funding"):
        load_streams_config(p)


def test_repo_streams_has_s1_funding():
    cfg = load_streams_config(REPO_STREAMS)
    assert cfg.section("s1_funding")["funding_window_years"] >= 1


def test_streams_missing_s2_section_rejected(tmp_path):
    p = tmp_path / "streams.yaml"
    p.write_text("something_else: {}\n")
    with pytest.raises(ConfigError, match="s2_patents"):
        load_streams_config(p)


def test_repo_taxonomy_config_is_valid():
    cfg = load_taxonomy_config(REPO_TAXONOMY)
    assert {"green", "digital", "critical_tech"} <= set(cfg.categories)
    assert cfg.strong_match_count >= 1
    assert "photonic" in cfg.categories["digital"]["terms"]


def test_taxonomy_rejects_category_without_terms(tmp_path):
    p = tmp_path / "taxonomy.yaml"
    p.write_text("eu_taxonomy:\n  categories:\n    green:\n      label: Green\n")
    with pytest.raises(ConfigError, match="non-empty 'terms'"):
        load_taxonomy_config(p)


def test_taxonomy_requires_categories(tmp_path):
    p = tmp_path / "taxonomy.yaml"
    p.write_text("eu_taxonomy:\n  strong_match_count: 3\n")
    with pytest.raises(ConfigError, match="categories"):
        load_taxonomy_config(p)


def test_repo_corroboration_config_is_valid():
    cfg = load_corroboration_config(REPO_CORROBORATION)
    assert cfg.indicator("field_crowding")["crowded_min"] >= 1
    assert cfg.indicator("market_pull")["strong_min"] >= 1


def test_corroboration_missing_indicator_rejected(tmp_path):
    p = tmp_path / "corroboration.yaml"
    p.write_text("indicators:\n  field_momentum: {rising_min_slope: 1, declining_max_slope: -1}\n")
    with pytest.raises(ConfigError, match="industry_attention"):
        load_corroboration_config(p)


def test_repo_recalibration_config_is_valid():
    cfg = load_recalibration_config(REPO_RECALIBRATION)
    assert "spun_out" in cfg.good_outcomes
    assert "abandoned" in cfg.bad_outcomes
    assert cfg.min_sample >= 1 and cfg.min_separation > 0
    assert cfg.outcome_quality["spun_out"] == 1.0


def test_recalibration_requires_outcome_lists(tmp_path):
    p = tmp_path / "recalibration.yaml"
    p.write_text("outcome_quality:\n  spun_out: 1.0\ngood_outcomes: [spun_out]\n")
    with pytest.raises(ConfigError, match="bad_outcomes"):
        load_recalibration_config(p)


def test_repo_sectors_config_is_valid():
    cfg = load_sectors_config(REPO_SECTORS)
    ids = [s.id for s in cfg.sectors]
    assert "photonics" in ids and len(ids) == len(set(ids))
    assert cfg.min_terms >= 1


def test_sectors_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "sectors.yaml"
    p.write_text(
        "sectors:\n"
        "  - {id: x, terms: [a]}\n"
        "  - {id: x, terms: [b]}\n"
    )
    with pytest.raises(ConfigError, match="duplicate sector id"):
        load_sectors_config(p)


def test_sectors_rejects_empty_terms(tmp_path):
    p = tmp_path / "sectors.yaml"
    p.write_text("sectors:\n  - {id: x, label: X}\n")
    with pytest.raises(ConfigError, match="non-empty 'terms'"):
        load_sectors_config(p)
