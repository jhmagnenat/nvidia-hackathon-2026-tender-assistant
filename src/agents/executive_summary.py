"""Executive summary — a compact, deterministic VIEW over an already-produced
QualificationBriefing, plus a plain-text ASCII rendering of it.

Purpose: let Hermes/NemoClaw (or any other caller) show a short, honest
status at a glance without needing a long presentation prompt reconstructed
every conversation — see src/mcp_server.py's `qualify_tender`/`create_briefing`/
`submit_human_decision`, which attach this module's output to their response.

Strictly a view, never a second scoring/matching engine:
- Never recomputes score, recommendation, confidence, or any MatchStatus —
  all already final on `briefing` (src/agents/briefing.py, fit_scoring.py,
  eligibility_gate.py, matching.py are untouched by this module).
- Never mutates `briefing` — `gaps`/`unknowns`/`risks`/`next_actions` keep
  every original entry for full traceability; only the *summary* is
  deduplicated/truncated for display.
- Only ever surfaces data already present on `briefing`/`briefing.tender`.
  The only HPE-capability-shaped facts allowed through (`fit_signals`) are
  `capability_matches` entries already resolved to MATCH/PARTIAL_MATCH by
  src/agents/matching.py — which itself never asserts a certification/
  reference/insurance MATCH without a sourced data/hpe_profile.json entry
  (see that module's `_certification_match`/`_reference_match`/
  `_insurance_match`). No certification, reference, legal presence,
  financial figure, security clearance, data residency claim, or HPE
  product is invented here.
"""

from __future__ import annotations

from typing import Any

from src.schemas.briefing import QualificationBriefing
from src.schemas.common import MatchStatus
from src.schemas.tender import TenderSource

_MAX_FIT_SIGNALS = 4
_MAX_BLOCKERS = 4
_MAX_RISKS = 3
_MAX_NEXT_ACTIONS = 3

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Required symbols (per-item, prefixed onto each fit_signal/blocker string):
# MatchStatus.MATCH/PARTIAL_MATCH for fit_signals, NO_MATCH/UNKNOWN for
# blockers — the same MatchStatus values matching.py already computed,
# never re-derived or guessed here.
_SYMBOL_MATCH = "✓"  # ✓ CHECK MARK
_SYMBOL_PARTIAL_MATCH = "◐"  # ◐ CIRCLE WITH LEFT HALF BLACK
_SYMBOL_UNKNOWN = "?"
_SYMBOL_NO_MATCH = "✗"  # ✗ BALLOT X
_SYMBOL_BLOCKER_SECTION = "!"

# HumanDecision.value ("approved"/"rejected"/"more_research") -> label;
# None (no decision recorded yet) is the default/most common case for a
# fresh qualify_tender/create_briefing result.
HUMAN_REVIEW_LABELS = {
    None: "HUMAN_REVIEW_PENDING",
    "approved": "HUMAN_REVIEW_APPROVED",
    "rejected": "HUMAN_REVIEW_REJECTED",
    "more_research": "HUMAN_REVIEW_MORE_RESEARCH",
}


def _dedup_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Order-preserving de-duplication for display only, by `text` alone —
    the `symbol` tags along with whichever occurrence is kept (first-seen).

    Two entries are treated as the same underlying fact when one `text` is
    a case-insensitive substring of the other — e.g. a mandatory
    requirement's full sentence ("Le soumissionnaire doit disposer d'une
    certification ISO/IEC 27001 valide.") and the corresponding short
    CERTIFICATIONS REQUISES entry ("ISO/IEC 27001") both describe the same
    real requirement, extracted as two separate `Requirement` objects
    because they come from two different cahier-des-charges sections (see
    src/agents/ingestion.py's `_SECTION_HEADERS`). Keyword-overlap matching
    (matching.py's `significant_tokens`) can't catch this specific pair:
    "ISO"/"IEC" are 3 letters and "27001" is digits-only, all below that
    tokenizer's 4-letter-word minimum — so this uses plain substring
    containment instead, which is simple, deterministic, and sufficient for
    a short display list (not a general-purpose semantic dedup). Matching is
    done on `text` only (never on the symbol-prefixed string), so a NO_MATCH
    ("✗") and an UNKNOWN ("?") duplicate of the same fact still collapse to
    one entry — first-seen wins, so a confirmed gap (✗, checked first) is
    kept over a merely-unresolved duplicate (?), never the other way round.
    """
    kept: list[tuple[str, str]] = []
    for symbol, raw in pairs:
        text = raw.strip()
        if not text:
            continue
        lowered = text.lower()
        if any(lowered in k_text.lower() or k_text.lower() in lowered for _, k_text in kept):
            continue
        kept.append((symbol, text))
    return kept


def _dedup_limit_pairs(pairs: list[tuple[str, str]], limit: int) -> list[str]:
    """`_dedup_pairs` + truncate + render each surviving pair as "symbol text"."""
    return [f"{symbol} {text}" for symbol, text in _dedup_pairs(pairs)[:limit]]


def _dedup_limit(items: list[str], limit: int) -> list[str]:
    """Same de-duplication as `_dedup_pairs`, for plain (symbol-less) text
    lists — used for risks/next_actions, which rule 4's symbol set doesn't
    cover and which the executive_card doesn't render."""
    return [text for _, text in _dedup_pairs([("", item) for item in items])[:limit]]


def _data_origin(tender_source: TenderSource) -> str:
    """The 3-way provenance label a caller needs to never confuse a
    synthetic demo fixture, or any other non-live fallback, with a real
    live SIMAP result — derived only from the already-existing
    `Tender.source` field (TenderSource: simap/tavily/local_sample), never
    invented or guessed:
    - LIVE_SIMAP: a real, live SIMAP search result (source == "simap").
    - SYNTHETIC_SAMPLE: one of the committed hackathon-demo fixtures under
      data/sample_tenders/ (source == "local_sample" — see
      data/sample_tenders/README.md, which calls these "synthetic,
      hackathon-demo data" explicitly).
    - LOCAL_FALLBACK: any other non-live source (e.g. Tavily)."""
    if tender_source == TenderSource.SIMAP:
        return "LIVE_SIMAP"
    if tender_source == TenderSource.LOCAL_SAMPLE:
        return "SYNTHETIC_SAMPLE"
    return "LOCAL_FALLBACK"


def build_executive_summary(briefing: QualificationBriefing, qualification_status: str = "COMPLETE") -> dict[str, Any]:
    """Compact, deterministic view of an already-produced QualificationBriefing.

    Only ever meaningful for a briefing that actually completed (documents
    were retrieved and extraction/matching/scoring/briefing all ran for
    real) — there is deliberately no "BLOCKED" executive_summary: when
    documents can't be retrieved at all, src/mcp_server.py's own
    `_documents_blocked` already reports that, and there is no
    QualificationBriefing yet to summarize.
    """
    tender = briefing.tender
    deadline = briefing.deadlines[0].date if briefing.deadlines else tender.submission_deadline

    origin = _data_origin(tender.source)
    decision = briefing.human_review.decision
    human_review_status = HUMAN_REVIEW_LABELS.get(decision.value if decision else None, "HUMAN_REVIEW_PENDING")

    # Rule 4: ✓/◐ per fit signal, taken straight from matching.py's own
    # already-computed MatchStatus — never re-derived, never guessed. MATCH
    # entries sort before PARTIAL_MATCH so truncation to _MAX_FIT_SIGNALS
    # keeps the strongest signals first.
    fit_signals = _dedup_limit_pairs(
        [
            (_SYMBOL_MATCH if m.status == MatchStatus.MATCH else _SYMBOL_PARTIAL_MATCH, m.requirement_description)
            for m in sorted(briefing.capability_matches, key=lambda m: 0 if m.status == MatchStatus.MATCH else 1)
            if m.status in (MatchStatus.MATCH, MatchStatus.PARTIAL_MATCH)
        ],
        _MAX_FIT_SIGNALS,
    )
    # No separate "unknowns" slot in this compact card — confirmed gaps
    # (NO_MATCH, "✗") and unresolved items (UNKNOWN, "?") are both things
    # blocking a clean GO, so both feed "blockers" here, gaps first
    # (confirmed, more severe) then unknowns (unresolved) — deduplicated
    # together on text (see _dedup_pairs), which is exactly what catches the
    # ISO/IEC 27001 long-sentence/short-bullet pair (both UNKNOWN here,
    # since data/hpe_profile.json ships no certifications — see
    # matching.py's `_certification_match`). Each entry keeps its own real
    # status symbol rather than collapsing to one generic marker, so a
    # confirmed gap is never visually indistinguishable from a merely
    # unresolved UNKNOWN.
    blockers = _dedup_limit_pairs(
        [*((_SYMBOL_NO_MATCH, g) for g in briefing.gaps), *((_SYMBOL_UNKNOWN, u) for u in briefing.unknowns)],
        _MAX_BLOCKERS,
    )
    risks = _dedup_limit(
        [r.description for r in sorted(briefing.risks, key=lambda r: _SEVERITY_RANK.get(r.severity, 3))],
        _MAX_RISKS,
    )
    next_actions = _dedup_limit(list(briefing.next_actions), _MAX_NEXT_ACTIONS)

    return {
        "title": tender.title,
        "authority": tender.buyer,
        "deadline": deadline.isoformat() if deadline else None,
        "source_type": tender.source_type,
        "qualification_status": qualification_status,
        "recommendation": briefing.recommendation.value,
        "score": briefing.score,
        "confidence": briefing.confidence.value,
        "workflow_status": {
            "simap": "LIVE" if origin == "LIVE_SIMAP" else "NOT_USED",
            "local_fallback": (
                "NOT_USED" if origin == "LIVE_SIMAP" else "SYNTHETIC_SAMPLE" if origin == "SYNTHETIC_SAMPLE" else "USED"
            ),
            "documents": "RETRIEVED",
            "qualification": qualification_status,
            "human_review": human_review_status,
        },
        "fit_signals": fit_signals,
        "blockers": blockers,
        "risks": risks,
        "next_actions": next_actions,
        "human_review_status": human_review_status,
    }


_CARD_WIDTH = 60


def render_executive_card(summary: dict[str, Any]) -> str:
    """Deterministic, fixed-width ASCII card built only from `summary` — the
    same input always renders identically (no randomness, no LLM call), and
    nothing here adds a fact not already present in `summary` (see
    `build_executive_summary`'s docstring for what that can/cannot contain).
    """
    workflow = summary.get("workflow_status") or {}
    if workflow.get("simap") == "LIVE":
        origin_label = "LIVE_SIMAP"
    elif workflow.get("local_fallback") == "SYNTHETIC_SAMPLE":
        origin_label = "SYNTHETIC_SAMPLE"
    else:
        origin_label = "LOCAL_FALLBACK"

    title = summary.get("title") or "UNKNOWN"
    lines = [
        "=" * _CARD_WIDTH,
        f"TENDER: {title}",
        f"AUTHORITY: {summary.get('authority') or 'UNKNOWN'}  |  DEADLINE: {summary.get('deadline') or 'UNKNOWN'}",
        f"DATA ORIGIN: {origin_label}  |  SOURCE_TYPE: {summary.get('source_type') or 'UNKNOWN'}",
        "-" * _CARD_WIDTH,
        (
            f"RECOMMENDATION: {summary.get('recommendation') or 'UNKNOWN'}  |  "
            f"SCORE: {summary.get('score', 'UNKNOWN')}/100  |  "
            f"CONFIDENCE: {summary.get('confidence') or 'UNKNOWN'}"
        ),
        (
            f"WORKFLOW: qualification={workflow.get('qualification', 'UNKNOWN')}  "
            f"human_review={workflow.get('human_review', 'UNKNOWN')}"
        ),
        f"SELECTED TENDER: {title}",
        "-" * _CARD_WIDTH,
        "CAPABILITY SIGNALS:",
    ]
    # Each entry already carries its own rule-4 symbol (✓/◐) from
    # build_executive_summary — printed as-is, not re-derived here.
    fit_signals = summary.get("fit_signals") or []
    if fit_signals:
        lines.extend(f"  {s}" for s in fit_signals)
    else:
        lines.append("  (none)")
    lines.append(f"{_SYMBOL_BLOCKER_SECTION} BLOCKERS:")
    # Each entry already carries its own rule-4 symbol (✗ confirmed / ? unresolved).
    blockers = summary.get("blockers") or []
    if blockers:
        lines.extend(f"  {b}" for b in blockers)
    else:
        lines.append("  (none)")
    lines.append("-" * _CARD_WIDTH)
    lines.append(f"HUMAN REVIEW: {summary.get('human_review_status') or 'UNKNOWN'}")
    lines.append("=" * _CARD_WIDTH)
    return "\n".join(lines)
