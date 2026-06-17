"""Config loading + validation (rules 2 & 3): weights/thresholds are checked config."""

from __future__ import annotations

import textwrap

import pytest

from forge.config import (
    VENTUREABILITY_DIMENSIONS,
    ConfigError,
    load_connectors_config,
    load_dormancy_config,
    load_llm_config,
    load_organisation_config,
    load_scoring_config,
)

REPO_SCORING = "config/scoring.yaml"
REPO_DORMANCY = "config/dormancy.yaml"
REPO_CONNECTORS = "config/connectors.yaml"
REPO_ORGANISATION = "config/organisation.yaml"
REPO_LLM = "config/llm.yaml"


def test_repo_scoring_config_is_valid():
    cfg = load_scoring_config(REPO_SCORING)
    assert set(cfg.weights) == set(VENTUREABILITY_DIMENSIONS)
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9


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
    assert cfg.model == "claude-opus-4-8"  # latest, most capable default
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
