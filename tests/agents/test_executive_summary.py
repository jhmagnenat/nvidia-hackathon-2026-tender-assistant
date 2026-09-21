from datetime import UTC, date, datetime

from src.agents.briefing import generate_briefing
from src.agents.eligibility_gate import run_eligibility_gate
from src.agents.executive_summary import build_executive_summary, render_executive_card
from src.agents.fit_scoring import score_fit
from src.schemas.briefing import QualificationBriefing, ScoreBreakdown
from src.schemas.common import Confidence, Recommendation
from src.schemas.tender import Tender, TenderSource


def test_build_executive_summary_has_score_and_recommendation(sample_briefing):
    summary = build_executive_summary(sample_briefing)

    assert summary["recommendation"] == sample_briefing.recommendation.value
    assert summary["score"] == sample_briefing.score
    assert summary["confidence"] == sample_briefing.confidence.value
    assert summary["title"] == sample_briefing.tender.title


def test_build_executive_summary_human_review_pending_by_default(sample_briefing):
    """sample_briefing's human_review defaults to no decision yet — the
    compact card must say so explicitly, not omit the fact."""
    assert sample_briefing.human_review.decision is None

    summary = build_executive_summary(sample_briefing)

    assert summary["human_review_status"] == "HUMAN_REVIEW_PENDING"
    assert summary["workflow_status"]["human_review"] == "HUMAN_REVIEW_PENDING"


def test_build_executive_summary_dedups_iso_27001(sample_extracted, sample_hpe_profile):
    """Regression for the reported example: sample_extracted carries the
    SAME ISO/IEC 27001 requirement twice — once as the full mandatory
    sentence ("ISO/IEC 27001 certification required."), once as the short
    CERTIFICATIONS REQUISES bullet ("ISO/IEC 27001") — both UNKNOWN against
    sample_hpe_profile (no certifications listed). The executive_summary
    must show this once, not twice."""
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, all_matches = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    briefing = generate_briefing(sample_extracted, gate_matches, breakdown, all_matches)

    summary = build_executive_summary(briefing)

    iso_mentions = [b for b in summary["blockers"] if "iso" in b.lower() and "27001" in b.lower()]
    assert len(iso_mentions) == 1
    # The original briefing data is untouched -- both entries are still there.
    assert sum("27001" in u.lower() for u in briefing.unknowns) >= 2


def _briefing_with_many_items(**overrides) -> QualificationBriefing:
    breakdown = ScoreBreakdown(
        capability_fit=20,
        mandatory_requirement_fit=20,
        eligibility_fit=10,
        delivery_feasibility=8,
        strategic_relevance=7,
        information_confidence=5,
        explanation="Example.",
    )
    tender = Tender(
        id="many-items-2026",
        title="Synthetic tender with many gaps",
        buyer="Test buyer",
        source=TenderSource.LOCAL_SAMPLE,
    )
    defaults = {
        "tender": tender,
        "recommendation": Recommendation.MAYBE,
        "score": 55,
        "score_breakdown": breakdown,
        "confidence": Confidence.MEDIUM,
        "executive_summary": "Example summary.",
        "generated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return QualificationBriefing(**defaults)


def test_build_executive_summary_limits_blockers_to_four():
    briefing = _briefing_with_many_items(
        gaps=["Gap A", "Gap B", "Gap C"],
        unknowns=["Unknown D", "Unknown E", "Unknown F"],
    )

    summary = build_executive_summary(briefing)

    assert len(summary["blockers"]) <= 4
    # gaps (✗) first, then unknowns (?), in order -- each keeps its own symbol.
    assert summary["blockers"] == ["✗ Gap A", "✗ Gap B", "✗ Gap C", "? Unknown D"]


def test_build_executive_summary_limits_risks_and_next_actions_and_fit_signals():
    from src.schemas.briefing import CapabilityMatch, RiskFlag
    from src.schemas.common import MatchStatus

    briefing = _briefing_with_many_items(
        risks=[RiskFlag(severity="low", description=f"Risk {i}") for i in range(5)],
        next_actions=[f"Action {i}" for i in range(5)],
        capability_matches=[
            CapabilityMatch(requirement_id=f"r{i}", requirement_description=f"Fit {i}", status=MatchStatus.MATCH, justification="x")
            for i in range(6)
        ],
    )

    summary = build_executive_summary(briefing)

    assert len(summary["risks"]) <= 3
    assert len(summary["next_actions"]) <= 3
    assert len(summary["fit_signals"]) <= 4


def test_data_origin_distinguishes_live_simap_synthetic_sample_and_local_fallback():
    """The 3-way label a local tender must never be confused with a live
    one, and a synthetic demo fixture must never be confused with a
    generic non-SIMAP fallback (e.g. Tavily) either."""
    live = _briefing_with_many_items(tender=Tender(id="t-live", title="Live", source=TenderSource.SIMAP))
    synthetic = _briefing_with_many_items(tender=Tender(id="t-sample", title="Sample", source=TenderSource.LOCAL_SAMPLE))
    other_fallback = _briefing_with_many_items(tender=Tender(id="t-tavily", title="Tavily", source=TenderSource.TAVILY))

    live_summary = build_executive_summary(live)
    synthetic_summary = build_executive_summary(synthetic)
    fallback_summary = build_executive_summary(other_fallback)

    assert live_summary["workflow_status"]["simap"] == "LIVE"
    assert live_summary["workflow_status"]["local_fallback"] == "NOT_USED"

    assert synthetic_summary["workflow_status"]["simap"] == "NOT_USED"
    assert synthetic_summary["workflow_status"]["local_fallback"] == "SYNTHETIC_SAMPLE"

    assert fallback_summary["workflow_status"]["simap"] == "NOT_USED"
    assert fallback_summary["workflow_status"]["local_fallback"] == "USED"


def test_render_executive_card_distinguishes_origin_labels():
    live_card = render_executive_card(build_executive_summary(_briefing_with_many_items(
        tender=Tender(id="t-live", title="Live tender", source=TenderSource.SIMAP)
    )))
    sample_card = render_executive_card(build_executive_summary(_briefing_with_many_items(
        tender=Tender(id="t-sample", title="Sample tender", source=TenderSource.LOCAL_SAMPLE)
    )))
    fallback_card = render_executive_card(build_executive_summary(_briefing_with_many_items(
        tender=Tender(id="t-tavily", title="Tavily tender", source=TenderSource.TAVILY)
    )))

    assert "LIVE_SIMAP" in live_card
    assert "SYNTHETIC_SAMPLE" in sample_card
    assert "LOCAL_FALLBACK" in fallback_card
    assert "LIVE_SIMAP" not in sample_card
    assert "LIVE_SIMAP" not in fallback_card


def test_render_executive_card_contains_required_sections(sample_briefing):
    summary = build_executive_summary(sample_briefing)
    card = render_executive_card(summary)

    assert sample_briefing.tender.title in card
    assert "RECOMMENDATION:" in card
    assert "SCORE:" in card
    assert "WORKFLOW:" in card
    assert "SELECTED TENDER:" in card
    assert "CAPABILITY SIGNALS:" in card
    assert "! BLOCKERS:" in card
    assert "HUMAN REVIEW:" in card
    assert "HUMAN_REVIEW_PENDING" in card


def test_build_executive_summary_uses_required_symbols():
    """Rule 4 -- ✓ MATCH, ◐ PARTIAL_MATCH, ? UNKNOWN, ✗ NO_MATCH, and a "!"
    marker for the blockers section."""
    from src.schemas.briefing import CapabilityMatch
    from src.schemas.common import MatchStatus

    briefing = _briefing_with_many_items(
        gaps=["Confirmed gap"],
        unknowns=["Unresolved item"],
        capability_matches=[
            CapabilityMatch(requirement_id="m", requirement_description="Cloud infrastructure capability", status=MatchStatus.MATCH, justification="x"),
            CapabilityMatch(requirement_id="p", requirement_description="Networking support offering", status=MatchStatus.PARTIAL_MATCH, justification="x"),
        ],
    )

    summary = build_executive_summary(briefing)

    assert summary["fit_signals"] == ["✓ Cloud infrastructure capability", "◐ Networking support offering"]
    assert summary["blockers"] == ["✗ Confirmed gap", "? Unresolved item"]

    card = render_executive_card(summary)
    assert "! BLOCKERS:" in card


def test_build_executive_summary_preserves_unknown_distinct_from_no_match():
    """Rule 9 ("UNKNOWN préservé") -- a confirmed NO_MATCH gap and a merely
    unresolved UNKNOWN item must never be collapsed into the same generic
    marker; each keeps its own symbol so the distinction stays visible."""
    briefing = _briefing_with_many_items(
        gaps=["A confirmed capability gap"],
        unknowns=["An item the HPE profile can't yet confirm or deny"],
    )

    summary = build_executive_summary(briefing)

    assert "✗ A confirmed capability gap" in summary["blockers"]
    assert "? An item the HPE profile can't yet confirm or deny" in summary["blockers"]


def test_build_executive_summary_never_mutates_the_original_briefing(sample_extracted, sample_hpe_profile):
    gate_matches = run_eligibility_gate(sample_extracted, sample_hpe_profile)
    breakdown, all_matches = score_fit(sample_extracted, sample_hpe_profile, gate_matches, as_of=date(2026, 9, 18))
    briefing = generate_briefing(sample_extracted, gate_matches, breakdown, all_matches)
    unknowns_before = list(briefing.unknowns)
    gaps_before = list(briefing.gaps)

    build_executive_summary(briefing)

    assert briefing.unknowns == unknowns_before
    assert briefing.gaps == gaps_before
