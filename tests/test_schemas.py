"""Schema round-trip tests — these are the shared contracts every agent builds against.

Keep in sync with src/schemas/.
"""

from datetime import UTC, datetime

from src.schemas.briefing import QualificationBriefing, ScoreBreakdown
from src.schemas.common import Confidence, Recommendation


def test_extracted_tender_data_round_trip(sample_extracted):
    restored = sample_extracted.model_validate_json(sample_extracted.model_dump_json())
    assert restored == sample_extracted


def test_hpe_profile_round_trip(sample_hpe_profile):
    restored = sample_hpe_profile.model_validate_json(sample_hpe_profile.model_dump_json())
    assert restored == sample_hpe_profile


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
