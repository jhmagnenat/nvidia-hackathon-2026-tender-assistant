"""Workflow state — a small, deterministic, per-`tender_id` JSON record that
persists business status across MCP tool calls / conversation turns, so a
caller can ask "where are we on tender X" (qualification result, human
review status, prior research requests) without re-running `qualify_tender`
or re-reading the full `data/briefings/<id>.json` briefing every time.

Persistence: one plain JSON file per tender_id under
`data/workflow_state/<tender_id>.json` (see `src/mcp_server.py`'s
`WORKFLOW_STATE_DIR`) — no new database/store technology, same "one JSON
file per id" pattern `data/briefings/`/`data/drafts/` already use.
Deliberately a *separate* file from `data/briefings/<id>.json`: that file's
exact shape (the raw `QualificationBriefing` dump) is depended on byte-for-
byte by `create_draft`/`_render_readiness_memo` in `src/mcp_server.py` —
this module never reads or writes it, so nothing about that existing
contract changes.

Never a second scoring/matching engine and never invents anything: every
field here is copied from an already-produced `QualificationBriefing`
(score, recommendation, confidence, tender.source_type, gaps, unknowns) or
from an already-validated `HumanDecision` string — see
src/agents/matching.py, fit_scoring.py, briefing.py, all untouched by this
module. The compact `executive_summary` sub-object reuses
`src.agents.executive_summary.build_executive_summary` unmodified (no
dedup/truncation logic duplicated here).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.executive_summary import HUMAN_REVIEW_LABELS, build_executive_summary
from src.schemas.briefing import HumanDecision, QualificationBriefing


def _state_path(state_dir: Path, tender_id: str) -> Path:
    return state_dir / f"{tender_id}.json"


def load_workflow_state(state_dir: Path, tender_id: str) -> dict[str, Any] | None:
    """None when no state has ever been recorded for this tender_id —
    never fabricated, the caller decides what "no state yet" means."""
    path = _state_path(state_dir, tender_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save(state_dir: Path, state: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    _state_path(state_dir, state["tender_id"]).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _new_state(tender_id: str) -> dict[str, Any]:
    return {
        "tender_id": tender_id,
        "source_type": None,
        "documents_status": None,
        "qualification_status": None,
        "score": None,
        "recommendation": None,
        "confidence": None,
        "blockers": [],
        "unknowns": [],
        "research_requests": [],
        "human_review": {
            "status": "HUMAN_REVIEW_PENDING",
            "decision": None,
            "comment": None,
            "reviewer": None,
            "timestamp": None,
        },
        "history": [],
        "executive_summary": None,
    }


def _append_history(state: dict[str, Any], event: str, detail: str | None = None) -> None:
    state["history"].append({"event": event, "timestamp": datetime.now(UTC).isoformat(), "detail": detail})


def update_state_after_qualification(
    state_dir: Path,
    briefing: QualificationBriefing,
    qualification_status: str = "COMPLETE",
) -> dict[str, Any]:
    """Persist/update the state after a real qualify_tender/create_briefing
    run (rule 2).

    Creates the state on first call for this tender_id; otherwise merges
    into the existing record — `human_review`/`research_requests`/`history`
    from any earlier turn are preserved, never wiped by a later
    qualification re-run (only the qualification-derived fields below are
    refreshed). `blockers`/`unknowns` are copied in full from `briefing.gaps`/
    `briefing.unknowns` — nothing truncated or deduplicated here (that's
    only done for the compact `executive_summary` sub-object, via the
    unmodified `build_executive_summary`), so no UNKNOWN item is ever lost
    from this record (rule: "conserver les UNKNOWN").
    """
    tender_id = briefing.tender.id
    state = load_workflow_state(state_dir, tender_id) or _new_state(tender_id)

    exec_summary = build_executive_summary(briefing, qualification_status=qualification_status)

    state["source_type"] = briefing.tender.source_type
    state["documents_status"] = "RETRIEVED"
    state["qualification_status"] = qualification_status
    state["score"] = briefing.score
    state["recommendation"] = briefing.recommendation.value
    state["confidence"] = briefing.confidence.value
    state["blockers"] = list(briefing.gaps)
    state["unknowns"] = list(briefing.unknowns)
    state["executive_summary"] = {
        "recommendation": exec_summary["recommendation"],
        "score": exec_summary["score"],
        "confidence": exec_summary["confidence"],
        "blockers": exec_summary["blockers"],
        "risks": exec_summary["risks"],
        "next_actions": exec_summary["next_actions"],
        "human_review_status": exec_summary["human_review_status"],
    }
    _append_history(
        state, "qualification_complete", f"{state['recommendation']} (score {state['score']}/100)"
    )
    _save(state_dir, state)
    return state


def record_human_decision(
    state_dir: Path,
    tender_id: str,
    decision: str,
    reviewer: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Persist a human reviewer's approved/rejected/more_research decision
    (rules 3 and 4) — `decision` must already be a validated
    `HumanDecision` value (see src/mcp_server.py's `submit_human_decision`,
    which checks this before calling here; never guessed/defaulted).

    Never erases the qualification fields (`score`/`recommendation`/
    `blockers`/`unknowns`/`qualification_status`) a prior
    `update_state_after_qualification` call already recorded — only
    `human_review`/`research_requests`/`history` change here, so the
    original recommendation/score stay exactly as qualify_tender computed
    them regardless of which decision comes in (rule 4: "conserver la
    recommandation originale"). A "more_research" decision additionally
    appends to `research_requests` — the prior briefing/state is not
    cleared (rule 3).
    """
    state = load_workflow_state(state_dir, tender_id) or _new_state(tender_id)
    timestamp = datetime.now(UTC).isoformat()

    # Same "HUMAN_REVIEW_..." vocabulary build_executive_summary already
    # uses (and the executive_card renders) — one label set, not two.
    status_label = HUMAN_REVIEW_LABELS.get(decision, f"HUMAN_REVIEW_{decision.upper()}")
    state["human_review"] = {
        "status": status_label,
        "decision": decision,
        "comment": comment,
        "reviewer": reviewer,
        "timestamp": timestamp,
    }
    if state["executive_summary"] is not None:
        state["executive_summary"]["human_review_status"] = status_label

    if decision == HumanDecision.MORE_RESEARCH.value:
        state["research_requests"].append({"requested_at": timestamp, "reviewer": reviewer, "note": comment})
        _append_history(state, "research_requested", comment)
    else:
        _append_history(state, "human_decision", decision + (f" — {comment}" if comment else ""))

    _save(state_dir, state)
    return state
