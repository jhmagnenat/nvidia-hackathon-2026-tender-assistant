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


class ResearchMode(str, Enum):
    """Which backend actually produced a `Tender` search result.

    Coarser than `TenderSource` (simap/tavily/local_sample — the specific
    provider): this is the real-vs-fallback signal a caller can key off of
    without knowing every provider name. `SIMAP_MCP` is set only by a live,
    successful call through `src.adapters.tender_search.SimapAdapter`'s real
    MCP client (see that module) — never assumed just because the adapter is
    configured. `LOCAL_FALLBACK` covers the local sample index and any other
    non-live source.
    """

    SIMAP_MCP = "simap_mcp"
    LOCAL_FALLBACK = "local_fallback"


class SelectionMode(str, Enum):
    """How a `QualificationBriefing`'s tender was chosen.

    AUTO: automatically selected among multiple search-result candidates by
    `src.agents.tender_selection`'s relevance scoring. HUMAN_OVERRIDE: a
    human explicitly picked a different candidate from that same set.
    DIRECT: the tender was analyzed directly by id/object, with no candidate
    comparison at all (e.g. `python -m src.pipeline analyze <id>`, or any
    direct call to `WorkflowOrchestrator.analyze_tender`) — the default, so
    every existing call site keeps behaving exactly as before.
    """

    AUTO = "auto"
    HUMAN_OVERRIDE = "human_override"
    DIRECT = "direct"


class PublicationStatus(str, Enum):
    """A tender's actionability, per `src.agents.tender_selection`'s SELECT
    phase — set only from a real signal (a real `pub_type` from a live
    `get_tender_details` call, or a real known `submission_deadline`), never
    guessed. `UNKNOWN` is the honest default whenever neither is available
    (e.g. a local_fallback tender, or a SIMAP tender with no publication_id,
    or an unreachable SIMAP adapter) — it must never be treated as a
    confirmed NO-GO on its own; see `classify_publication_status`.
    """

    UNKNOWN = "unknown"
    OPEN = "open"
    ALREADY_AWARDED = "already_awarded"
    DIRECT_AWARD_NOT_OPEN = "direct_award_not_open"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CANCELLED = "cancelled"
