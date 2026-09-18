import json

from src.agents.feedback import record_feedback
from src.schemas.briefing import HumanDecision


def test_record_feedback_appends_and_attaches_review(tmp_path, sample_briefing):
    log_path = tmp_path / "feedback_log.json"
    review = record_feedback(
        sample_briefing, HumanDecision.APPROVED, reviewer="jj", notes="looks good", log_path=log_path
    )

    assert review.decision == HumanDecision.APPROVED
    assert sample_briefing.human_review.decision == HumanDecision.APPROVED

    entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["tender_id"] == sample_briefing.tender.id
    assert entries[0]["human_review"]["reviewer"] == "jj"


def test_record_feedback_appends_to_existing_log(tmp_path, sample_briefing):
    log_path = tmp_path / "feedback_log.json"
    record_feedback(sample_briefing, HumanDecision.MORE_RESEARCH, log_path=log_path)
    record_feedback(sample_briefing, HumanDecision.REJECTED, log_path=log_path)

    entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(entries) == 2
    assert entries[-1]["human_review"]["decision"] == "rejected"
