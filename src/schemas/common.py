"""Shared primitives used across the tender/HPE-profile/briefing schemas."""

from enum import Enum

from pydantic import BaseModel, Field


class Language(str, Enum):
    FR = "fr"
    DE = "de"
    IT = "it"
    EN = "en"


class Citation(BaseModel):
    """Traceability back to the source document for an extracted fact.

    Every fact pulled out of a tender document (deadline, criterion,
    requirement, ...) must carry one of these. Never assert a fact without it.
    Absence of a citation on an optional field means the fact is UNKNOWN, not
    that it was silently inferred.
    """

    document: str = Field(..., description="Source file name, URL, or 'search index' for search-result metadata")
    page: int | None = Field(default=None, description="Page number, 1-indexed, if known")
    section: str | None = Field(default=None, description="Section/clause reference, e.g. '4.2'")
    quote: str | None = Field(default=None, description="Optional exact snippet supporting the fact")


class MatchStatus(str, Enum):
    """How a requirement compares against the HPE provider profile.

    NO_MATCH is only used when the profile carries data for that dimension and
    it clearly does not cover the requirement. When the profile simply has no
    data for that dimension (e.g. no certifications listed at all), the
    correct status is UNKNOWN — profile incompleteness is not the same as a
    confirmed gap.
    """

    MATCH = "match"
    PARTIAL_MATCH = "partial_match"
    UNKNOWN = "unknown"
    NO_MATCH = "no_match"


class Recommendation(str, Enum):
    GO = "GO"
    MAYBE = "MAYBE"
    NO_GO = "NO-GO"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
