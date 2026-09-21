from datetime import date

from src.agents.briefing import generate_briefing
from src.agents.eligibility_gate import run_eligibility_gate
from src.agents.fit_scoring import score_fit
from src.agents.workflow_state import (
    get_pending_research_requests,
    load_workflow_state,
    mark_research_requests_reviewed,
    record_human_decision,
    update_state_after_qualification,
)


def test_update_state_after_qualification_creates_state(tmp_path, sample_briefing):
    state = update_state_after_qualification(tmp_path, sample_briefing)

    assert state["tender_id"] == sample_briefing.tender.id
    assert state["source_type"] == sample_briefing.tender.source_type
    assert state["documents_status"] == "RETRIEVED"
    assert state["qualification_status"] == "COMPLETE"
    assert state["score"] == sample_briefing.score
    assert state["recommendation"] == sample_briefing.recommendation.value
    assert state["confidence"] == sample_briefing.confidence.value
    assert state["human_review"]["status"] == "HUMAN_REVIEW_PENDING"
    assert state["human_review"]["decision"] is None
    assert state["history"][-1]["event"] == "qualification_complete"

    # Persisted to disk, one file per tender_id -- reloadable independently.
    reloaded = load_workflow_state(tmp_path, sample_briefing.tender.id)
    assert reloaded == state


def test_update_state_after_qualification_preserves_unknowns(sample_extracted, sample_hpe_profile, tmp_path):
    """Rule: 'conserver les UNKNOWN' -- sample_extracted carries the same
    ISO/IEC 27001 requirement twice (full sentence + short bullet), both
    UNKNOWN against sample_hpe_profile. The state's `unknowns` list is the
    full, untruncated record (deduplication only happens in the compact
    `executive_summary` sub-object) -- nothing is silently dropped."""
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, all_matches = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    briefing = generate_briefing(sample_extracted, gate_matches, breakdown, all_matches)

    state = update_state_after_qualification(tmp_path, briefing)

    assert state["unknowns"] == briefing.unknowns
    assert sum("27001" in u.lower() for u in state["unknowns"]) >= 2
    # The compact view still deduplicates, as before.
    assert sum("27001" in b.lower() for b in state["executive_summary"]["blockers"]) == 1


def test_record_human_decision_more_research_does_not_erase_prior_state(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)

    state = record_human_decision(
        tmp_path, sample_briefing.tender.id, "more_research", reviewer="jj", comment="need more docs"
    )

    # Prior qualification result is untouched.
    assert state["score"] == sample_briefing.score
    assert state["recommendation"] == sample_briefing.recommendation.value
    assert state["qualification_status"] == "COMPLETE"

    # The request itself is recorded, not silently dropped.
    assert len(state["research_requests"]) == 1
    assert state["research_requests"][0]["note"] == "need more docs"
    assert state["research_requests"][0]["reviewer"] == "jj"
    assert state["human_review"]["status"] == "HUMAN_REVIEW_MORE_RESEARCH"
    assert state["human_review"]["decision"] == "more_research"

    # A history event was appended (on top of the earlier qualification one).
    events = [h["event"] for h in state["history"]]
    assert events == ["qualification_complete", "research_requested"]


def test_record_human_decision_approve_preserves_original_recommendation(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)
    original_score = sample_briefing.score
    original_recommendation = sample_briefing.recommendation.value

    state = record_human_decision(
        tmp_path, sample_briefing.tender.id, "approved", reviewer="jj", comment="Looks good"
    )

    assert state["score"] == original_score
    assert state["recommendation"] == original_recommendation
    assert state["human_review"]["status"] == "HUMAN_REVIEW_APPROVED"
    assert state["human_review"]["decision"] == "approved"
    assert state["human_review"]["comment"] == "Looks good"
    assert state["human_review"]["reviewer"] == "jj"
    assert state["executive_summary"]["human_review_status"] == "HUMAN_REVIEW_APPROVED"


def test_record_human_decision_reject_persists_decision_and_comment(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)

    state = record_human_decision(tmp_path, sample_briefing.tender.id, "rejected", reviewer="jj", comment="Not a fit")

    assert state["human_review"]["status"] == "HUMAN_REVIEW_REJECTED"
    assert state["human_review"]["decision"] == "rejected"
    assert state["human_review"]["comment"] == "Not a fit"
    reloaded = load_workflow_state(tmp_path, sample_briefing.tender.id)
    assert reloaded["human_review"]["decision"] == "rejected"


def test_workflow_state_is_separated_by_tender_id(tmp_path, sample_briefing):
    other = sample_briefing.model_copy(deep=True)
    other.tender = other.tender.model_copy(update={"id": "other-tender-2026", "title": "Another tender"})

    update_state_after_qualification(tmp_path, sample_briefing)
    update_state_after_qualification(tmp_path, other)
    record_human_decision(tmp_path, "other-tender-2026", "rejected", comment="Not this one")

    state_a = load_workflow_state(tmp_path, sample_briefing.tender.id)
    state_b = load_workflow_state(tmp_path, "other-tender-2026")

    assert state_a["tender_id"] == sample_briefing.tender.id
    assert state_b["tender_id"] == "other-tender-2026"
    # A decision recorded on tender B must never leak onto tender A's state.
    assert state_a["human_review"]["decision"] is None
    assert state_b["human_review"]["decision"] == "rejected"
    assert load_workflow_state(tmp_path, "does-not-exist-2099") is None


def test_get_pending_research_requests_empty_when_no_state_or_no_request(tmp_path, sample_briefing):
    assert get_pending_research_requests(tmp_path, "does-not-exist-2099") == []

    update_state_after_qualification(tmp_path, sample_briefing)
    assert get_pending_research_requests(tmp_path, sample_briefing.tender.id) == []


def test_get_pending_research_requests_after_more_research(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)
    record_human_decision(tmp_path, sample_briefing.tender.id, "more_research", reviewer="jj", comment="Check X")

    pending = get_pending_research_requests(tmp_path, sample_briefing.tender.id)

    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["note"] == "Check X"


def test_mark_research_requests_reviewed_clears_pending_and_logs_history(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)
    record_human_decision(tmp_path, sample_briefing.tender.id, "more_research", reviewer="jj", comment="Check X")

    state = mark_research_requests_reviewed(tmp_path, sample_briefing.tender.id)

    assert get_pending_research_requests(tmp_path, sample_briefing.tender.id) == []
    assert state["research_requests"][0]["status"] == "reviewed"
    assert state["research_requests"][0]["reviewed_at"] is not None
    assert state["history"][-1]["event"] == "research_reviewed"


def test_mark_research_requests_reviewed_is_a_noop_without_pending_requests(tmp_path, sample_briefing):
    update_state_after_qualification(tmp_path, sample_briefing)
    history_before = list(load_workflow_state(tmp_path, sample_briefing.tender.id)["history"])

    state = mark_research_requests_reviewed(tmp_path, sample_briefing.tender.id)

    assert state["history"] == history_before  # nothing to review -> no new event
