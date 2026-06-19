"""Offline demo seeding — synthetic public assets, no credentials, no network.

This populates a database with a handful of SYNTHETIC patents (rule 4: invented,
public-style data only) and runs the pipeline against them using an *offline*
profiling provider, so the web demo has grounded, scored, corroborated assets to
show without an LLM key or any external API.

The offline provider is deliberately honest: it grounds every profile statement
in a verbatim span of the asset's own text (the same grounding contract the real
LLM must satisfy), so nothing fabricated reaches the store. Patents-only here, as
those carry a dormancy ruleset; S2/S1 (patents/funding) need live credentials and
are simply absent — the score reports its reduced coverage rather than inventing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Asset, AssetType, FieldProvenance, Licence, Source
from .llm.provider import LLMResponse
from .pipeline import Pipeline, PipelineConfig
from .repository import (
    AssetBundle,
    ProvenanceEntry,
    get_asset,
    get_score,
    save_asset,
)

# -- offline profiling provider --------------------------------------------
_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by", "from",
    "per", "into", "at", "as", "is", "are", "that", "this", "it", "its", "not",
    "synthetic", "invented", "real", "patent", "comprising", "method", "system",
}


def _parse_source_blob(user: str) -> dict[str, str]:
    """Recover {field -> text} from the profiling prompt's SOURCE block."""
    body = user.split("<<<", 1)[-1].rsplit(">>>", 1)[0]
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        marker = re.match(r"\[(\w+)\]\s*$", line.strip())
        if marker:
            current = marker.group(1)
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in fields.items()}


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.;])\s+", text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _keywords(text: str, limit: int = 4) -> list[str]:
    seen: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower()):
        if raw in _STOPWORDS or raw in seen:
            continue
        seen.append(raw)
        if len(seen) >= limit:
            break
    return seen


class OfflineProfilingProvider:
    """An ``LLMProvider`` that profiles from verbatim spans — no network, no LLM.

    It reads the SOURCE block, takes exact substrings for problem/solution/
    application quotes (so grounding verification passes), and derives query terms
    from keywords. Output matches the profiling JSON schema.
    """

    model = "offline-profiler-v1"

    def complete(self, system, user, *, json_schema=None, max_tokens=None) -> LLMResponse:
        fields = _parse_source_blob(user)
        abstract = fields.get("abstract", "")
        claims = fields.get("claims_or_description", "")
        title = fields.get("title", "")

        abstract_sents = _sentences(abstract)
        claims_sents = _sentences(claims)

        problem_quote = abstract_sents[0] if abstract_sents else (title or claims)
        solution_quote = (
            claims_sents[0]
            if claims_sents
            else (abstract_sents[-1] if abstract_sents else title)
        )
        app_quote = title or problem_quote

        terms = _keywords(f"{title} {abstract}")
        payload = {
            "technology_summary": title,
            "problem": {"value": problem_quote, "quote": problem_quote},
            "solution": {"value": solution_quote, "quote": solution_quote},
            # Offline can't invent markets, so the single application reuses the
            # asset's own terms as industry_terms (degraded placeholder, honest).
            "applications": [
                {"value": app_quote, "quote": app_quote, "industry_terms": terms}
            ],
            "query_terms": terms,
        }
        return LLMResponse(text=json.dumps(payload), model=self.model)


# -- synthetic demo assets (rule 4: invented, public-style) -----------------
@dataclass
class _Spec:
    locator: str
    title: str
    abstract: str
    claims: str
    inventors: list[str]
    owners: list[str]
    legal_status: str
    key_dates: dict
    fee_status: str


_DEMO_SPECS: list[_Spec] = [
    _Spec(
        locator="synthetic://demo/patent/EP-FAKE-1001",
        title="Low-power photonic interconnect for edge AI accelerators",
        abstract=(
            "A photonic interconnect architecture reduces inter-chip energy per bit "
            "for edge inference workloads. The design targets dense accelerator racks "
            "where electrical links dominate the power budget."
        ),
        claims=(
            "An interconnect comprising a micro-ring modulator array coupled to a "
            "silicon waveguide and a wavelength-division multiplexing controller. "
            "The controller balances optical channels to hold bit-error rate within a "
            "fixed bound."
        ),
        inventors=["A. Rossi", "B. Bianchi"],
        owners=["Synthetic Research Org"],
        legal_status="granted",
        key_dates={"priority_date": "2017-03-04", "filing_date": "2018-03-01",
                   "grant_date": "2021-06-21"},
        fee_status="lapsing",
    ),
    _Spec(
        locator="synthetic://demo/patent/EP-FAKE-1002",
        title="Solid-state electrolyte for long-life grid storage batteries",
        abstract=(
            "A solid-state electrolyte improves cycle life in stationary grid storage "
            "batteries. The formulation suppresses dendrite growth at high current "
            "density."
        ),
        claims=(
            "A solid electrolyte composition comprising a sulfide glass matrix and a "
            "lithium-stabilising additive. The composition maintains ionic conductivity "
            "across a wide temperature range."
        ),
        inventors=["C. Verdi", "D. Neri"],
        owners=["Synthetic Energy Institute"],
        legal_status="granted",
        key_dates={"priority_date": "2016-09-10", "filing_date": "2017-09-01",
                   "grant_date": "2020-11-12"},
        fee_status="lapsed",
    ),
    _Spec(
        locator="synthetic://demo/patent/EP-FAKE-1003",
        title="Soil-moisture sensing network for precision irrigation",
        abstract=(
            "A wireless soil-moisture sensing network schedules precision irrigation "
            "to cut water use in arid farmland. Nodes self-calibrate against local "
            "soil composition."
        ),
        claims=(
            "A sensing network comprising buried capacitive probes and a gateway that "
            "computes an irrigation schedule from a moisture gradient. The gateway "
            "defers watering when rainfall is forecast."
        ),
        inventors=["E. Galli"],
        owners=["Synthetic Agritech Lab"],
        legal_status="pending",
        key_dates={"priority_date": "2021-05-20", "filing_date": "2022-05-18"},
        fee_status="active",
    ),
    _Spec(
        locator="synthetic://demo/patent/EP-FAKE-1004",
        title="Enzymatic process for depolymerising mixed plastic waste",
        abstract=(
            "An enzymatic process depolymerises mixed plastic waste into reusable "
            "monomers at moderate temperature. The process tolerates contaminated "
            "feedstock without pre-sorting."
        ),
        claims=(
            "A process comprising contacting shredded polymer with an engineered "
            "hydrolase under controlled pH. The monomer stream is recovered by "
            "membrane separation."
        ),
        inventors=["F. Costa", "G. Marino"],
        owners=["Synthetic Materials Consortium"],
        legal_status="granted",
        key_dates={"priority_date": "2015-01-15", "filing_date": "2016-01-12",
                   "grant_date": "2019-04-09"},
        fee_status="lapsing",
    ),
]


def synthetic_demo_bundles() -> list[AssetBundle]:
    """Build the synthetic demo assets, each fully grounded (rule 1)."""
    bundles: list[AssetBundle] = []
    for spec in _DEMO_SPECS:
        src = Source(
            source_type="synthetic",
            licence=Licence.synthetic,
            locator=spec.locator,
            retrieved_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        asset = Asset(
            asset_type=AssetType.patent,
            source_layer="L1.synthetic",
            title=spec.title,
            abstract=spec.abstract,
            claims_or_description=spec.claims,
            inventors=spec.inventors,
            owners=spec.owners,
            legal_status=spec.legal_status,
            key_dates=spec.key_dates,
            fee_status=spec.fee_status,
            encumbrances="none recorded",
        )
        fields = [
            "title", "abstract", "claims_or_description", "inventors", "owners",
            "legal_status", "key_dates", "fee_status", "encumbrances",
        ]
        provenance = [
            ProvenanceEntry(field_name=f, source=src, note="synthetic demo")
            for f in fields
        ]
        bundles.append(AssetBundle(asset=asset, provenance=provenance))
    return bundles


def build_stream_clients(config_dir: str = "config"):
    """Build the optional cross-referencing stream clients from the environment.

    S3 (roadmaps) and S4 (taxonomy) always run offline and need nothing here. S2
    (EPO OPS patents) is a free source that needs an OAuth2 key; S1 (Dealroom
    funding) is licensed. Each activates only when its credential is present;
    absent or failing clients are skipped so one source never blocks the rest
    (rule 7). Returns ``(s2_client, s1_client)``, either of which may be None.
    """
    s2_client = s1_client = None
    if os.environ.get("FORGE_EPO_OPS_KEY"):
        try:
            from .config import load_connectors_config
            from .connectors.epo_ops import OpsClient, OpsSettings
            from .streams.s2_patents import OpsS2Client

            settings = OpsSettings.from_config(
                load_connectors_config(f"{config_dir}/connectors.yaml")
            )
            s2_client = OpsS2Client(OpsClient(settings))
        except Exception:  # noqa: BLE001 - S2 is optional; never block scoring
            s2_client = None
    if os.environ.get("FORGE_DEALROOM_API_KEY"):
        try:
            from .config import load_streams_config
            from .connectors.http import UrllibTransport
            from .streams.s1_funding import DealroomS1Client

            base_url = load_streams_config(f"{config_dir}/streams.yaml").section(
                "s1_funding"
            )["base_url"]
            s1_client = DealroomS1Client(UrllibTransport(), base_url=base_url)
        except Exception:  # noqa: BLE001 - S1 is optional/licensed
            s1_client = None
    return s2_client, s1_client


@dataclass
class SeedReport:
    created: int
    skipped: int
    scored: int
    errors: list[str]

    def summary(self) -> str:
        return (
            f"seed: {self.created} created, {self.skipped} already present, "
            f"{self.scored} scored, {len(self.errors)} errors"
        )


def seed_demo(
    session: Session,
    *,
    policy=None,
    as_of: date | None = None,
    run_pipeline: bool = True,
) -> SeedReport:
    """Insert the synthetic demo assets and (optionally) run the offline pipeline.

    Idempotent: an asset whose synthetic locator is already stored is skipped.
    Returns a report so the CLI can print what happened.
    """
    created = skipped = scored = 0
    errors: list[str] = []

    existing = {
        s.locator
        for s in session.query(Source).filter(Source.source_type == "synthetic")
    }
    new_ids = []
    for bundle in synthetic_demo_bundles():
        locator = bundle.provenance[0].source.locator
        if locator in existing:
            skipped += 1
            continue
        try:
            asset = save_asset(session, bundle, policy=policy)
            created += 1
            new_ids.append(asset.id)
        except Exception as exc:  # noqa: BLE001 - report, don't abort the batch
            session.rollback()
            errors.append(f"{locator}: {exc}")

    # Self-healing: score the assets just created PLUS any demo asset left
    # unscored by an earlier partial run (e.g. a deploy that created rows but
    # crashed before scoring). Idempotent — already-scored assets are skipped.
    to_score = list(new_ids)
    demo_locators = [b.provenance[0].source.locator for b in synthetic_demo_bundles()]
    existing_demo_ids = session.execute(
        select(FieldProvenance.asset_id)
        .join(Source, FieldProvenance.source_id == Source.id)
        .where(Source.locator.in_(demo_locators))
        .distinct()
    ).scalars()
    for aid in existing_demo_ids:
        if aid not in to_score and get_score(session, aid) is None:
            to_score.append(aid)

    if run_pipeline and to_score:
        config = PipelineConfig.from_files(as_of=as_of)
        s2_client, s1_client = build_stream_clients()
        pipe = Pipeline(
            config,
            OfflineProfilingProvider(),
            s2_client=s2_client,
            s1_client=s1_client,
        )
        report = pipe.run(session, to_score)
        for r in report.results:
            if r.score is not None:
                scored += 1
            errors.extend(f"{r.asset_id}: {e}" for e in r.errors)

    return SeedReport(created=created, skipped=skipped, scored=scored, errors=errors)
