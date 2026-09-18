"""FitScoring (Track B) — transparent 0-100 qualification score.

Six weighted dimensions (30/25/15/10/10/10 = 100), each independently
explainable — see ScoreBreakdown. No LLM call: capability matching reuses
matching.py's deterministic keyword-overlap matcher; delivery feasibility is
computed from the submission deadline; strategic relevance and information
confidence are computed from the same matches and the HPE capability list.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.agents.matching import match_all, significant_tokens
from src.schemas.briefing import CapabilityMatch, ScoreBreakdown
from src.schemas.common import MatchStatus
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import ExtractedTenderData, Requirement

_STATUS_VALUE = {
    MatchStatus.MATCH: 1.0,
    MatchStatus.PARTIAL_MATCH: 0.5,
    MatchStatus.UNKNOWN: 0.35,
    MatchStatus.NO_MATCH: 0.0,
}


def _dimension_score(
    requirements: list[Requirement], matches_by_id: dict[str, CapabilityMatch], max_points: float
) -> float:
    if not requirements:
        return round(max_points * 0.5, 1)  # neutral: this tender states none of these

    weighted_sum = 0.0
    total_weight = 0.0
    for requirement in requirements:
        match = matches_by_id.get(requirement.id)
        value = _STATUS_VALUE[match.status] if match else _STATUS_VALUE[MatchStatus.UNKNOWN]
        weight = requirement.weight_percent if requirement.weight_percent else 1.0
        weighted_sum += value * weight
        total_weight += weight

    ratio = weighted_sum / total_weight if total_weight else 0.5
    return round(max_points * ratio, 1)


def _delivery_feasibility(tender_data: ExtractedTenderData, max_points: float, as_of: date | None = None) -> float:
    as_of = as_of or datetime.now(UTC).date()
    deadline = tender_data.deadlines[0].date if tender_data.deadlines else tender_data.tender.submission_deadline
    if deadline is None:
        return round(max_points * 0.5, 1)

    days_left = (deadline - as_of).days
    if days_left < 0:
        return 0.0
    if days_left < 14:
        return round(max_points * 0.3, 1)
    if days_left < 30:
        return round(max_points * 0.6, 1)
    return round(max_points, 1)


def _strategic_relevance(tender_data: ExtractedTenderData, profile: HPEProfile, max_points: float) -> float:
    if not profile.capabilities:
        return round(max_points * 0.5, 1)

    text = f"{tender_data.tender.title} {tender_data.tender.scope or ''}"
    tender_tokens = significant_tokens(text)
    if not tender_tokens:
        return round(max_points * 0.5, 1)

    matched = sum(
        1
        for cap in profile.capabilities
        if tender_tokens & significant_tokens(f"{cap.name} {cap.description or ''}")
    )
    ratio = min(matched / len(profile.capabilities), 1.0)
    return round(max_points * ratio, 1)


def _information_confidence(all_matches: list[CapabilityMatch], max_points: float) -> float:
    if not all_matches:
        return round(max_points * 0.5, 1)
    resolved = sum(1 for m in all_matches if m.status != MatchStatus.UNKNOWN)
    ratio = resolved / len(all_matches)
    return round(max_points * ratio, 1)


def score_fit(
    tender_data: ExtractedTenderData,
    profile: HPEProfile,
    gate_matches: list[CapabilityMatch],
    as_of: date | None = None,
) -> tuple[ScoreBreakdown, list[CapabilityMatch]]:
    """Score every requirement category for HPE fit.

    `gate_matches` are the already-computed mandatory-requirement matches from
    eligibility_gate.run_eligibility_gate (reused here, not recomputed).
    Returns the transparent ScoreBreakdown plus the full list of
    CapabilityMatch (gate matches + technical/commercial/evaluation/reference
    matches) for the briefing agent to render.
    """
    # commercial_requirements and evaluation_criteria are contractual/administrative
    # terms (contract duration, price weighting, ...), not capability questions — they
    # are not run through capability matching, so they never show up as false "gaps".
    capability_requirements = [*tender_data.technical_requirements, *tender_data.required_references]
    other_matches = match_all(capability_requirements, profile)
    all_matches = gate_matches + other_matches
    matches_by_id = {m.requirement_id: m for m in all_matches}

    capability_fit = _dimension_score(capability_requirements, matches_by_id, 30)
    mandatory_requirement_fit = _dimension_score(
        [*tender_data.mandatory_requirements, *tender_data.required_certifications], matches_by_id, 25
    )
    eligibility_fit = _dimension_score(tender_data.eligibility_criteria, matches_by_id, 15)
    delivery_feasibility = _delivery_feasibility(tender_data, 10, as_of)
    strategic_relevance = _strategic_relevance(tender_data, profile, 10)
    information_confidence = _information_confidence(all_matches, 10)

    explanation = (
        f"Capability fit {capability_fit:.1f}/30 (technical/commercial/evaluation/reference match quality); "
        f"mandatory requirement fit {mandatory_requirement_fit:.1f}/25; "
        f"eligibility fit {eligibility_fit:.1f}/15; "
        f"delivery feasibility {delivery_feasibility:.1f}/10 (time to deadline); "
        f"strategic relevance {strategic_relevance:.1f}/10 (overlap with HPE's stated capabilities); "
        f"information confidence {information_confidence:.1f}/10 (share of requirements resolved, not UNKNOWN)."
    )

    breakdown = ScoreBreakdown(
        capability_fit=capability_fit,
        mandatory_requirement_fit=mandatory_requirement_fit,
        eligibility_fit=eligibility_fit,
        delivery_feasibility=delivery_feasibility,
        strategic_relevance=strategic_relevance,
        information_confidence=information_confidence,
        explanation=explanation,
    )
    return breakdown, all_matches
