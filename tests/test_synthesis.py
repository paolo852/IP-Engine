"""Decision-oriented synthesis: build, persistence, pipeline wiring, web display."""

from __future__ import annotations

import json
from datetime import date

from forge.db.models import AssetSynthesis
from forge.llm.provider import LLMResponse
from forge.output.synthesis import SynthesisInputs, build_synthesis
from forge.repository import (
    delete_synthesis,
    get_synthesis,
    save_asset,
    save_synthesis,
)
from forge.scoring import DimensionScore, VentureabilityScore
from forge.seed import OfflineProfilingProvider

from .synthetic.assets import synthetic_patent_bundle

AS_OF = date(2026, 6, 18)

_SYNTH_JSON = json.dumps(
    {
        "recommendation": "License to an instrument maker",
        "summary": "Mature quantum-sensing IP with three plausible measurement markets; "
        "capital-intensive, no tracked funding nearby — fits licensing over spin-out.",
        "open_questions": [
            "Is the resolution gain a real advantage over incumbent tools, and who pays?",
            "Which of the three markets has the nearest buyer?",
        ],
    }
)


class FakeSynthesisProvider:
    model = "fake-synth"

    def __init__(self, text: str = _SYNTH_JSON) -> None:
        self._text = text

    def complete(self, system, user, *, json_schema=None, max_tokens=None) -> LLMResponse:
        return LLMResponse(text=self._text, model=self.model)


class SchemaAwareProvider:
    """Profiles offline (grounded from the asset) but answers synthesis as JSON."""

    model = "fake-aware"

    def __init__(self) -> None:
        self._offline = OfflineProfilingProvider()

    def complete(self, system, user, *, json_schema=None, max_tokens=None) -> LLMResponse:
        props = (json_schema or {}).get("properties", {})
        if "recommendation" in props:
            return LLMResponse(text=_SYNTH_JSON, model=self.model)
        return self._offline.complete(system, user, json_schema=json_schema, max_tokens=max_tokens)


def _score():
    dims = [DimensionScore("market_pull", 0.4, "two roadmap matches")]
    return VentureabilityScore(0.5, 0.6, dims, {"market_pull": 1.0})


def _inputs():
    bundle = synthetic_patent_bundle()
    return SynthesisInputs(asset=bundle.asset, score=_score())


# -- build ------------------------------------------------------------------
def test_build_synthesis_from_signals():
    s = build_synthesis(_inputs(), FakeSynthesisProvider())
    assert s is not None
    assert s.recommendation.startswith("License")
    assert len(s.open_questions) == 2
    assert s.model == "fake-synth"
    assert any("SCORE" in line for line in s.basis)  # derived from engine signals


def test_build_synthesis_none_without_signals():
    bundle = synthetic_patent_bundle()
    # Only the title line -> nothing to synthesise.
    assert build_synthesis(SynthesisInputs(asset=bundle.asset), FakeSynthesisProvider()) is None


def test_build_synthesis_none_on_unparseable_provider():
    # The offline provider returns profiling JSON, not synthesis JSON -> None.
    assert build_synthesis(_inputs(), OfflineProfilingProvider()) is None


# -- persistence ------------------------------------------------------------
def test_save_get_delete_synthesis(session):
    asset = save_asset(session, synthetic_patent_bundle())
    s = build_synthesis(_inputs(), FakeSynthesisProvider())
    save_synthesis(session, asset, s)

    row = get_synthesis(session, asset.id)
    assert row is not None
    assert row.recommendation.startswith("License")
    assert isinstance(row.open_questions, list) and len(row.open_questions) == 2

    delete_synthesis(session, asset.id)
    assert get_synthesis(session, asset.id) is None


def test_save_synthesis_is_idempotent(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_synthesis(session, asset, build_synthesis(_inputs(), FakeSynthesisProvider()))
    save_synthesis(session, asset, build_synthesis(_inputs(), FakeSynthesisProvider()))
    rows = session.query(AssetSynthesis).filter(AssetSynthesis.asset_id == asset.id).all()
    assert len(rows) == 1


# -- pipeline integration ---------------------------------------------------
def test_pipeline_persists_synthesis_with_capable_llm(session):
    from forge.pipeline import Pipeline, PipelineConfig

    asset = save_asset(session, synthetic_patent_bundle())
    Pipeline(PipelineConfig.from_files(as_of=AS_OF), SchemaAwareProvider()).run(
        session, [asset.id]
    )
    row = get_synthesis(session, asset.id)
    assert row is not None and row.recommendation


def test_pipeline_skips_synthesis_offline(session):
    from forge.pipeline import Pipeline, PipelineConfig

    asset = save_asset(session, synthetic_patent_bundle())
    Pipeline(PipelineConfig.from_files(as_of=AS_OF), OfflineProfilingProvider()).run(
        session, [asset.id]
    )
    # Offline provider can't synthesise -> no synthesis row, but scoring still ran.
    assert get_synthesis(session, asset.id) is None
