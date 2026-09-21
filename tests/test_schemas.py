"""Schema round-trip tests — these are the shared contracts every agent builds against.

Keep in sync with src/schemas/.
"""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.schemas.briefing import AlternativeTender, QualificationBriefing, ScoreBreakdown
from src.schemas.common import Confidence, Recommendation, ResearchMode, SelectionMode
from src.schemas.hpe_profile import HPEProfile
from src.schemas.hpe_research_profile import load_research_profile
from src.schemas.tender import Tender, TenderSource


def test_extracted_tender_data_round_trip(sample_extracted):
    restored = sample_extracted.model_validate_json(sample_extracted.model_dump_json())
    assert restored == sample_extracted


def test_tender_source_type_reflects_research_mode():
    """Requirement 3 — correct source_type display: 'simap_mcp' only for a
    real SIMAP-MCP-produced result, 'local_fallback' otherwise (the default)."""
    simap_tender = Tender(
        id="t-1", title="X", source=TenderSource.SIMAP, research_mode=ResearchMode.SIMAP_MCP
    )
    assert simap_tender.source_type == "simap_mcp"
    assert simap_tender.model_dump(mode="json")["source_type"] == "simap_mcp"

    local_tender = Tender(id="t-2", title="Y", source=TenderSource.LOCAL_SAMPLE)
    assert local_tender.source_type == "local_fallback"
    assert local_tender.model_dump(mode="json")["source_type"] == "local_fallback"


def test_tender_publication_id_defaults_to_none_and_round_trips():
    """publication_id is never guessed/derived from `id` -- absent unless a
    real SIMAP search result actually carried a 'Publication ID' line."""
    tender = Tender(id="t-1", title="X", source=TenderSource.LOCAL_SAMPLE)
    assert tender.publication_id is None

    with_pub = Tender(
        id="PRJ-1", title="X", source=TenderSource.SIMAP, publication_id="PUBID-1"
    )
    restored = Tender.model_validate_json(with_pub.model_dump_json())
    assert restored.publication_id == "PUBID-1"


def test_hpe_profile_round_trip(sample_hpe_profile):
    restored = sample_hpe_profile.model_validate_json(sample_hpe_profile.model_dump_json())
    assert restored == sample_hpe_profile


# --- HPE research profile (V4) -----------------------------------------------
# data/hpe_profile_research_v4.json / data/hpe_profile_canonical_v4.json —
# a separate, richer, INCOMPATIBLE schema from HPEProfile above (see
# src/schemas/hpe_research_profile.py's docstring). Never fed into
# matching/fit_scoring/eligibility_gate/briefing.


def test_hpe_profile_research_v4_is_valid_json():
    with open("data/hpe_profile_research_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert isinstance(raw, dict)
    for key in ("capabilities", "certifications", "sources", "qualification_rules", "unknowns"):
        assert key in raw


def test_hpe_profile_research_v4_is_incompatible_with_the_live_hpe_profile_schema():
    """Confirms the Étape 1 finding: the raw V4 shape cannot be loaded
    directly as HPEProfile (capability_name vs name, certification_name vs
    name, ...) — this is exactly why a separate adapter schema exists."""
    with open("data/hpe_profile_research_v4.json", encoding="utf-8") as f:
        raw = json.load(f)

    with pytest.raises(ValidationError):
        HPEProfile.model_validate(raw)


def test_canonical_research_profile_is_loadable():
    profile = load_research_profile("data/hpe_profile_canonical_v4.json")
    assert profile.capabilities
    assert profile.sources
    assert profile.qualification_rules.unknown_is_not_match is True
    assert profile.qualification_rules.mandatory_unknown_caps_recommendation_at == "MAYBE"


def test_canonical_research_profile_capability_fields_are_preserved():
    profile = load_research_profile("data/hpe_profile_canonical_v4.json")
    compute = next(c for c in profile.capabilities if c.capability_id == "compute_infrastructure")
    assert compute.capability_name == "Compute and server infrastructure"
    assert compute.hpe_products_or_platforms  # HPE_products_or_platforms alias resolved
    assert compute.evidence_sources


def test_all_requirements_concatenates_every_category(sample_extracted):
    combined = sample_extracted.all_requirements()
    assert len(combined) == 5  # mandatory + eligibility + technical + evaluation + certification


def test_score_breakdown_total_matches_dimensions():
    breakdown = ScoreBreakdown(
        capability_fit=20,
        mandatory_requirement_fit=20,
        eligibility_fit=10,
        delivery_feasibility=8,
        strategic_relevance=7,
        information_confidence=5,
        explanation="Example.",
    )
    assert breakdown.total == 70


def test_qualification_briefing_minimal(sample_tender_meta):
    breakdown = ScoreBreakdown(
        capability_fit=0,
        mandatory_requirement_fit=0,
        eligibility_fit=0,
        delivery_feasibility=0,
        strategic_relevance=0,
        information_confidence=0,
        explanation="No data.",
    )
    result = QualificationBriefing(
        tender=sample_tender_meta,
        recommendation=Recommendation.NO_GO,
        score=0,
        score_breakdown=breakdown,
        confidence=Confidence.LOW,
        executive_summary="Example summary.",
        generated_at=datetime.now(UTC),
    )
    assert result.recommendation == Recommendation.NO_GO
    assert result.human_review.decision is None
    # serializable to JSON per the brief's suggested output structure
    dumped = result.model_dump(mode="json")
    for key in ("tender", "recommendation", "score", "confidence", "executive_summary", "human_review"):
        assert key in dumped


def test_qualification_briefing_selection_fields_default_honestly(sample_tender_meta):
    """A briefing built without any selection info (every pre-existing call
    site) must default to 'direct' -- never silently claim an automatic
    selection happened when no candidate comparison occurred."""
    breakdown = ScoreBreakdown(
        capability_fit=0,
        mandatory_requirement_fit=0,
        eligibility_fit=0,
        delivery_feasibility=0,
        strategic_relevance=0,
        information_confidence=0,
        explanation="No data.",
    )
    result = QualificationBriefing(
        tender=sample_tender_meta,
        recommendation=Recommendation.NO_GO,
        score=0,
        score_breakdown=breakdown,
        confidence=Confidence.LOW,
        executive_summary="Example summary.",
        generated_at=datetime.now(UTC),
    )
    assert result.selection_mode == SelectionMode.DIRECT
    assert result.alternatives == []
    assert result.selected_tender_id == sample_tender_meta.id

    dumped = result.model_dump(mode="json")
    # selected_tender_id is a computed_field -- must appear in the dump, not
    # just be accessible as a Python attribute.
    assert dumped["selected_tender_id"] == sample_tender_meta.id
    assert dumped["selection_mode"] == "direct"


def test_alternative_tender_round_trip():
    alt = AlternativeTender(tender_id="t-2", title="Some other tender", relevance_score=42.5, rank=1)
    restored = AlternativeTender.model_validate_json(alt.model_dump_json())
    assert restored == alt
