"""BriefingAgent (Track C) — assembles the final QualificationBriefing.

Combines the eligibility gate result, the fit score, and the capability
matches into the structured output the brief asks for: executive summary,
score, recommendation, gaps, risks, unknowns, next actions, citations.

Recommendation logic (transparent, not left to model judgment):
- Any mandatory requirement with a confirmed NO_MATCH -> NO-GO, regardless of
  score (a hard, sourced gap should not be scored around).
- Any mandatory requirement still UNKNOWN (profile incomplete, not a
  confirmed gap) -> capped at MAYBE, even with a high score — we should not
  say GO while a mandatory item is unresolved.
- Otherwise: score >= 70 -> GO, score >= 45 -> MAYBE, else NO-GO.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.eligibility_gate import gate_has_hard_failure, gate_has_unknown
from src.schemas.briefing import (
    AlternativeTender,
    CapabilityMatch,
    HumanReview,
    QualificationBriefing,
    RiskFlag,
    ScoreBreakdown,
)
from src.schemas.common import Confidence, MatchStatus, Recommendation, SelectionMode
from src.schemas.tender import ExtractedTenderData

_GO_THRESHOLD = 70
_MAYBE_THRESHOLD = 45


def _recommendation(score: float, gate_matches: list[CapabilityMatch]) -> tuple[Recommendation, str]:
    if gate_has_hard_failure(gate_matches):
        failed = [m.requirement_description for m in gate_matches if m.status == MatchStatus.NO_MATCH]
        return (
            Recommendation.NO_GO,
            "Mandatory requirement(s) confirmed unmet, regardless of overall score: " + "; ".join(failed),
        )

    if gate_has_unknown(gate_matches):
        unresolved = [m.requirement_description for m in gate_matches if m.status == MatchStatus.UNKNOWN]
        capped = min(score, _GO_THRESHOLD - 0.01)
        if capped >= _MAYBE_THRESHOLD:
            return (
                Recommendation.MAYBE,
                f"Score is {score:.1f}/100, but capped at MAYBE because mandatory requirement(s) "
                "remain UNKNOWN against the HPE profile (not a confirmed gap, but not confirmed met "
                "either): " + "; ".join(unresolved),
            )
        return (
            Recommendation.NO_GO,
            f"Score is {score:.1f}/100 and mandatory requirement(s) remain UNKNOWN: " + "; ".join(unresolved),
        )

    if score >= _GO_THRESHOLD:
        return Recommendation.GO, f"Score {score:.1f}/100 meets the GO threshold ({_GO_THRESHOLD}) with all mandatory requirements resolved."
    if score >= _MAYBE_THRESHOLD:
        return Recommendation.MAYBE, f"Score {score:.1f}/100 is in the MAYBE range ({_MAYBE_THRESHOLD}-{_GO_THRESHOLD})."
    return Recommendation.NO_GO, f"Score {score:.1f}/100 is below the MAYBE threshold ({_MAYBE_THRESHOLD})."


def _confidence(score_breakdown: ScoreBreakdown) -> Confidence:
    info = score_breakdown.information_confidence  # out of 10
    if info >= 8:
        return Confidence.HIGH
    if info >= 4:
        return Confidence.MEDIUM
    return Confidence.LOW


def _risks(tender_data: ExtractedTenderData, all_matches: list[CapabilityMatch]) -> list[RiskFlag]:
    risks = [RiskFlag(severity="medium", description=r) for r in tender_data.risks]

    if tender_data.deadlines:
        deadline = tender_data.deadlines[0]
        days_left = (deadline.date - datetime.now(UTC).date()).days
        if days_left < 14:
            risks.append(
                RiskFlag(
                    severity="high",
                    description=f"Submission deadline in {days_left} day(s) — tight timeline for bid preparation.",
                    citation=deadline.citation,
                )
            )

    for match in all_matches:
        if match.status == MatchStatus.NO_MATCH:
            risks.append(
                RiskFlag(
                    severity="high",
                    description=f"Confirmed gap: {match.requirement_description}",
                    citation=match.citation,
                )
            )
    return risks


def _gaps_and_unknowns(all_matches: list[CapabilityMatch], tender_data: ExtractedTenderData) -> tuple[list[str], list[str]]:
    gaps = [m.requirement_description for m in all_matches if m.status == MatchStatus.NO_MATCH]
    unknowns = [m.requirement_description for m in all_matches if m.status == MatchStatus.UNKNOWN]
    unknowns.extend(tender_data.unknowns)
    return gaps, unknowns


def _next_actions(recommendation: Recommendation, gaps: list[str], unknowns: list[str]) -> list[str]:
    actions: list[str] = []
    if unknowns:
        actions.append(
            "Resolve UNKNOWN items by adding sourced entries (with a citation) to data/hpe_profile.json, "
            "or by confirming directly with the relevant HPE team."
        )
    if gaps:
        actions.append("Assess whether the confirmed gap(s) can be closed (subcontracting, certification in progress, etc.) before bidding.")
    if recommendation == Recommendation.GO:
        actions.append("Proceed to bid preparation and assign a bid owner.")
    elif recommendation == Recommendation.MAYBE:
        actions.append("Request more research/clarification before committing a bid team.")
    else:
        actions.append("Do not allocate bid resources unless the blocking gap(s) above are resolved.")
    return actions


def generate_briefing(
    tender_data: ExtractedTenderData,
    gate_matches: list[CapabilityMatch],
    score_breakdown: ScoreBreakdown,
    all_matches: list[CapabilityMatch],
    selection_mode: SelectionMode | None = None,
    selection_reason: str | None = None,
    alternatives: list[AlternativeTender] | None = None,
) -> QualificationBriefing:
    """Assemble the final QualificationBriefing from upstream agent outputs.

    `selection_mode`/`selection_reason`/`alternatives` are optional — left
    `None`, `QualificationBriefing`'s own defaults apply (`selection_mode`
    "direct", a generic honest reason, no alternatives), so every
    pre-existing caller is unaffected. Set by `src.agents.tender_selection`
    via `WorkflowOrchestrator.run`'s automatic-selection path.
    """
    score = round(score_breakdown.total, 1)
    recommendation, recommendation_reason = _recommendation(score, gate_matches)
    confidence = _confidence(score_breakdown)
    gaps, unknowns = _gaps_and_unknowns(all_matches, tender_data)
    risks = _risks(tender_data, all_matches)
    next_actions = _next_actions(recommendation, gaps, unknowns)
    citations = list(tender_data.citations)

    tender = tender_data.tender
    executive_summary = (
        f"{tender.title} ({tender.buyer or 'buyer UNKNOWN'}, {tender.location or 'location UNKNOWN'}). "
        f"Recommendation: {recommendation.value} (score {score:.1f}/100, confidence {confidence.value}). "
        f"{recommendation_reason}"
    )

    # Optional selection-metadata kwargs: only pass through what the caller
    # actually provided, so QualificationBriefing's own field defaults apply
    # exactly as before when none of it was given.
    selection_kwargs: dict = {}
    if selection_mode is not None:
        selection_kwargs["selection_mode"] = selection_mode
    if selection_reason is not None:
        selection_kwargs["selection_reason"] = selection_reason
    if alternatives is not None:
        selection_kwargs["alternatives"] = alternatives

    return QualificationBriefing(
        tender=tender,
        recommendation=recommendation,
        score=score,
        score_breakdown=score_breakdown,
        confidence=confidence,
        executive_summary=executive_summary,
        deadlines=tender_data.deadlines,
        mandatory_requirements=[
            *tender_data.mandatory_requirements,
            *[r for r in tender_data.eligibility_criteria if r.mandatory],
            *[r for r in tender_data.required_certifications if r.mandatory],
            *[r for r in tender_data.required_references if r.mandatory],
        ],
        capability_matches=all_matches,
        gaps=gaps,
        risks=risks,
        unknowns=unknowns,
        next_actions=next_actions,
        citations=citations,
        human_review=HumanReview(),
        generated_at=datetime.now(UTC),
        **selection_kwargs,
    )
