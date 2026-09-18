"""Tender data contracts.

`Tender` is a search-result-level record (what TenderSearchTool returns).
`TenderDocument` is a retrieved document belonging to a tender.
`Requirement` + `ExtractedTenderData` are the RequirementExtractionAgent's
output contract — every requirement should carry a `Citation` back to the
document/section it came from; `None` means UNKNOWN provenance, not an
inferred fact.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.schemas.common import Citation, Language


class TenderSource(str, Enum):
    SIMAP = "simap"
    TAVILY = "tavily"
    LOCAL_SAMPLE = "local_sample"


class Tender(BaseModel):
    """A tender found by search, before its documents are retrieved/analyzed."""

    id: str
    title: str
    buyer: str | None = None
    location: str | None = None
    publication_date: date | None = None
    submission_deadline: date | None = None
    url: str | None = None
    source: TenderSource
    scope: str | None = Field(default=None, description="Short free-text scope/description from the listing")


class TenderDocument(BaseModel):
    """A single retrieved document belonging to a tender (notice, cahier des charges, annex, ...)."""

    tender_id: str
    name: str
    local_path: str | None = None
    url: str | None = None
    language: Language | None = None
    content_text: str | None = Field(default=None, description="Extracted plain text, if available")
    retrieved_at: datetime


class Deadline(BaseModel):
    label: str = Field(..., description="e.g. 'Submission deadline', 'Question deadline'")
    date: date
    citation: Citation


class RequirementCategory(str, Enum):
    MANDATORY = "mandatory"
    ELIGIBILITY = "eligibility"
    TECHNICAL = "technical"
    COMMERCIAL = "commercial"
    EVALUATION = "evaluation"
    CERTIFICATION = "certification"
    REFERENCE = "reference"


class Requirement(BaseModel):
    """A single structured requirement extracted from a tender's documents."""

    id: str
    category: RequirementCategory
    description: str
    mandatory: bool = False
    weight_percent: float | None = Field(default=None, ge=0, le=100, description="Set for evaluation criteria")
    citation: Citation | None = Field(default=None, description="None only if provenance is UNKNOWN")


class ExtractedTenderData(BaseModel):
    """Output of the RequirementExtractionAgent for a single tender."""

    tender: Tender
    source_documents: list[str] = Field(default_factory=list, description="Document names processed")
    source_language: Language | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    mandatory_requirements: list[Requirement] = Field(default_factory=list)
    eligibility_criteria: list[Requirement] = Field(default_factory=list)
    technical_requirements: list[Requirement] = Field(default_factory=list)
    commercial_requirements: list[Requirement] = Field(default_factory=list)
    evaluation_criteria: list[Requirement] = Field(default_factory=list)
    required_certifications: list[Requirement] = Field(default_factory=list)
    required_references: list[Requirement] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list, description="Fields the extractor could not determine")
    citations: list[Citation] = Field(default_factory=list)

    def all_requirements(self) -> list[Requirement]:
        return [
            *self.mandatory_requirements,
            *self.eligibility_criteria,
            *self.technical_requirements,
            *self.commercial_requirements,
            *self.evaluation_criteria,
            *self.required_certifications,
            *self.required_references,
        ]
