from src.agents.eligibility_gate import (
    gate_has_hard_failure,
    gate_has_unknown,
    mandatory_requirements,
    run_eligibility_gate,
)
from src.schemas.briefing import CapabilityMatch
from src.schemas.common import MatchStatus


def test_mandatory_requirements_collects_all_mandatory_categories(sample_extracted):
    reqs = mandatory_requirements(sample_extracted)
    ids = {r.id for r in reqs}
    assert {"req-1", "elig-1", "cert-1"}.issubset(ids)


def test_run_eligibility_gate_returns_one_match_per_mandatory_requirement(sample_extracted, sample_hpe_profile):
    matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    assert len(matches) == len(mandatory_requirements(sample_extracted))


def test_gate_unknown_but_not_failed_when_profile_lacks_certifications(sample_extracted, sample_hpe_profile):
    matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    assert gate_has_unknown(matches) is True
    assert gate_has_hard_failure(matches) is False


def test_gate_hard_failure_detected():
    matches = [
        CapabilityMatch(requirement_id="x", requirement_description="d", status=MatchStatus.NO_MATCH, justification="j")
    ]
    assert gate_has_hard_failure(matches) is True
