"""L4 sector clustering: deterministic assignment, ranking, explainability."""

from __future__ import annotations

from forge.clustering import ClusterInput, cluster_assets
from forge.config import SectorsConfig, load_sectors_config

CONFIG = load_sectors_config("config/sectors.yaml")


def inp(aid, text, score=None, title=None):
    return ClusterInput(asset_id=aid, title=title or aid, text=text, ventureability=score)


def test_assets_are_grouped_into_matching_sectors():
    result = cluster_assets(
        [
            inp("a", "a photonic optical waveguide interconnect", 0.8),
            inp("b", "an edge ai inference accelerator semiconductor", 0.6),
            inp("c", "green hydrogen electrolyser and fuel cell", 0.4),
        ],
        CONFIG,
    )
    assignment = result.assignment()
    assert assignment["a"] == "photonics"
    assert assignment["b"] == "ai_semiconductors"
    assert assignment["c"] == "green_energy"


def test_membership_records_matched_terms():
    result = cluster_assets([inp("a", "silicon photonics optical modulator")], CONFIG)
    member = result.sector("photonics").members[0]
    assert "photonics" in member.matched_terms and "optical" in member.matched_terms


def test_best_sector_wins_on_term_count():
    # More photonics terms than AI terms -> photonics.
    result = cluster_assets(
        [inp("a", "photonic optical waveguide interconnect for an accelerator")], CONFIG
    )
    assert result.assignment()["a"] == "photonics"


def test_unmatched_asset_is_unclassified():
    result = cluster_assets([inp("a", "a wooden chair with four legs")], CONFIG)
    assert result.assignment()["a"] == "unclassified"
    assert result.sector("unclassified").members[0].matched_terms == []


def test_members_ranked_by_ventureability_desc_within_sector():
    result = cluster_assets(
        [
            inp("low", "photonic optical interconnect", 0.30),
            inp("high", "photonic waveguide modulator", 0.90),
            inp("none", "photonics", None),
        ],
        CONFIG,
    )
    members = [m.asset_id for m in result.sector("photonics").members]
    assert members == ["high", "low", "none"]  # scored desc, then None last


def test_empty_sectors_are_omitted_and_summary_reads():
    result = cluster_assets([inp("a", "photonic optical interconnect", 0.8)], CONFIG)
    ids = [c.sector_id for c in result.clusters]
    assert ids == ["photonics"]  # only the non-empty sector
    assert "Integrated photonics" in result.summary()


def test_min_terms_is_config_driven():
    one_term = ClusterInput("a", "a", "this mentions optical only", 0.5)
    # Default min_terms=1 -> assigned to photonics.
    assert cluster_assets([one_term], CONFIG).assignment()["a"] == "photonics"

    strict = SectorsConfig(sectors=CONFIG.sectors, min_terms=2)
    # Needs >=2 matched terms now -> a single 'optical' match is unclassified.
    assert cluster_assets([one_term], strict).assignment()["a"] == "unclassified"


def test_mean_score_over_scored_members():
    result = cluster_assets(
        [
            inp("a", "photonic optical", 0.8),
            inp("b", "photonic waveguide", 0.4),
            inp("c", "photonics", None),  # None excluded from the mean
        ],
        CONFIG,
    )
    assert abs(result.sector("photonics").mean_score - 0.6) < 1e-9
