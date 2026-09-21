"""TenderSelectionAgent — automatic, transparent tender selection.

Scores every search-result-level `Tender` on six dimensions and ranks them,
so `WorkflowOrchestrator.run` can select the best one automatically while
keeping 2-3 runner-ups for traceability and manual override:

- cloud_infrastructure_fit / managed_services_fit / cybersecurity_fit:
  keyword overlap (title + scope) against the subset of `data/hpe_profile.json`
  capabilities whose *name* matches that theme (e.g. "hybrid cloud" for
  cloud infrastructure) — the theme keyword sets are never invented
  separately, they're read straight from the same editable profile the rest
  of the app already trusts.
- hpe_capability_fit: the same keyword overlap against the *entire*
  capability list (catches capabilities outside those three themes, e.g.
  networking or AI infrastructure).
- deadline_fit: `Tender.submission_deadline` (real field only — search
  results from SimapAdapter never carry one, see
  `src/adapters/tender_search.py`; that stays honestly neutral, never guessed).
- documents_available: whether `DocumentRetrievalTool.retrieve_documents`
  actually succeeds for this tender — a real check, not an assumption.

No LLM call — deterministic, and reuses `src.agents.matching.significant_tokens`
(the same tokenizer `eligibility_gate.py`/`fit_scoring.py` already use), so
this is one more consumer of that shared primitive, not a second scoring
implementation. `fit_scoring.py`'s HPE *qualification* score is untouched —
this module answers a different question (which candidate to analyze first),
computed on search-result metadata alone, before any document is extracted.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import fetch_tender_details, get_search_adapters
from src.agents.matching import significant_tokens
from src.agents.retrieval import DocumentRetrievalTool
from src.schemas.briefing import AlternativeTender
from src.schemas.common import PublicationStatus
from src.schemas.hpe_profile import Capability, HPEProfile
from src.schemas.tender import Tender, TenderDocument

_MAX_CLOUD = 20.0
_MAX_MANAGED = 20.0
_MAX_CYBER = 20.0
_MAX_CAPABILITY = 20.0
_MAX_DEADLINE = 10.0
_MAX_DOCUMENTS = 10.0
# 20 + 20 + 20 + 20 + 10 + 10 = 100, mirroring ScoreBreakdown's style.

# A ratio of significant-keyword overlap >= this is a "MATCH" in
# src.agents.matching._capability_overlap — reused here as the point where a
# themed/overall capability-fit dimension hits its own max points, instead of
# inventing a separate cutoff.
_FULL_SCORE_RATIO = 0.25

_CLOUD_NAME_HINTS = ("cloud", "data center")
_MANAGED_NAME_HINTS = ("managed", "support", "consulting")
_CYBER_NAME_HINTS = ("cyber", "security")


class RelevanceScoreBreakdown(BaseModel):
    """Transparent point allocation for automatic tender selection. Max points: 20/20/20/20/10/10 = 100."""

    cloud_infrastructure_fit: float = Field(..., ge=0, le=_MAX_CLOUD)
    managed_services_fit: float = Field(..., ge=0, le=_MAX_MANAGED)
    cybersecurity_fit: float = Field(..., ge=0, le=_MAX_CYBER)
    hpe_capability_fit: float = Field(..., ge=0, le=_MAX_CAPABILITY)
    deadline_fit: float = Field(..., ge=0, le=_MAX_DEADLINE)
    documents_available: float = Field(..., ge=0, le=_MAX_DOCUMENTS)
    notes: list[str] = Field(default_factory=list, description="One short explanation per dimension, in the same order.")

    @property
    def total(self) -> float:
        return (
            self.cloud_infrastructure_fit
            + self.managed_services_fit
            + self.cybersecurity_fit
            + self.hpe_capability_fit
            + self.deadline_fit
            + self.documents_available
        )


@dataclass
class TenderRelevance:
    """One scored candidate — carries its already-fetched documents so a
    later extraction step (for whichever candidate ends up selected) never
    re-fetches them."""

    tender: Tender
    breakdown: RelevanceScoreBreakdown
    documents: list[TenderDocument]

    @property
    def total(self) -> float:
        return self.breakdown.total


def _capabilities_by_name_hint(profile: HPEProfile, hints: tuple[str, ...]) -> list[Capability]:
    return [c for c in profile.capabilities if any(hint in c.name.lower() for hint in hints)]


def _capability_fit_score(text: str, capabilities: list[Capability], max_points: float, theme: str) -> tuple[float, str]:
    if not capabilities:
        return round(max_points * 0.5, 1), f"{theme}: no matching HPE capability listed in the profile (neutral)"

    text_tokens = significant_tokens(text)
    if not text_tokens:
        return 0.0, f"{theme}: tender title/scope has no significant keywords to match on"

    cap_tokens = significant_tokens(" ".join(f"{c.name} {c.description or ''}" for c in capabilities))
    overlap = text_tokens & cap_tokens
    ratio = len(overlap) / len(text_tokens)
    score = round(min(ratio / _FULL_SCORE_RATIO, 1.0) * max_points, 1)
    names = "/".join(c.name for c in capabilities)
    return score, f"{theme}: {ratio:.0%} keyword overlap with HPE capabilities ({names})"


def _deadline_score(tender: Tender, as_of: date, max_points: float) -> tuple[float, str]:
    if tender.submission_deadline is None:
        return round(max_points * 0.5, 1), "Deadline: UNKNOWN (not provided by this search result) — neutral"

    days_left = (tender.submission_deadline - as_of).days
    if days_left < 0:
        return 0.0, f"Deadline: already passed ({-days_left} day(s) ago)"
    if days_left < 7:
        return round(max_points * 0.3, 1), f"Deadline: in {days_left} day(s) — very tight"
    if days_left < 14:
        return round(max_points * 0.6, 1), f"Deadline: in {days_left} day(s) — tight but workable"
    return max_points, f"Deadline: in {days_left} day(s) — comfortable lead time"


def _documents_score(
    tender: Tender, retrieval_tool: DocumentRetrievalTool, max_points: float
) -> tuple[float, list[TenderDocument], str]:
    try:
        documents = retrieval_tool.retrieve_documents(tender)
    except AdapterUnavailableError as exc:
        return 0.0, [], f"Documents: not retrievable ({exc})"
    if not documents:
        return 0.0, [], "Documents: none found for this tender"
    return max_points, documents, f"Documents: {len(documents)} available"


def score_tender(
    tender: Tender, profile: HPEProfile, retrieval_tool: DocumentRetrievalTool, as_of: date
) -> TenderRelevance:
    """Score one candidate. Document retrieval happens here (not just at
    extraction time) because "documents present" is itself one of the
    scoring dimensions — the fetched documents are kept on the result so the
    eventual winner's extraction step reuses them instead of re-fetching."""
    text = f"{tender.title} {tender.scope or ''}".strip()

    cloud_score, cloud_note = _capability_fit_score(
        text, _capabilities_by_name_hint(profile, _CLOUD_NAME_HINTS), _MAX_CLOUD, "Cloud infrastructure"
    )
    managed_score, managed_note = _capability_fit_score(
        text, _capabilities_by_name_hint(profile, _MANAGED_NAME_HINTS), _MAX_MANAGED, "Managed services"
    )
    cyber_score, cyber_note = _capability_fit_score(
        text, _capabilities_by_name_hint(profile, _CYBER_NAME_HINTS), _MAX_CYBER, "Cybersecurity"
    )
    capability_score, capability_note = _capability_fit_score(
        text, profile.capabilities, _MAX_CAPABILITY, "HPE capability match (overall)"
    )
    deadline_score, deadline_note = _deadline_score(tender, as_of, _MAX_DEADLINE)
    documents_score, documents, documents_note = _documents_score(tender, retrieval_tool, _MAX_DOCUMENTS)

    notes = [cloud_note, managed_note, cyber_note, capability_note, deadline_note, documents_note]
    breakdown = RelevanceScoreBreakdown(
        cloud_infrastructure_fit=cloud_score,
        managed_services_fit=managed_score,
        cybersecurity_fit=cyber_score,
        hpe_capability_fit=capability_score,
        deadline_fit=deadline_score,
        documents_available=documents_score,
        # Each note is a full clause without trailing punctuation — add a
        # period here, once, so joining them for selection_reason reads as
        # separate sentences instead of running on.
        notes=[n if n.endswith(".") else f"{n}." for n in notes],
    )
    return TenderRelevance(tender=tender, breakdown=breakdown, documents=documents)


def rank_candidates(
    candidates: list[Tender],
    profile: HPEProfile,
    retrieval_tool: DocumentRetrievalTool,
    as_of: date | None = None,
) -> list[TenderRelevance]:
    """Score every candidate and return them best-first."""
    resolved_as_of = as_of or datetime.now(UTC).date()
    scored = [score_tender(t, profile, retrieval_tool, resolved_as_of) for t in candidates]
    scored.sort(key=lambda r: r.total, reverse=True)
    return scored


def build_alternatives(ranked: list[TenderRelevance], exclude_id: str, limit: int = 3) -> list[AlternativeTender]:
    """2-3 runner-ups (whatever is left after excluding the selected id), best-first."""
    runner_ups = [r for r in ranked if r.tender.id != exclude_id]
    return [
        AlternativeTender(tender_id=r.tender.id, title=r.tender.title, relevance_score=round(r.total, 1), rank=i + 1)
        for i, r in enumerate(runner_ups[:limit])
    ]


def auto_selection_reason(selected: TenderRelevance, runner_ups: list[TenderRelevance]) -> str:
    headline = (
        f"Automatically selected '{selected.tender.title}' (id={selected.tender.id}) as the "
        f"highest-relevance candidate ({selected.total:.1f}/100)."
    )
    parts = [headline]
    parts.extend(selected.breakdown.notes)
    if runner_ups:
        runner_up_desc = "; ".join(f"{r.tender.id} ({r.total:.1f}/100)" for r in runner_ups[:3])
        parts.append(f"Runner-up candidate(s): {runner_up_desc}.")
    return " ".join(parts)


def override_selection_reason(selected: TenderRelevance, auto_pick: TenderRelevance) -> str:
    if selected.tender.id == auto_pick.tender.id:
        # A human "override" that happens to match the automatic pick — still
        # record it as an override (that's what was asked for), but say so honestly.
        return (
            f"Manually selected '{selected.tender.title}' (id={selected.tender.id}) via human override — "
            f"this happens to match the automatic pick ({selected.total:.1f}/100)."
        )
    return (
        f"Manually selected '{selected.tender.title}' (id={selected.tender.id}, relevance score "
        f"{selected.total:.1f}/100) via human override, overriding the automatic pick "
        f"'{auto_pick.tender.title}' (id={auto_pick.tender.id}, relevance score {auto_pick.total:.1f}/100)."
    )


# ---------------------------------------------------------------------------
# select_tenders — the explicit SELECT phase:
#   search_tenders -> select_tenders -> get_tender -> qualification
#
# Everything above this point (rank_candidates/score_tender/RelevanceScoreBreakdown)
# is reused completely unmodified as the HPE-capability-fit half of the
# score. What follows only *adds* the two things that engine doesn't cover:
# how well a candidate matches the user's actual search query, and whether
# it's still actionable at all (publication status). This is one engine
# extended, not a second one.
# ---------------------------------------------------------------------------

_ALREADY_AWARDED_PUB_TYPES = {"award_tender", "award_study_contract", "award_competition"}
_REVOKED_PUB_TYPES = {"revocation"}
_CANCELLED_PUB_TYPES = {"abandonment"}
_DIRECT_AWARD_PUB_TYPES = {"direct_award"}

_NON_ACTIONABLE_REASON = {
    PublicationStatus.ALREADY_AWARDED: "Already awarded — not actionable.",
    PublicationStatus.DIRECT_AWARD_NOT_OPEN: "Direct award, not an open competitive process — not actionable.",
    PublicationStatus.EXPIRED: "Submission deadline has already passed — not actionable.",
    PublicationStatus.REVOKED: "Publication was revoked — not actionable.",
    PublicationStatus.CANCELLED: "Procurement was abandoned/cancelled — not actionable.",
}


def classify_publication_status(
    pub_type: str | None,
    process_type: str | None,
    submission_deadline: date | None,
    as_of: date,
) -> tuple[PublicationStatus, str]:
    """Never invents a status: only returns something other than UNKNOWN
    when a real signal actually says so — a real `pub_type` from a live
    `get_tender_details` call, or a real known `submission_deadline`
    (whichever source it came from). A missing/unrecognized `pub_type`
    always stays UNKNOWN — it is never inferred to mean "open" or excluded
    as if it meant something worse.
    """
    if submission_deadline is not None and submission_deadline < as_of:
        return PublicationStatus.EXPIRED, f"Submission deadline {submission_deadline.isoformat()} has already passed."

    if not pub_type:
        return PublicationStatus.UNKNOWN, "Publication status UNKNOWN — no status field available."

    if pub_type in _ALREADY_AWARDED_PUB_TYPES:
        return (
            PublicationStatus.ALREADY_AWARDED,
            f"Publication type {pub_type!r} indicates the contract has already been awarded.",
        )
    if pub_type in _REVOKED_PUB_TYPES:
        return PublicationStatus.REVOKED, f"Publication type {pub_type!r} indicates the procurement was revoked."
    if pub_type in _CANCELLED_PUB_TYPES:
        return (
            PublicationStatus.CANCELLED,
            f"Publication type {pub_type!r} indicates the procurement was abandoned/cancelled.",
        )
    if pub_type in _DIRECT_AWARD_PUB_TYPES and (process_type or "").lower() != "open":
        return (
            PublicationStatus.DIRECT_AWARD_NOT_OPEN,
            f"Publication type {pub_type!r} is a direct award, not an open competitive process.",
        )

    return PublicationStatus.OPEN, f"Publication type {pub_type!r} is an open/ongoing procurement step."


def _query_relevance_score(query: str, tender: Tender) -> tuple[float, str, bool]:
    """Pertinence par rapport à la requête — keyword overlap between the
    search query and this tender's title/scope, using the exact same
    tokenizer (`matching.significant_tokens`) every other dimension in this
    module already uses. Neutral (not zero) when the query is too short to
    judge anything (e.g. a browse-everything call) — never penalized for
    that.

    The third element (`meets_gate`) says whether this candidate has *any*
    meaningful keyword overlap with an actual (>=3 char) query — see
    `_QUERY_RELEVANCE_GATE` below, which uses it to keep select_tenders from
    ever selecting a candidate with zero relevance to what was actually
    asked for, purely because everything else scored worse. A "no specific
    query given" call always passes the gate (there's nothing to filter
    against)."""
    stripped = (query or "").strip()
    if len(stripped) < 3:
        return 50.0, "Query relevance: no specific query given (neutral).", True
    query_tokens = significant_tokens(stripped)
    text_tokens = significant_tokens(f"{tender.title} {tender.scope or ''}")
    if not query_tokens or not text_tokens:
        return 0.0, "Query relevance: no significant keywords to compare.", False
    overlap = query_tokens & text_tokens
    ratio = len(overlap) / len(query_tokens)
    return (
        round(min(ratio, 1.0) * 100, 1),
        f"Query relevance: {ratio:.0%} of the search query's keywords found in this tender's title/scope.",
        bool(overlap),
    )


# The SELECT-phase relevance gate (see select_tenders): a candidate with
# zero meaningful query-keyword overlap must never be the one selected, even
# when it's the highest-scoring candidate left after status filtering — an
# unrelated tender is not an acceptable "least bad" answer. This message is
# used both as the per-candidate exclusion_reason and as the note appended
# to that candidate's `unknowns`, so it surfaces at the top level too (see
# mcp_server.select_tenders' aggregated `unknowns`).
_QUERY_RELEVANCE_GATE_REASON = "No meaningful keyword match with the requested query."


def _perimeter_note(filters: dict | None, tender: Tender) -> str | None:
    """Canton/périmètre — only produced when the caller actually specified
    one (`filters={"cantons": [...]}` or `{"location": ...}`); note-only, no
    score impact, since this is explicitly "if available", not a hard
    criterion. Returns None (nothing to say) when no perimeter was
    requested — never fabricates a canton the caller didn't ask about."""
    filters = filters or {}
    location = (tender.location or "").lower()
    if cantons := filters.get("cantons"):
        matched = any(str(c).lower() in location for c in cantons)
        return (
            f"Perimeter: tender location ({tender.location or 'UNKNOWN'}) "
            f"{'matches' if matched else 'does not match'} requested canton(s) {list(cantons)}."
        )
    if wanted_location := filters.get("location"):
        matched = str(wanted_location).lower() in location
        return (
            f"Perimeter: tender location ({tender.location or 'UNKNOWN'}) "
            f"{'matches' if matched else 'does not match'} requested location {wanted_location!r}."
        )
    return None


def _resolve_status(tender: Tender, as_of: date) -> tuple[PublicationStatus, str]:
    """One get_tender_details call at most, and only when it could possibly
    say something: a SIMAP-sourced tender with a real publication_id. Never
    called for local_fallback tenders (they never carry a publication_id at
    all) and never called twice for the same tender within one
    `select_tenders` run."""
    effective_deadline = tender.submission_deadline  # real field, whatever its source
    pub_type: str | None = None
    process_type: str | None = None

    if tender.source_type == "simap_mcp":
        if not tender.publication_id:
            return (
                PublicationStatus.UNKNOWN,
                f"Publication status UNKNOWN — no publication_id captured for tender {tender.id!r}.",
            )
        details = fetch_tender_details(tender, get_search_adapters())
        if not details["available"]:
            return PublicationStatus.UNKNOWN, f"Publication status UNKNOWN — {details['reason']}"
        pub_type = details.get("pub_type")
        process_type = details.get("process_type")
        if details.get("submission_deadline"):
            effective_deadline = date.fromisoformat(details["submission_deadline"])

    return classify_publication_status(pub_type, process_type, effective_deadline, as_of)


# Bounds the thread pool below, regardless of how many candidates a broad
# search_tenders query returns — so a 50-candidate query still opens at most
# this many concurrent subprocess/HTTP round-trips at once, not 50.
_MAX_PARALLEL_STATUS_CHECKS = 8


def _resolve_statuses_concurrently(tenders: list[Tender], as_of: date) -> list[tuple[PublicationStatus, str]]:
    """Runs `_resolve_status` for every candidate concurrently instead of
    one at a time, in the same order as `tenders`.

    This is the actual fix for select_tenders being slow on a broad query
    (observed: ~57s via Hermes): `_resolve_status` is the one step here that
    can do real network I/O (a `get_tender_details` MCP round-trip per
    SIMAP-sourced candidate with a `publication_id`) — document retrieval
    (`_documents_score`) is a local filesystem read and was never the
    bottleneck. Calling `_resolve_status` sequentially, once per candidate,
    made total wall time grow with the number of candidates; running it
    concurrently (bounded by `_MAX_PARALLEL_STATUS_CHECKS`) cuts that back to
    roughly one round-trip's worth of wall time. Every candidate is still
    checked exactly once, the same way `_resolve_status` always has — no
    status value, exclusion decision, or the selected candidate changes.
    """
    if not tenders:
        return []
    max_workers = min(len(tenders), _MAX_PARALLEL_STATUS_CHECKS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda t: _resolve_status(t, as_of), tenders))


def select_tenders(
    candidates: list[Tender],
    query: str,
    profile: HPEProfile,
    retrieval_tool: DocumentRetrievalTool,
    as_of: date | None = None,
    filters: dict | None = None,
) -> list[dict]:
    """The explicit SELECT phase: search_tenders -> select_tenders ->
    get_tender -> qualification.

    Returns one structured justification dict per candidate, best-first:
    `tender_id`, `project_id` (always equal to `tender_id` — SIMAP's project
    UUID), `publication_id`, `title`, `source_type`, `relevance_score`
    (0-100, combining the reused HPE-capability-fit score with query
    relevance), `status` (a `PublicationStatus` value), `reasons` (every
    dimension's note, human-readable), `unknowns` (only the status note,
    when status is UNKNOWN), `exclusion_reason` (set only for a candidate
    that was *not* selected), and `selected` (True for exactly one
    candidate — the best-ranked actionable one — or no candidate at all if
    every single one turned out non-actionable, or if every actionable
    candidate has zero meaningful query relevance; never forced onto a
    non-actionable or query-irrelevant candidate just to have a winner —
    see the query-relevance gate below, which excludes any candidate with
    no meaningful keyword overlap with `query` regardless of how well it
    otherwise scores).
    """
    resolved_as_of = as_of or datetime.now(UTC).date()
    ranked = rank_candidates(candidates, profile, retrieval_tool, as_of=resolved_as_of)

    # See _resolve_statuses_concurrently's docstring: this is the one
    # potentially-slow step (real SIMAP round-trips), so it runs concurrently
    # across all candidates instead of one at a time — same statuses, same
    # order, just not serialized.
    statuses = _resolve_statuses_concurrently([r.tender for r in ranked], resolved_as_of)

    results: list[dict] = []
    gate_by_id: dict[str, bool] = {}
    for relevance, (status, status_note) in zip(ranked, statuses, strict=True):
        tender = relevance.tender
        query_score, query_note, meets_gate = _query_relevance_score(query, tender)
        gate_by_id[tender.id] = meets_gate
        perimeter_note = _perimeter_note(filters, tender)

        reasons = [query_note]
        if not meets_gate:
            reasons.append(f"{_QUERY_RELEVANCE_GATE_REASON} (query relevance score {query_score:.1f}/100).")
        reasons.extend(relevance.breakdown.notes)
        if perimeter_note:
            reasons.append(perimeter_note)
        reasons.append(status_note)

        unknowns = [status_note] if status == PublicationStatus.UNKNOWN else []
        if not meets_gate:
            unknowns.append(_QUERY_RELEVANCE_GATE_REASON)

        results.append(
            {
                "tender_id": tender.id,
                "project_id": tender.id,
                "publication_id": tender.publication_id,
                "title": tender.title,
                "source_type": tender.source_type,
                "relevance_score": round((relevance.total + query_score) / 2, 1),
                "status": status.value,
                "reasons": reasons,
                "unknowns": unknowns,
                "exclusion_reason": None,
                "selected": False,
            }
        )

    # Re-rank by the *combined* relevance_score (HPE fit + query relevance),
    # not just the HPE-fit-only order rank_candidates produced on its own.
    results.sort(key=lambda r: r["relevance_score"], reverse=True)

    selected_marked = False
    for entry in results:
        status = PublicationStatus(entry["status"])
        if status in _NON_ACTIONABLE_REASON:
            entry["exclusion_reason"] = _NON_ACTIONABLE_REASON[status]
            continue
        # UNKNOWN (and OPEN) both remain eligible — an unresolved status
        # never excludes a candidate on its own (rule 6). The query-relevance
        # gate is checked separately below, and independently of status: a
        # candidate with zero meaningful query relevance must never be
        # selected just because it's the best of a bad, unrelated lot.
        if not gate_by_id[entry["tender_id"]]:
            entry["exclusion_reason"] = _QUERY_RELEVANCE_GATE_REASON
            continue
        if not selected_marked:
            entry["selected"] = True
            selected_marked = True
        else:
            entry["exclusion_reason"] = (
                f"Not the highest-relevance actionable candidate (relevance_score "
                f"{entry['relevance_score']:.1f}/100, ranked below the selected tender)."
            )

    return results
