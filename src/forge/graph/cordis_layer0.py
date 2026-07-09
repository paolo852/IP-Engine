"""Layer-0 graph population (T10): the university's EU-project industrial partners.

CORDIS is public open data, so this is the near-free first layer of the
Relationship Graph and the only realistic one for validation sites (brief §6).
From a CORDIS project we take the *industrial* participants (activityType 'PRC')
and record, for each, a ``collaborative_project`` relationship at source_layer 0.
Universities and research organisations are skipped — they are not reachable
industrial partners. Entity resolution merges a company seen across projects.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..connectors.cordis.parser import ParsedProject, parse_project
from ..db.models import RelationshipType, Strength
from .repository import add_relationship, resolve_company


@dataclass
class Layer0Report:
    project_id: str | None
    companies_created: int = 0
    companies_matched: int = 0
    relationships_added: int = 0
    skipped_non_industrial: int = 0

    def summary(self) -> str:
        return (
            f"project {self.project_id}: +{self.companies_created} companies "
            f"({self.companies_matched} matched), +{self.relationships_added} ties, "
            f"{self.skipped_non_industrial} non-industrial skipped"
        )


def build_layer0(session: Session, project: ParsedProject) -> Layer0Report:
    """Populate the graph from one parsed CORDIS project. Flushes, does not commit."""
    report = Layer0Report(project_id=project.project_id)
    topic = project.acronym or project.title
    source_ref = f"cordis:project:{project.project_id}" if project.project_id else None

    for org in project.organizations:
        if not org.is_industrial:
            report.skipped_non_industrial += 1
            continue
        company, created = resolve_company(
            session,
            name=org.name,
            registry_id=org.registry_id,
            country=org.country,
            size="sme" if org.is_sme else None,
        )
        report.companies_created += int(created)
        report.companies_matched += int(not created)

        _, rel_created = add_relationship(
            session,
            company,
            type=RelationshipType.collaborative_project,
            source_layer=0,
            topic=topic,
            start_date=project.start_date,
            end_date=project.end_date,
            strength=Strength.medium,
            source_ref=source_ref,
        )
        report.relationships_added += int(rel_created)

    return report


def populate_from_cordis_project(session: Session, client, ref: str) -> Layer0Report:
    """Fetch a CORDIS project and populate Layer-0 from it (commits on success)."""
    raw = client.fetch_project(ref)
    project = parse_project(raw.payload)
    if project is None:
        return Layer0Report(project_id=None)
    report = build_layer0(session, project)
    session.commit()
    return report
