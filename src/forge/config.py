"""Externalised configuration loading (non-negotiable rules 2 & 3).

Dormancy thresholds and scoring weights live in YAML, never as hard-coded
constants. These loaders read + validate that config so later slices can depend
on a stable, checked shape. Validation here is deliberate: a typo in a weight
must fail loudly, not silently skew a score.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The six ventureability dimensions. The set is fixed by the scoring rubric; the
# *weights* are configuration. Keeping the names here lets config validation
# reject unknown/missing dimensions.
VENTUREABILITY_DIMENSIONS = (
    "technology_maturity",
    "market_pull",
    "ip_defensibility",
    "capital_intensity",
    "regulatory_pathway",
    "team_availability",
)

_WEIGHT_SUM_TOLERANCE = 1e-6


class ConfigError(ValueError):
    """Raised when externalised config is missing, malformed, or invalid."""


def _read_yaml(path: str | os.PathLike[str]) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough of parser msg
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping in {p}")
    return data


@dataclass(frozen=True)
class ScoringConfig:
    """Validated ventureability weights. Immutable once loaded."""

    weights: dict[str, float]

    def weight(self, dimension: str) -> float:
        return self.weights[dimension]


def load_scoring_config(path: str | os.PathLike[str]) -> ScoringConfig:
    """Load + validate scoring weights.

    Enforces: exactly the six known dimensions are present, every weight is a
    non-negative number, and the weights sum to 1.0. A black-box would hide this;
    a transparent function must not.
    """
    data = _read_yaml(path)
    raw = data.get("weights")
    if not isinstance(raw, dict):
        raise ConfigError("scoring config must have a 'weights' mapping")

    keys = set(raw)
    expected = set(VENTUREABILITY_DIMENSIONS)
    if keys != expected:
        missing = expected - keys
        unknown = keys - expected
        problems = []
        if missing:
            problems.append(f"missing {sorted(missing)}")
        if unknown:
            problems.append(f"unknown {sorted(unknown)}")
        raise ConfigError("scoring weights " + "; ".join(problems))

    weights: dict[str, float] = {}
    for dim in VENTUREABILITY_DIMENSIONS:
        value = raw[dim]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"weight for {dim!r} must be a number, got {value!r}")
        if value < 0:
            raise ConfigError(f"weight for {dim!r} must be non-negative")
        weights[dim] = float(value)

    total = math.fsum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ConfigError(f"scoring weights must sum to 1.0, got {total:g}")

    return ScoringConfig(weights=weights)


@dataclass(frozen=True)
class DormancyConfig:
    """Validated dormancy thresholds + signal definitions for each asset family.

    ``signals`` holds the (also configurable) markers the L4 rules use to derive
    boolean facts from asset fields — e.g. which ``encumbrances`` values count as
    "clear". Keeping these in config means no thresholds or magic strings live in
    the rule code (rule 3).
    """

    patents: dict
    project_results: dict
    signals: dict = field(default_factory=dict)


def load_dormancy_config(path: str | os.PathLike[str]) -> DormancyConfig:
    """Load dormancy thresholds. Shape-validated; semantics consumed by L4 rules."""
    data = _read_yaml(path)
    for section in ("patents", "project_results"):
        if not isinstance(data.get(section), dict):
            raise ConfigError(f"dormancy config must have a '{section}' mapping")
    signals = data.get("signals", {})
    if not isinstance(signals, dict):
        raise ConfigError("dormancy 'signals' must be a mapping if present")
    return DormancyConfig(
        patents=data["patents"],
        project_results=data["project_results"],
        signals=signals,
    )


@dataclass(frozen=True)
class OrganisationConfig:
    """Our organisation's identity — used by the dormancy ownership check.

    Identifiers are the name variants that count as "us" when matching an asset's
    owners/co-owners. Config, not code: who "we" are is never hard-coded.
    """

    name: str
    identifiers: tuple[str, ...]

    def matches(self, party: str | None) -> bool:
        if not party:
            return False
        needle = party.strip().lower()
        return any(needle == ident.strip().lower() for ident in self.identifiers)


def load_organisation_config(path: str | os.PathLike[str]) -> OrganisationConfig:
    """Load the organisation identity used by ownership-based rules."""
    data = _read_yaml(path)
    org = data.get("organisation")
    if not isinstance(org, dict):
        raise ConfigError("organisation config must have an 'organisation' mapping")
    identifiers = org.get("identifiers") or []
    if not isinstance(identifiers, list) or not identifiers:
        raise ConfigError("organisation config needs a non-empty 'identifiers' list")
    name = org.get("name") or identifiers[0]
    return OrganisationConfig(name=str(name), identifiers=tuple(str(i) for i in identifiers))


@dataclass(frozen=True)
class ConnectorsConfig:
    """Validated connector settings (endpoints, formats, throttle). No secrets."""

    sections: dict

    def section(self, name: str) -> dict:
        if name not in self.sections:
            raise ConfigError(f"no connector config section named {name!r}")
        return self.sections[name]


def load_connectors_config(path: str | os.PathLike[str]) -> ConnectorsConfig:
    """Load + lightly validate connector settings.

    Endpoints live in config (rule 3); credentials never do. Each known section
    must carry the URLs its connector needs so failures surface at load time, not
    mid-ingestion.
    """
    data = _read_yaml(path)
    epo = data.get("epo_ops")
    if not isinstance(epo, dict):
        raise ConfigError("connectors config must have an 'epo_ops' mapping")
    for key in ("base_url", "auth_url"):
        if not epo.get(key):
            raise ConfigError(f"epo_ops connector config missing {key!r}")
    return ConnectorsConfig(sections=data)


@dataclass(frozen=True)
class LLMConfig:
    """Provider-agnostic LLM settings. EU-hosting preferred via ``base_url``.

    The provider/region is swappable here so the Engine is not locked to one
    vendor or location. API keys are NEVER stored here — they come from the
    environment (rule: no secrets in code).
    """

    provider: str
    model: str
    base_url: str | None
    max_tokens: int
    adaptive_thinking: bool


@dataclass(frozen=True)
class StreamsConfig:
    """Validated cross-referencing stream parameters."""

    sections: dict

    def section(self, name: str) -> dict:
        if name not in self.sections:
            raise ConfigError(f"no streams config section named {name!r}")
        return self.sections[name]


def load_streams_config(path: str | os.PathLike[str]) -> StreamsConfig:
    """Load + lightly validate stream parameters."""
    data = _read_yaml(path)
    if not isinstance(data.get("s2_patents"), dict):
        raise ConfigError("streams config must have an 's2_patents' mapping")
    return StreamsConfig(sections=data)


def load_llm_config(path: str | os.PathLike[str]) -> LLMConfig:
    """Load + validate LLM settings."""
    data = _read_yaml(path)
    model = data.get("model")
    if not model:
        raise ConfigError("llm config must set 'model'")
    try:
        max_tokens = int(data.get("max_tokens", 4096))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"llm 'max_tokens' must be an integer: {exc}") from exc
    if max_tokens <= 0:
        raise ConfigError("llm 'max_tokens' must be positive")
    return LLMConfig(
        provider=str(data.get("provider", "anthropic")),
        model=str(model),
        base_url=data.get("base_url"),
        max_tokens=max_tokens,
        adaptive_thinking=bool(data.get("adaptive_thinking", True)),
    )
