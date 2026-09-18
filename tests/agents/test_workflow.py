from datetime import date

import pytest

from src.agents.workflow import WorkflowOrchestrator
from src.schemas.common import Recommendation


def test_workflow_run_end_to_end_on_local_sample_data():
    orchestrator = WorkflowOrchestrator()
    briefing = orchestrator.run(
        "Find Swiss tenders related to cloud infrastructure, managed services and cybersecurity",
        as_of=date(2026, 9, 18),
    )
    assert briefing.tender.id in {"cloud-infra-2026", "cybersec-managed-2026", "datacenter-modernization-2026"}
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
