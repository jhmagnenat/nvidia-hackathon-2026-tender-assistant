"""HPEQualificationAgent — composes eligibility_gate + fit_scoring + briefing
into the single named interface the brief asks for.
"""

from __future__ import annotations

from datetime import date

from src.agents import briefing, eligibility_gate, fit_scoring
from src.schemas.briefing import AlternativeTender, QualificationBriefing
from src.schemas.common import SelectionMode
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import ExtractedTenderData


def qualify_tender(
    tender_data: ExtractedTenderData,
    profile: HPEProfile,
    as_of: date | None = None,
    selection_mode: SelectionMode | None = None,
    selection_reason: str | None = None,
    alternatives: list[AlternativeTender] | None = None,
) -> QualificationBriefing:
    """tender + requirements are both carried on `tender_data` (ExtractedTenderData.tender).

    `selection_mode`/`selection_reason`/`alternatives` are optional pass-throughs
    to `briefing.generate_briefing` (see `src.agents.tender_selection` and
    `WorkflowOrchestrator.run`) — left `None` here, every pre-existing call
    site (CLI `analyze`, `WorkflowOrchestrator.analyze_tender`) is unaffected
    and the resulting briefing keeps its honest `selection_mode="direct"` default.
    """
    gate_matches = eligibility_gate.run_eligibility_gate(tender_data, profile)
    score_breakdown, all_matches = fit_scoring.score_fit(tender_data, profile, gate_matches, as_of=as_of)
    return briefing.generate_briefing(
        tender_data,
        gate_matches,
        score_breakdown,
        all_matches,
        selection_mode=selection_mode,
        selection_reason=selection_reason,
        alternatives=alternatives,
    )


class HPEQualificationAgent:
    def qualify_tender(
        self,
        tender_data: ExtractedTenderData,
        profile: HPEProfile,
        as_of: date | None = None,
        selection_mode: SelectionMode | None = None,
        selection_reason: str | None = None,
        alternatives: list[AlternativeTender] | None = None,
    ) -> QualificationBriefing:
        return qualify_tender(
            tender_data,
            profile,
            as_of=as_of,
            selection_mode=selection_mode,
            selection_reason=selection_reason,
            alternatives=alternatives,
        )
