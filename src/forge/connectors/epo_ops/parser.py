"""Parse an OPS biblio response into structured patent records.

OPS XML is namespaced and the same party appears in several ``data-format``s.
We match on *local* tag names (namespace-tolerant) and prefer the ``epodoc``
data-format for parties to avoid duplicates. Missing pieces degrade to None /
empty lists rather than raising — robustness over strictness (rule 7).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


def _local(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an element tag."""
    return tag.rsplit("}", 1)[-1]


def _find(elem: ET.Element, *path: str) -> ET.Element | None:
    """Walk child elements by local name, returning the first match."""
    current = elem
    for name in path:
        nxt = None
        for child in list(current):
            if _local(child.tag) == name:
                nxt = child
                break
        if nxt is None:
            return None
        current = nxt
    return current


def _findall(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in elem.iter() if _local(child.tag) == name]


def _direct(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(elem) if _local(child.tag) == name]


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    text = elem.text.strip()
    return text or None


def _iso_date(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return None
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


@dataclass
class ParsedPatent:
    """The biblio fields we lift from one OPS exchange-document."""

    country: str | None
    doc_number: str | None
    kind: str | None
    publication_id: str | None  # canonical e.g. "EP9999999A1" (per-doc dedup key)
    title: str | None = None
    abstract: str | None = None
    inventors: list[str] = field(default_factory=list)
    applicants: list[str] = field(default_factory=list)
    publication_date: str | None = None
    application_date: str | None = None
    priority_date: str | None = None
    ipc_classes: list[str] = field(default_factory=list)


def _document_id(parent: ET.Element, id_type: str) -> ET.Element | None:
    for doc_id in _direct(parent, "document-id"):
        if doc_id.get("document-id-type") == id_type:
            return doc_id
    return None


def _pick_title(doc: ET.Element) -> str | None:
    titles = _findall(doc, "invention-title")
    if not titles:
        return None
    for title in titles:  # prefer English
        if (title.get("lang") or "").lower() == "en":
            return _text(title)
    return _text(titles[0])


def _pick_abstract(doc: ET.Element) -> str | None:
    abstracts = [c for c in list(doc) if _local(c.tag) == "abstract"]
    if not abstracts:
        return None
    chosen = None
    for ab in abstracts:
        if (ab.get("lang") or "").lower() == "en":
            chosen = ab
            break
    chosen = chosen or abstracts[0]
    parts = [t for p in _direct(chosen, "p") if (t := _text(p))]
    return " ".join(parts) if parts else _text(chosen)


def _party_names(parties: ET.Element | None, group: str, member: str) -> list[str]:
    """Collect epodoc-formatted party names, falling back to any format."""
    if parties is None:
        return []
    container = _find(parties, group)
    if container is None:
        return []
    members = _direct(container, member)
    epodoc = [m for m in members if m.get("data-format") == "epodoc"]
    chosen = epodoc or members
    names: list[str] = []
    for m in chosen:
        name = _text(_find(m, f"{member}-name", "name"))
        if name and name not in names:
            names.append(name)
    return names


def _parse_document(doc: ET.Element) -> ParsedPatent:
    biblio = _find(doc, "bibliographic-data")
    country = doc.get("country")
    doc_number = doc.get("doc-number")
    kind = doc.get("kind")

    pub_date = app_date = prio_date = None
    if biblio is not None:
        pub_ref = _find(biblio, "publication-reference")
        if pub_ref is not None:
            docdb = _document_id(pub_ref, "docdb")
            if docdb is not None:
                country = country or _text(_find(docdb, "country"))
                doc_number = doc_number or _text(_find(docdb, "doc-number"))
                kind = kind or _text(_find(docdb, "kind"))
                pub_date = _iso_date(_text(_find(docdb, "date")))

        app_ref = _find(biblio, "application-reference")
        if app_ref is not None:
            app_docdb = _document_id(app_ref, "docdb")
            if app_docdb is not None:
                app_date = _iso_date(_text(_find(app_docdb, "date")))

        prio = _find(biblio, "priority-claims")
        if prio is not None:
            first_claim = _find(prio, "priority-claim")
            if first_claim is not None:
                prio_docdb = _document_id(first_claim, "docdb")
                if prio_docdb is not None:
                    prio_date = _iso_date(_text(_find(prio_docdb, "date")))

    parties = _find(biblio, "parties") if biblio is not None else None
    ipc = [
        t
        for c in _findall(doc, "classification-ipcr")
        if (t := _text(_find(c, "text")))
    ]

    publication_id = (
        f"{country}{doc_number}{kind or ''}" if country and doc_number else None
    )

    return ParsedPatent(
        country=country,
        doc_number=doc_number,
        kind=kind,
        publication_id=publication_id,
        title=_pick_title(biblio) if biblio is not None else None,
        abstract=_pick_abstract(doc),
        inventors=_party_names(parties, "inventors", "inventor"),
        applicants=_party_names(parties, "applicants", "applicant"),
        publication_date=pub_date,
        application_date=app_date,
        priority_date=prio_date,
        ipc_classes=ipc,
    )


def parse_biblio(payload: bytes | str) -> list[ParsedPatent]:
    """Parse an OPS biblio payload into one ParsedPatent per exchange-document."""
    root = ET.fromstring(payload)
    docs = [e for e in root.iter() if _local(e.tag) == "exchange-document"]
    return [_parse_document(doc) for doc in docs]
