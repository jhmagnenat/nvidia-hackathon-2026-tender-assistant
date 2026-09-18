"""RequirementExtractionAgent (Track A) — structured, cited requirement extraction.

Parses each retrieved TenderDocument's plain text into `ExtractedTenderData`.
Every requirement/deadline carries a `Citation` back to its source document
(and section, when the source text tags one in `[section X.Y]` form).

Deterministic, regex/section-header based — no LLM call. None of the required
LLM/NeMo infra is available in this environment (see IMPLEMENTATION_LOG.md),
and rule 6 requires the app to work offline with local sample data, so this
targets the section-header format used by data/sample_tenders/*/*.txt
(documented in data/sample_tenders/README.md). Real-world tender text would
need a more tolerant parser or an LLM-based extractor behind the same
signature — this module is the seam where that would slot in.
"""

from __future__ import annotations

import re
from datetime import date

from src.schemas.common import Citation
from src.schemas.tender import (
    Deadline,
    ExtractedTenderData,
    Requirement,
    RequirementCategory,
    Tender,
    TenderDocument,
)

_BULLET_RE = re.compile(r"^-\s*(.+?)(?:\s*\[(.+?)\])?\s*$")
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_KV_RE = re.compile(r"^([A-ZÉÈÀÂÊÎÔÛÇ /]+):\s*(.+)$")

_SECTION_HEADERS = {
    "PERIMETRE": "scope",
    "EXIGENCES OBLIGATOIRES": "mandatory_requirements",
    "CRITERES ELIGIBILITE": "eligibility_criteria",
    "EXIGENCES TECHNIQUES": "technical_requirements",
    "EXIGENCES COMMERCIALES": "commercial_requirements",
    "CRITERES EVALUATION": "evaluation_criteria",
    "CERTIFICATIONS REQUISES": "required_certifications",
    "REFERENCES REQUISES": "required_references",
    "RISQUES": "risks",
}

_BUCKET_CATEGORY = {
    "mandatory_requirements": RequirementCategory.MANDATORY,
    "eligibility_criteria": RequirementCategory.ELIGIBILITY,
    "technical_requirements": RequirementCategory.TECHNICAL,
    "commercial_requirements": RequirementCategory.COMMERCIAL,
    "evaluation_criteria": RequirementCategory.EVALUATION,
    "required_certifications": RequirementCategory.CERTIFICATION,
    "required_references": RequirementCategory.REFERENCE,
}

_DEFAULT_MANDATORY = {
    "mandatory_requirements": True,
    "eligibility_criteria": True,
    "technical_requirements": False,
    "commercial_requirements": False,
    "evaluation_criteria": False,
    "required_certifications": True,
    "required_references": True,
}


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _merge_continuation_lines(text: str) -> list[str]:
    """Join wrapped bullet/paragraph lines (indented continuations with no leading
    '-') onto the previous logical line, without ever merging into a section
    header. Only merges once a section header has been seen — the free-form
    metadata preamble (title/buyer/dates, before any section header) is never
    merged, since it's one fact per line, not a wrapped paragraph.
    """
    logical_lines: list[str] = []
    current_section: str | None = None
    last_was_header = True  # nothing to merge into yet
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_key = line.rstrip(":").strip().upper()
        is_header = header_key in _SECTION_HEADERS
        is_bullet = line.startswith("-")
        is_kv = bool(_KV_RE.match(line)) and not is_bullet

        if is_header:
            current_section = _SECTION_HEADERS[header_key]
            logical_lines.append(line)
            last_was_header = True
        elif is_bullet or is_kv or last_was_header or not logical_lines or current_section is None:
            logical_lines.append(line)
            last_was_header = False
        else:
            logical_lines[-1] = f"{logical_lines[-1]} {line}"
    return logical_lines


def extract_requirements(tender: Tender, documents: list[TenderDocument]) -> ExtractedTenderData:
    """Extract structured, cited requirements from a tender's retrieved documents."""
    buckets: dict[str, list[Requirement]] = {
        "mandatory_requirements": [],
        "eligibility_criteria": [],
        "technical_requirements": [],
        "commercial_requirements": [],
        "evaluation_criteria": [],
        "required_certifications": [],
        "required_references": [],
    }
    scope_lines: list[str] = []
    risks: list[str] = []
    deadlines: list[Deadline] = []
    metadata: dict[str, str] = {}
    counters: dict[str, int] = {}

    for doc in documents:
        if not doc.content_text:
            continue
        current_section: str | None = None
        for line in _merge_continuation_lines(doc.content_text):
            header_key = line.rstrip(":").strip().upper()
            if header_key in _SECTION_HEADERS:
                current_section = _SECTION_HEADERS[header_key]
                continue

            if current_section == "scope":
                scope_lines.append(line)
                continue

            if current_section == "risks":
                risks.append(line.lstrip("- ").strip())
                continue

            if current_section in _BUCKET_CATEGORY:
                bullet = _BULLET_RE.match(line)
                if not bullet:
                    continue
                description, section_tag = bullet.group(1), bullet.group(2)
                category = _BUCKET_CATEGORY[current_section]
                mandatory = _DEFAULT_MANDATORY[current_section]
                if "souhait" in description.lower() or "optionnel" in description.lower():
                    mandatory = False

                weight_percent = None
                if category == RequirementCategory.EVALUATION:
                    weight_match = _WEIGHT_RE.search(description)
                    if weight_match:
                        weight_percent = float(weight_match.group(1))

                counters[current_section] = counters.get(current_section, 0) + 1
                req_id = f"{tender.id}-{current_section}-{counters[current_section]}"
                buckets[current_section].append(
                    Requirement(
                        id=req_id,
                        category=category,
                        description=description,
                        mandatory=mandatory,
                        weight_percent=weight_percent,
                        citation=Citation(document=doc.name, section=section_tag),
                    )
                )
                continue

            kv = _KV_RE.match(line)
            if kv:
                key, value = kv.group(1).strip(), kv.group(2).strip()
                metadata.setdefault(key, value)
                if key == "DELAI DE SOUMISSION":
                    parsed = _parse_date(value)
                    if parsed:
                        deadlines.append(
                            Deadline(
                                label="Submission deadline",
                                date=parsed,
                                citation=Citation(document=doc.name),
                            )
                        )

    unknowns: list[str] = []
    if not scope_lines and not tender.scope:
        unknowns.append("Tender scope could not be determined from the retrieved documents.")
    if not deadlines and not tender.submission_deadline:
        unknowns.append("Submission deadline could not be determined from the retrieved documents.")
    if not buckets["mandatory_requirements"]:
        unknowns.append("No explicit mandatory-requirements section was found in the retrieved documents.")
    if not buckets["required_certifications"]:
        unknowns.append(
            "No required-certifications section was found in the retrieved documents — "
            "unclear whether a certification is required."
        )
    if not buckets["required_references"]:
        unknowns.append(
            "No required-references section was found in the retrieved documents — "
            "unclear whether a reference is required."
        )

    citations = [r.citation for reqs in buckets.values() for r in reqs if r.citation] + [d.citation for d in deadlines]

    return ExtractedTenderData(
        tender=tender,
        source_documents=[doc.name for doc in documents],
        source_language=documents[0].language if documents else None,
        deadlines=deadlines,
        mandatory_requirements=buckets["mandatory_requirements"],
        eligibility_criteria=buckets["eligibility_criteria"],
        technical_requirements=buckets["technical_requirements"],
        commercial_requirements=buckets["commercial_requirements"],
        evaluation_criteria=buckets["evaluation_criteria"],
        required_certifications=buckets["required_certifications"],
        required_references=buckets["required_references"],
        risks=risks,
        unknowns=unknowns,
        citations=citations,
    )


class RequirementExtractionAgent:
    """Thin class wrapper matching the brief's named interface."""

    def extract_requirements(self, tender: Tender, documents: list[TenderDocument]) -> ExtractedTenderData:
        return extract_requirements(tender, documents)
