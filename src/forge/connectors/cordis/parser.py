"""Parse a CORDIS result payload into structured project-result records.

CORDIS (the EU's research-results portal) publishes Key Exploitable Results and
project deliverables as public open data (CC BY). The JSON shape varies across
the portal's endpoints, so we match keys tolerantly with fallbacks and degrade
missing pieces to None / empty lists rather than raising — robustness over
strictness (rule 7).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class ParsedResult:
    """The fields we lift from one CORDIS result record."""

    result_id: str | None
    title: str | None = None
    abstract: str | None = None  # teaser / short summary
    description: str | None = None  # the full exploitable-result text
    owners: list[str] = field(default_factory=list)
    end_date: str | None = None  # ISO yyyy-mm-dd (project end)
    project_id: str | None = None
    project_acronym: str | None = None
    url: str | None = None
    keywords: list[str] = field(default_factory=list)


def _first(data: dict, *keys: str) -> object:
    for key in keys:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _iso_date(value: object) -> str | None:
    text = _as_str(value)
    if not text:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _names(value: object) -> list[str]:
    """Organisation names from a list of dicts ({'name': ...}) or bare strings."""
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _as_str(_first(item, "name", "legalName", "shortName"))
            else:
                name = _as_str(item)
            if name and name not in out:
                out.append(name)
    elif isinstance(value, str):
        name = _as_str(value)
        if name:
            out.append(name)
    return out


def _keywords(value: object) -> list[str]:
    if isinstance(value, list):
        return [k for v in value if (k := _as_str(v))]
    if isinstance(value, str):
        # CORDIS sometimes gives a comma/semicolon-separated string.
        return [k for part in re.split(r"[;,]", value) if (k := part.strip())]
    return []


def _items(data: object) -> list[dict]:
    """Find the result objects in a CORDIS payload of varied shapes."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in ("results", "result", "hits", "payload"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [d for d in inner if isinstance(d, dict)]
            if isinstance(inner, dict) and isinstance(inner.get("hits"), list):
                return [d for d in inner["hits"] if isinstance(d, dict)]
        return [data]
    return []


def _parse_one(d: dict) -> ParsedResult:
    return ParsedResult(
        result_id=_as_str(_first(d, "id", "rcn", "resultId", "result_id")),
        title=_as_str(_first(d, "title", "name")),
        abstract=_as_str(_first(d, "teaser", "summary", "description_short")),
        description=_as_str(_first(d, "description", "content", "fullText")),
        owners=_names(_first(d, "organizations", "organisations", "owners", "coordinator")),
        end_date=_iso_date(_first(d, "endDate", "projectEndDate", "project_end_date", "end_date")),
        project_id=_as_str(_first(d, "projectID", "projectId", "project_id", "grantNumber")),
        project_acronym=_as_str(_first(d, "projectAcronym", "acronym")),
        url=_as_str(_first(d, "url", "link", "sourceUrl")),
        keywords=_keywords(_first(d, "keywords", "euroSciVoc", "tags")),
    )


def parse_results(payload: bytes | str) -> list[ParsedResult]:
    """Parse a CORDIS result payload into zero or more ParsedResult records."""
    data = json.loads(payload)
    return [_parse_one(item) for item in _items(data)]


# -- projects (Layer-0 graph population) ------------------------------------
@dataclass
class ParsedOrg:
    """One participating organisation in a CORDIS project."""

    name: str
    activity_type: str | None = None  # HES | REC | PRC | PUB | OTH
    role: str | None = None  # coordinator | participant
    country: str | None = None
    registry_id: str | None = None  # PIC
    is_sme: bool = False

    @property
    def is_industrial(self) -> bool:
        """A private for-profit company (CORDIS activityType 'PRC')."""
        return (self.activity_type or "").upper() == "PRC"


@dataclass
class ParsedProject:
    """A CORDIS project and its participating organisations."""

    project_id: str | None
    acronym: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    organizations: list[ParsedOrg] = field(default_factory=list)


def _parse_org(d: dict) -> ParsedOrg | None:
    name = _as_str(_first(d, "name", "legalName", "shortName"))
    if not name:
        return None
    sme = d.get("sme")
    return ParsedOrg(
        name=name,
        activity_type=_as_str(_first(d, "activityType", "activity_type", "type")),
        role=_as_str(_first(d, "role", "ecContribution_role", "organizationRole")),
        country=_as_str(_first(d, "country", "countryCode")),
        registry_id=_as_str(_first(d, "pic", "PIC", "registry_id", "vatNumber")),
        is_sme=bool(sme) if isinstance(sme, bool) else _as_str(sme) in ("true", "1", "yes"),
    )


def _project_orgs(d: dict) -> list[dict]:
    raw = _first(d, "organizations", "organisations", "participants", "partners")
    return [o for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []


def parse_project(payload: bytes | str) -> ParsedProject | None:
    """Parse a CORDIS project payload into a ParsedProject (or None if empty)."""
    data = json.loads(payload)
    items = _items(data)
    if not items:
        return None
    d = items[0]
    return ParsedProject(
        project_id=_as_str(_first(d, "id", "rcn", "projectID", "projectId", "grantNumber")),
        acronym=_as_str(_first(d, "acronym", "projectAcronym")),
        title=_as_str(_first(d, "title", "name")),
        start_date=_iso_date(_first(d, "startDate", "start_date", "startDateCode")),
        end_date=_iso_date(_first(d, "endDate", "end_date", "endDateCode")),
        organizations=[org for o in _project_orgs(d) if (org := _parse_org(o))],
    )
