"""Human-approval / feedback recording — the workflow's last step.

Appends every approve/reject/more-research decision to a local JSON log
(data/feedback_log.json — runtime state, gitignored, not a fixture) and
attaches the HumanReview to the briefing itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.schemas.briefing import HumanDecision, HumanReview, QualificationBriefing

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = REPO_ROOT / "data" / "feedback_log.json"


def record_feedback(
    briefing: QualificationBriefing,
    decision: HumanDecision,
    reviewer: str | None = None,
    notes: str | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> HumanReview:
    review = HumanReview(decision=decision, reviewer=reviewer, notes=notes, timestamp=datetime.now(UTC))
    briefing.human_review = review

    entries: list[dict] = []
    if log_path.exists():
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    entries.append(
        {
            "tender_id": briefing.tender.id,
            "tender_title": briefing.tender.title,
            "recommendation": briefing.recommendation.value,
            "score": briefing.score,
            "human_review": review.model_dump(mode="json"),
        }
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return review
