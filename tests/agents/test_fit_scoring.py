from datetime import date

from src.agents.eligibility_gate import run_eligibility_gate
from src.agents.fit_scoring import score_fit


def test_score_fit_returns_full_breakdown_within_bounds(sample_extracted, sample_hpe_profile):
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, all_matches = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    assert 0 <= breakdown.total <= 100
    assert len(all_matches) >= len(gate_matches)
    assert breakdown.explanation


def test_delivery_feasibility_penalizes_tight_deadline(sample_extracted, sample_hpe_profile):
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    far, _ = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    near, _ = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 10, 30))
    assert near.delivery_feasibility < far.delivery_feasibility


def test_delivery_feasibility_zero_past_deadline(sample_extracted, sample_hpe_profile):
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, _ = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2027, 1, 1))
    assert breakdown.delivery_feasibility == 0


def test_delivery_feasibility_neutral_when_deadline_unknown(sample_extracted, sample_hpe_profile):
    no_deadline = sample_extracted.model_copy(
        update={"deadlines": [], "tender": sample_extracted.tender.model_copy(update={"submission_deadline": None})}
    )
    gate_matches = run_eligibility_gate(no_deadline, sample_hpe_profile)
    breakdown, _ = score_fit(no_deadline, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    assert breakdown.delivery_feasibility == 5.0  # neutral midpoint, not penalized for missing data
