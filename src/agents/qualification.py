"""HPEQualificationAgent — composes eligibility_gate + fit_scoring + briefing
into the single named interface the brief asks for.
"""

from __future__ import annotations

from datetime import date

from src.agents import briefing, eligibility_gate, fit_scoring
from src.schemas.briefing import QualificationBriefing
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import ExtractedTenderData


def qualify_tender(
    tender_data: ExtractedTenderData, profile: HPEProfile, as_of: date | None = None
) -> QualificationBriefing:
    """tender + requirements are both carried on `tender_data` (ExtractedTenderData.tender)."""
    gate_matches = eligibility_gate.run_eligibility_gate(tender_data, profile)
    score_breakdown, all_matches = fit_scoring.score_fit(tender_data, profile, gate_matches, as_of=as_of)
    return briefing.generate_briefing(tender_data, gate_matches, score_breakdown, all_matches)


class HPEQualificationAgent:
    def qualify_tender(
        self, tender_data: ExtractedTenderData, profile: HPEProfile, as_of: date | None = None
    ) -> QualificationBriefing:
        return qualify_tender(tender_data, profile, as_of=as_of)
