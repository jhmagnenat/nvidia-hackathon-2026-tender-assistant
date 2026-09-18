from datetime import date

from src.agents.briefing import _recommendation, generate_briefing
from src.agents.eligibility_gate import run_eligibility_gate
from src.agents.fit_scoring import score_fit
from src.schemas.briefing import CapabilityMatch
from src.schemas.common import MatchStatus, Recommendation


def _match(status: MatchStatus) -> CapabilityMatch:
    return CapabilityMatch(requirement_id="r", requirement_description="desc", status=status, justification="x")


def test_recommendation_no_go_on_confirmed_hard_failure_regardless_of_score():
    rec, _ = _recommendation(90, [_match(MatchStatus.NO_MATCH)])
    assert rec == Recommendation.NO_GO


def test_recommendation_capped_at_maybe_when_mandatory_unknown():
    rec, _ = _recommendation(80, [_match(MatchStatus.UNKNOWN)])
    assert rec == Recommendation.MAYBE


def test_recommendation_go_when_all_resolved_and_score_high():
    rec, _ = _recommendation(80, [_match(MatchStatus.MATCH)])
    assert rec == Recommendation.GO


def test_recommendation_no_go_when_score_low_and_no_gate_issues():
    rec, _ = _recommendation(20, [_match(MatchStatus.MATCH)])
    assert rec == Recommendation.NO_GO


def test_generate_briefing_end_to_end(sample_extracted, sample_hpe_profile):
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, all_matches = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    briefing = generate_briefing(sample_extracted, gate_matches, breakdown, all_matches)

    assert briefing.recommendation == Recommendation.MAYBE  # ISO 27001 cert is UNKNOWN in the fixture profile
    assert briefing.human_review.decision is None
    assert briefing.score == round(breakdown.total, 1)
    assert briefing.tender.id == sample_extracted.tender.id
    dumped = briefing.model_dump(mode="json")
    assert dumped["human_review"]["decision"] is None
