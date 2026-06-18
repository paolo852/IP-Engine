"""Document ingestion: extract text from an uploaded file, classify it, and pull
out the fields the engine profiles.

Two honest, deterministic steps (no black-box ML):

* ``classify_document`` decides **patent vs unpatented result** from explicit,
  auditable markers (patent numbers, claim headings, INID codes…) and reports
  *which* markers it matched, so the decision is explainable.
* ``extract_fields`` pulls a best-effort title / abstract / claim-or-description
  from the text. It is heuristic and says so — the asset is always reviewable.

Supported inputs: PDF (text layer) and plain text / markdown. A scanned PDF with
no text layer yields no text and is reported as such, never fabricated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db.models import AssetType


class DocumentError(ValueError):
    """Raised when a document cannot be read or has no extractable text."""


# -- text extraction --------------------------------------------------------
def extract_text(filename: str, raw: bytes) -> str:
    """Return the plain text of an uploaded file (PDF or text). Never guesses."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or raw[:5] == b"%PDF-":
        return _extract_pdf_text(raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _extract_pdf_text(raw: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - dependency wiring
        raise DocumentError(f"PDF support unavailable: {exc}") from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentError(f"could not read PDF: {exc}") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise DocumentError(
            "no text found in PDF (a scanned image needs OCR, which is out of scope)"
        )
    return text


# -- classification (patent vs unpatented result) ---------------------------
# Explicit, auditable markers. Each is (label, compiled-pattern); a match is
# surfaced to the user as the reason for the classification.
_PATENT_MARKERS: list[tuple[str, re.Pattern]] = [
    ("claim heading", re.compile(r"\b(what is claimed|we claim|i claim|the claims? (is|are))\b", re.I)),
    ("patent number", re.compile(r"\b(?:EP|US|WO|CN|JP|DE|GB|FR)\s?\d[\d ,]{5,}\s?[AB]?\d?\b")),
    ("patent header", re.compile(r"\b(united states patent|european patent|patent application publication|patent no\.?)\b", re.I)),
    ("INID code", re.compile(r"\(\s*(?:54|57|71|72|73|21|22|45|51)\s*\)")),
    ("IPC class", re.compile(r"\bInt\.?\s?Cl\.?\b", re.I)),
]

# Markers that lean towards a non-patent research result (used only to explain).
_RESULT_MARKERS: list[tuple[str, re.Pattern]] = [
    ("references section", re.compile(r"\n\s*references\s*\n", re.I)),
    ("DOI", re.compile(r"\bdoi:\s*10\.\d{4,}", re.I)),
    ("deliverable/WP", re.compile(r"\b(deliverable|work package|work-package|wp\d)\b", re.I)),
    ("thesis/paper", re.compile(r"\b(thesis|dissertation|this paper|we present|preprint)\b", re.I)),
]


@dataclass
class DocumentClassification:
    asset_type: AssetType
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return "patent" if self.asset_type is AssetType.patent else "unpatented result"


def classify_document(text: str) -> DocumentClassification:
    """Patent vs unpatented result, by explicit markers. Returns the reasons too."""
    patent_hits = [label for label, pat in _PATENT_MARKERS if pat.search(text)]
    result_hits = [label for label, pat in _RESULT_MARKERS if pat.search(text)]

    # A patent if it carries at least one strong patent marker AND patents are not
    # clearly outweighed by paper/deliverable markers; else an unpatented result.
    if patent_hits and len(patent_hits) >= len(result_hits):
        return DocumentClassification(
            AssetType.patent, [f"matched {h}" for h in patent_hits]
        )
    reasons = [f"matched {h}" for h in result_hits] or [
        "no patent markers found (no claims / patent number / INID codes)"
    ]
    return DocumentClassification(AssetType.project_result, reasons)


# -- field extraction -------------------------------------------------------
_HEADINGS = re.compile(
    r"^\s*\(?\d{0,2}\)?\s*(abstract|summary|background|claims?|description|"
    r"field of (the )?invention|references|introduction)\b",
    re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


# Patent front-page boilerplate that should never be part of a title — INID codes
# like (71)/(73), the applicant/assignee/inventor lines, and classification fields.
_TITLE_STOP = re.compile(
    r"\(\s*\d{2}\s*\)|\bApplicant\b|\bAssignee\b|\bInventor|\bU\.?\s?S\.?\s?Cl\b|"
    r"\bInt\.?\s?Cl\b|\bCPC\b|\bField of\b|\bPrior Publication\b|\bRelated\s+U\.?\s?S\b",
    re.I,
)


def _clean_title(text: str) -> str | None:
    """Strip patent front-page noise from a candidate title line.

    Cuts at the first boilerplate marker (INID code, applicant, classification),
    drops a leading (54)/'Title of Invention'/patent-number prefix, and trims
    stray punctuation. Returns None if nothing title-like remains.
    """
    s = _clean(text)
    cut = _TITLE_STOP.search(s)
    if cut:
        s = s[: cut.start()]
    s = re.sub(r"^\s*\(\s*54\s*\)\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*title of (?:the )?invention\s*[:\-]?\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*(?:united states patent|patent no\.?|US|EP|WO)\b[\s\d,./-]*", "", s, flags=re.I)
    s = _clean(s.strip(" .,:;-@#*|()/"))
    letters = sum(c.isalpha() for c in s)
    return s if letters >= 6 and len(s) <= 160 else None


def _first_title(text: str) -> str | None:
    # Prefer an explicit "Title of Invention" / (54) marker (cleaned), else the
    # first substantial line that reads like a title once boilerplate is stripped.
    m = re.search(r"(?:title of (?:the )?invention|\(\s*54\s*\))\s*[:\-]?\s*(.+)", text, re.I)
    if m:
        cleaned = _clean_title(m.group(1))
        if cleaned:
            return cleaned
    for line in text.splitlines():
        s = _clean(line)
        if not s or _HEADINGS.match(s) or " " not in s:
            continue
        cleaned = _clean_title(s)
        if cleaned:
            return cleaned
    return None


def _section(text: str, start: re.Pattern) -> str | None:
    """Text from a heading match until the next heading (or a blank gap)."""
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if not capturing:
            if start.search(line):
                capturing = True
                tail = start.split(line, 1)[-1].strip(" :.-")
                if tail and not _HEADINGS.match(tail):
                    out.append(tail)
            continue
        if _HEADINGS.match(line) or (not line.strip() and out):
            break
        if line.strip():
            out.append(line.strip())
    body = _clean(" ".join(out))
    return body or None


def extract_fields(text: str, asset_type: AssetType) -> dict:
    """Best-effort {title, abstract, claims_or_description} from the document text."""
    fields: dict[str, str] = {}
    title = _first_title(text)
    if title:
        fields["title"] = title

    abstract = _section(text, re.compile(r"\babstract\b", re.I)) or _section(
        text, re.compile(r"\bsummary\b", re.I)
    )
    if abstract:
        fields["abstract"] = abstract[:2000]

    claims = _section(text, re.compile(r"\b(what is claimed|we claim|claims?)\b", re.I))
    if claims is None:
        claims = _section(text, re.compile(r"\bdescription\b", re.I))
    if claims is None:
        # Fall back to the body after the abstract so there is something to profile.
        body = _clean(text)
        if abstract and abstract[:60] in body:
            body = body.split(abstract[:60], 1)[-1]
        claims = body[:2000] if body else None
    if claims:
        fields["claims_or_description"] = claims[:2000]

    return fields


@dataclass
class ParsedDocument:
    classification: DocumentClassification
    fields: dict
    char_count: int

    @property
    def asset_type(self) -> AssetType:
        return self.classification.asset_type


def parse_document(filename: str, raw: bytes) -> ParsedDocument:
    """Extract text, classify the document, and pull out the profilable fields."""
    text = extract_text(filename, raw)
    if not text.strip():
        raise DocumentError("the document has no readable text")
    classification = classify_document(text)
    fields = extract_fields(text, classification.asset_type)
    if "title" not in fields and "abstract" not in fields and "claims_or_description" not in fields:
        raise DocumentError("could not extract any title/abstract/description text")
    return ParsedDocument(classification=classification, fields=fields, char_count=len(text))
