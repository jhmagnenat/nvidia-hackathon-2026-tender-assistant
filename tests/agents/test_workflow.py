from datetime import date

import pytest

from src.agents.workflow import WorkflowOrchestrator
from src.schemas.common import Recommendation, SelectionMode

_QUERY = "Find Swiss tenders related to cloud infrastructure, managed services and cybersecurity"
_RELEVANT_IDS = {"cloud-infra-2026", "cybersec-managed-2026", "datacenter-modernization-2026"}


def test_workflow_run_end_to_end_on_local_sample_data():
    orchestrator = WorkflowOrchestrator()
    briefing = orchestrator.run(_QUERY, as_of=date(2026, 9, 18))
    assert briefing.tender.id in _RELEVANT_IDS
    assert briefing.recommendation in (Recommendation.GO, Recommendation.MAYBE, Recommendation.NO_GO)
    assert briefing.citations  # every important fact should be traceable


def test_workflow_run_raises_on_no_matching_tenders():
    orchestrator = WorkflowOrchestrator()
    with pytest.raises(ValueError):
        orchestrator.run("xyzzy nonexistent query terms zzz")


def test_workflow_analyze_specific_tender_is_no_go():
    orchestrator = WorkflowOrchestrator()
    tenders = orchestrator.search("mobilier de bureau")
    assert tenders and tenders[0].id == "office-furniture-2026"
    briefing = orchestrator.analyze_tender(tenders[0], as_of=date(2026, 9, 18))
    assert briefing.recommendation == Recommendation.NO_GO


def test_workflow_analyze_tender_is_selection_mode_direct():
    """analyze_tender (search+pick-by-hand call sites like the CLI `analyze`
    command / app.py's per-card Analyze button) must be unaffected by
    automatic selection — no candidate comparison happened, so this must
    stay honestly "direct", never claim "auto"."""
    orchestrator = WorkflowOrchestrator()
    tenders = orchestrator.search("mobilier de bureau")
    briefing = orchestrator.analyze_tender(tenders[0], as_of=date(2026, 9, 18))
    assert briefing.selection_mode == SelectionMode.DIRECT
    assert briefing.alternatives == []
    assert briefing.selected_tender_id == tenders[0].id


def test_workflow_run_auto_selection_populates_selection_fields():
    orchestrator = WorkflowOrchestrator()
    briefing = orchestrator.run(_QUERY, as_of=date(2026, 9, 18))

    assert briefing.selection_mode == SelectionMode.AUTO
    assert briefing.selected_tender_id == briefing.tender.id
    assert briefing.tender.id in briefing.selection_reason  # grounded in the real winner, not generic text
    assert 1 <= len(briefing.alternatives) <= 3
    alt_ids = {a.tender_id for a in briefing.alternatives}
    assert briefing.tender.id not in alt_ids  # the winner is never also listed as its own alternative
    assert alt_ids <= _RELEVANT_IDS
    # alternatives must be sorted best-first
    scores = [a.relevance_score for a in briefing.alternatives]
    assert scores == sorted(scores, reverse=True)


def test_workflow_run_override_selects_the_requested_candidate():
    orchestrator = WorkflowOrchestrator()
    auto = orchestrator.run(_QUERY, as_of=date(2026, 9, 18))
    other_id = next(iter(_RELEVANT_IDS - {auto.tender.id}))

    overridden = orchestrator.run(_QUERY, as_of=date(2026, 9, 18), override_tender_id=other_id)

    assert overridden.selection_mode == SelectionMode.HUMAN_OVERRIDE
    assert overridden.tender.id == other_id
    assert overridden.selected_tender_id == other_id
    # the override reason stays traceable: it names both the override and what auto would have picked
    assert other_id in overridden.selection_reason
    assert auto.tender.id in overridden.selection_reason


def test_workflow_run_override_with_unknown_id_raises_value_error():
    orchestrator = WorkflowOrchestrator()
    with pytest.raises(ValueError):
        orchestrator.run(_QUERY, as_of=date(2026, 9, 18), override_tender_id="not-a-real-tender-id")
