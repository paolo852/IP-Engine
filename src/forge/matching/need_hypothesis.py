"""Need-hypothesis generator (T11) — the four-step chain, falsifiable output.

For an asset's candidate applications and the companies in the Relationship Graph,
produce FALSIFIABLE need hypotheses:

  1. capability -> value: the application's industry framing (producer vocabulary)
     and its end-customer/use-case framing (customer vocabulary);
  2. value -> sector need-types: the market terms those framings expand to;
  3. company + signals -> specific hypothesis: a graph company is matched by shared
     market terms, assigned a track (customer vs producer), given a strength from
     the convergence of graph tie + shared-term depth + a corroborating market
     signal, and phrased as a testable sentence;
  4. validation happens later — nothing here is a need (rule 4). Every sentence
     carries the "unvalidated" guard and names the test that would confirm/deny it.

Deterministic and grounded: each hypothesis records the evidence it was derived
from. No LLM is required; phrasing is config-driven (rule 3).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from ..config import NeedsConfig
from ..db.models import Company, Strength, Track

MODEL = "needgen-v1"

_STOP = frozenset(
    {
        "the", "and", "for", "with", "from", "into", "this", "that", "una", "che",
        "per", "gmbh", "ltd", "inc", "srl", "spa", "system", "systems", "solution",
        "solutions", "technology", "technologies", "based", "using", "via",
    }
)


def _tokens(text: str | None) -> set[str]:
    """Meaningful lower-case tokens (length >= 3, minus stopwords)."""
    if not text:
        return set()
    raw = re.split(r"[^a-z0-9]+", text.lower())
    return {t for t in raw if len(t) >= 3 and t not in _STOP}


def _app_customer_terms(app: dict) -> set[str]:
    return _tokens(app.get("end_customer")) | _tokens(app.get("use_case")) | _tokens(
        app.get("application")
    )


def _app_producer_terms(app: dict) -> set[str]:
    terms: set[str] = set()
    for t in app.get("industry_terms") or []:
        terms |= _tokens(t)
    return terms


def customer_terms(applications: list[dict]) -> set[str]:
    out: set[str] = set()
    for app in applications:
        out |= _app_customer_terms(app)
    return out


def producer_terms(applications: list[dict], technology_summary: str | None) -> set[str]:
    out = _tokens(technology_summary)
    for app in applications:
        out |= _app_producer_terms(app)
    return out


def company_terms(company: Company) -> set[str]:
    """The market vocabulary a company exposes: its name, sector, and graph topics."""
    out = _tokens(company.name) | _tokens(company.sector)
    for rel in company.relationships:
        out |= _tokens(rel.topic)
    return out


_ORDER = (Strength.weak, Strength.medium, Strength.strong)


def _base_strength(company: Company) -> Strength:
    """The company's strongest graph tie sets the baseline convergence level."""
    levels = [_ORDER.index(rel.strength) for rel in company.relationships]
    return _ORDER[max(levels)] if levels else Strength.weak


def strength_of(base: Strength, shared_count: int, *, market_signal: bool, cfg: NeedsConfig) -> Strength:
    level = _ORDER.index(base)
    if shared_count >= cfg.strengthen_shared_terms:
        level += 1
    if market_signal:
        level += 1
    return _ORDER[min(level, len(_ORDER) - 1)]


@dataclass
class NeedHypothesisDraft:
    company_id: uuid.UUID
    track: Track
    hypothesised_need: str
    strength: Strength
    evidence: list[dict] = field(default_factory=list)
    rationale: str = ""
    model: str = MODEL


def _best_application(applications: list[dict], shared: set[str], *, producer: bool) -> dict | None:
    """The candidate application whose framing overlaps the shared terms most."""
    best, best_n = None, -1
    for app in applications:
        terms = _app_producer_terms(app) if producer else _app_customer_terms(app)
        n = len(terms & shared)
        if n > best_n:
            best, best_n = app, n
    return best


def _sentence(cfg: NeedsConfig, template: str, company: Company, application: dict) -> str:
    label = application.get("application") or "this application"
    context = application.get("use_case") or "their operations"
    body = template.format(company=company.name, application=label, context=context)
    return f"{cfg.prefix} {body}"


def generate(
    *,
    applications: list[dict],
    technology_summary: str | None,
    companies: list[Company],
    market_signal: bool,
    cfg: NeedsConfig,
) -> list[NeedHypothesisDraft]:
    """Produce falsifiable need-hypothesis drafts for the matching graph companies.

    ``applications`` is the profile's ``candidate_applications`` (list of dicts).
    ``market_signal`` is whether the asset has any corroborating cross-stream
    evidence (raises hypothesis strength). Companies with no shared market term are
    not hypothesised — an ungrounded match would be a guess, not a hypothesis.
    """
    cust = customer_terms(applications)
    prod = producer_terms(applications, technology_summary)
    drafts: list[NeedHypothesisDraft] = []

    for company in companies:
        cterms = company_terms(company)
        cust_shared = cterms & cust
        prod_shared = cterms & prod
        if max(len(cust_shared), len(prod_shared)) < cfg.min_shared_terms:
            continue

        # Track = whichever side the company's vocabulary overlaps more (ties ->
        # producer: an adjacent maker is the more actionable licensing route).
        producer_track = len(prod_shared) >= len(cust_shared)
        track = Track.producer if producer_track else Track.customer
        shared = prod_shared if producer_track else cust_shared
        template = cfg.producer_template if producer_track else cfg.customer_template

        application = _best_application(applications, shared, producer=producer_track)
        if application is None:
            continue

        strength = strength_of(
            _base_strength(company), len(shared), market_signal=market_signal, cfg=cfg
        )
        ties = sorted({rel.type.value for rel in company.relationships})
        evidence = [
            {"kind": "graph", "ref": rel.source_ref, "detail": f"{rel.type.value}: {rel.topic}"}
            for rel in company.relationships
        ]
        evidence.append(
            {"kind": "shared_terms", "ref": None, "detail": ", ".join(sorted(shared))}
        )
        if market_signal:
            evidence.append(
                {"kind": "market_signal", "ref": None, "detail": "corroborating cross-stream evidence present"}
            )
        rationale = (
            f"Matched via the relationship graph on shared market term(s) "
            f"[{', '.join(sorted(shared))}]; graph tie(s): {', '.join(ties) or 'none'}; "
            f"{'a corroborating market signal is present' if market_signal else 'no corroborating market signal yet'}. "
            f"This is a hypothesis to be tested with the company, not a known need."
        )
        drafts.append(
            NeedHypothesisDraft(
                company_id=company.id,
                track=track,
                hypothesised_need=_sentence(cfg, template, company, application),
                strength=strength,
                evidence=evidence,
                rationale=rationale,
            )
        )
    return drafts
