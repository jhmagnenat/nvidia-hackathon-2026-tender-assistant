"""Schema/adapter for the HPE web-research profile
(data/hpe_profile_research_v4.json, normalized into
data/hpe_profile_canonical_v4.json by
src.agents.hpe_research_normalization) — a richer, evidence-tracked
artifact produced by an external web-research pass.

Deliberately INCOMPATIBLE with, and separate from,
`src.schemas.hpe_profile.HPEProfile` (different field names —
`capability_name` vs `name`, `certification_name` vs `name` — and many more
top-level sections `HPEProfile` has no equivalent for). This module does
NOT feed `src.agents.matching`/`fit_scoring`/`eligibility_gate`/`briefing`:
those keep reading only `data/hpe_profile.json` via `HPEProfile`, completely
unchanged. This is a read-only validator/loader for the research artifact —
evidence review, `docs/AGENT_CONTEXT.md` generation, and any future,
explicitly-authorized promotion of a specific entry into
`data/hpe_profile.json` (a decision this module deliberately does not make
on its own).

`EvidenceStatus` is never the same thing as `src.schemas.common.MatchStatus`
— it describes how well a *claim in this research document* is sourced, not
whether a *tender requirement* matches an HPE capability. Never conflate
the two.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceStatus(str, Enum):
    """How strongly a claim in this research profile is backed.

    VERIFIED_PUBLIC requires at least one official HPE (hpe.com/
    developer.hpe.com/newsroom.hpe.com) or, for a certification claim, an
    accredited certification body's own source (see
    src.agents.hpe_research_normalization.is_official_source).
    PARTIALLY_VERIFIED covers secondary-source-only claims, or claims that
    are real but stale/out-of-scope (e.g. a 2015 global certification
    announcement of unconfirmed current validity). UNKNOWN means no usable
    evidence was found at all — never silently promoted to a match.
    """

    VERIFIED_PUBLIC = "VERIFIED_PUBLIC"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNKNOWN = "UNKNOWN"


class ResearchSource(BaseModel):
    """One entry in the profile's `sources` registry — the canonical shape
    Étape 4 specifies. `url` is the only field every real citation in this
    codebase's data actually carries; everything else is best-effort."""

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    url: str
    publisher: str | None = None
    accessed_at: str | None = None
    source_type: str | None = None
    claims_supported: list[str] = Field(default_factory=list)


class ResearchCapability(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    capability_id: str
    capability_name: str
    category: str | None = None
    description: str | None = None
    tender_keywords: list[str] = Field(default_factory=list)
    typical_deliverables: list[str] = Field(default_factory=list)
    hpe_products_or_platforms: list[str] = Field(default_factory=list, alias="HPE_products_or_platforms")
    capability_strength: str | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.UNKNOWN
    evidence_sources: list[str] = Field(default_factory=list)
    limitations: str | None = None
    partner_or_subcontractor_dependency: str | None = None


class QualificationRulesFlags(BaseModel):
    """Mirrors Étape 5's required flags exactly — informational here (the
    live enforcement is already in src/agents/eligibility_gate.py/briefing.py,
    unmodified); this is a checked record that the research profile agrees
    with the same policy, not a second place that enforces it."""

    unknown_is_not_match: bool = True
    technical_fit_does_not_prove_eligibility: bool = True
    unsupported_claims_are_forbidden: bool = True
    mandatory_unknown_caps_recommendation_at: str = "MAYBE"


class HPEResearchProfile(BaseModel):
    """The full canonical research artifact. Validates the top-level shape
    and the `capabilities`/`sources`/`qualification_rules` sections
    strictly (the ones this codebase actually consumes programmatically);
    every other section is kept as a loosely-typed list of dicts —
    strict-typing all sixteen sections would duplicate the source JSON's
    own structure for no behavioral gain (rule: minimal adapter, no
    architecture rewrite).
    """

    model_config = ConfigDict(extra="allow")

    profile_metadata: dict[str, Any] = Field(default_factory=dict)
    provider: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[ResearchCapability] = Field(default_factory=list)
    services: list[dict[str, Any]] = Field(default_factory=list)
    products_and_platforms: list[dict[str, Any]] = Field(default_factory=list)
    context_dependent_areas: list[dict[str, Any]] = Field(default_factory=list)
    out_of_scope_categories: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    geographic_coverage: list[dict[str, Any]] = Field(default_factory=list)
    legal_entities: list[dict[str, Any]] = Field(default_factory=list)
    public_sector_references: list[dict[str, Any]] = Field(default_factory=list)
    delivery_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    commercial_models: list[dict[str, Any]] = Field(default_factory=list)
    qualification_rules: QualificationRulesFlags = Field(default_factory=QualificationRulesFlags)
    unknowns: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)


def load_research_profile(path: str) -> HPEResearchProfile:
    """Loads and validates a research-profile JSON file (the raw
    data/hpe_profile_research_v4.json, or the normalized
    data/hpe_profile_canonical_v4.json — both share this same shape)."""
    from pathlib import Path

    return HPEResearchProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))
