"""Qualification briefing — the final output contract, produced by the HPEQualificationAgent."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from src.schemas.common import Citation, Confidence, MatchStatus, Recommendation, SelectionMode
from src.schemas.tender import Deadline, Requirement, Tender


class CapabilityMatch(BaseModel):
    requirement_id: str
    requirement_description: str
    status: MatchStatus
    hpe_capability: str | None = Field(default=None, description="Matched HPE capability/certification name, if any")
    justification: str
    citation: Citation | None = None


class RiskFlag(BaseModel):
    severity: Literal["low", "medium", "high"]
    description: str
    citation: Citation | None = None


class ScoreBreakdown(BaseModel):
    """Transparent point allocation. Max points: 30/25/15/10/10/10 = 100."""

    capability_fit: float = Field(..., ge=0, le=30)
    mandatory_requirement_fit: float = Field(..., ge=0, le=25)
    eligibility_fit: float = Field(..., ge=0, le=15)
    delivery_feasibility: float = Field(..., ge=0, le=10)
    strategic_relevance: float = Field(..., ge=0, le=10)
    information_confidence: float = Field(..., ge=0, le=10)
    explanation: str

    @property
    def total(self) -> float:
        return (
            self.capability_fit
            + self.mandatory_requirement_fit
            + self.eligibility_fit
            + self.delivery_feasibility
            + self.strategic_relevance
            + self.information_confidence
        )


class HumanDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MORE_RESEARCH = "more_research"


class HumanReview(BaseModel):
    decision: HumanDecision | None = None
    reviewer: str | None = None
    notes: str | None = None
    timestamp: datetime | None = None


class AlternativeTender(BaseModel):
    """A runner-up candidate from the same search, kept for traceability and
    manual override — see `src.agents.tender_selection`."""

    tender_id: str
    title: str
    relevance_score: float = Field(..., ge=0, le=100)
    rank: int = Field(..., ge=1, description="1 = best runner-up (i.e. rank 1 among the non-selected candidates)")


class QualificationBriefing(BaseModel):
    tender: Tender
    recommendation: Recommendation
    score: float = Field(..., ge=0, le=100)
    score_breakdown: ScoreBreakdown
    confidence: Confidence
    executive_summary: str
    deadlines: list[Deadline] = Field(default_factory=list)
    mandatory_requirements: list[Requirement] = Field(default_factory=list)
    capability_matches: list[CapabilityMatch] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    risks: list[RiskFlag] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    human_review: HumanReview = Field(default_factory=HumanReview)
    generated_at: datetime
    selection_mode: SelectionMode = Field(
        default=SelectionMode.DIRECT,
        description=(
            "How `tender` was chosen — 'auto' (automatic relevance-based selection among "
            "multiple search results), 'human_override' (a human explicitly picked a "
            "different candidate), or 'direct' (analyzed by id, no candidate comparison — "
            "the default, so every pre-existing call site is unaffected)."
        ),
    )
    selection_reason: str = Field(
        default="Tender was analyzed directly; no automatic multi-candidate selection was performed.",
        description=(
            "Human-readable explanation of why `tender` was selected. Always grounded in the "
            "actual computed relevance score/override once selection_mode is 'auto' or "
            "'human_override' — never a generic placeholder in those cases."
        ),
    )
    alternatives: list[AlternativeTender] = Field(
        default_factory=list,
        description="2-3 runner-up candidates considered but not selected, kept for traceability and override.",
    )

    @computed_field(description="Always equal to tender.id — included for convenient JSON access.")  # type: ignore[prop-decorator]
    @property
    def selected_tender_id(self) -> str:
        return self.tender.id
