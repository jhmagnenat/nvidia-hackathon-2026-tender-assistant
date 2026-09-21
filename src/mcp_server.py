"""MCP stdio server exposing the HPE tender qualification workflow.

Lets Hermes/NemoClaw drive the real pipeline (src/agents/*, src/adapters/*)
as MCP tools instead of a human running `python -m src.pipeline` by hand.
This module is a thin adapter layer only: every tool below calls straight
into the existing, already-tested agents/adapters. No search, extraction,
matching, scoring, or briefing logic is duplicated or reimplemented here —
see docs/architecture.md and IMPLEMENTATION_LOG.md for why those are
deterministic/local-fallback-first in this environment.

Run it directly:

    python -m src.mcp_server

Register with Hermes as a native stdio MCP server (same pattern as the
SIMAP MCP server documented in integrations/simap/README.md, but a local
Python command instead of a Node one — see `hermes mcp add --help`):

    mcp_servers:
      hpe-tender-qualification:
        command: python3
        args: ["-m", "src.mcp_server"]
        cwd: /path/to/this/repo   # so `src` and `data/` resolve
        connect_timeout: 10

See IMPLEMENTATION_LOG.md for the full launch/registration notes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import (
    LocalSampleSearchAdapter,
    fetch_tender_details,
    get_search_adapters,
)
from src.agents import matching, tender_selection
from src.agents.feedback import record_feedback
from src.agents.ingestion import extract_requirements as run_extraction
from src.agents.workflow import WorkflowOrchestrator
from src.schemas.briefing import HumanDecision
from src.schemas.tender import Tender, TenderSource

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIEFINGS_DIR = REPO_ROOT / "data" / "briefings"
DRAFTS_DIR = REPO_ROOT / "data" / "drafts"
FEEDBACK_LOG_PATH = REPO_ROOT / "data" / "feedback_log.json"

mcp = FastMCP(
    "hpe-tender-qualification",
    instructions=(
        "QUALIFIES a Swiss public tender against the HPE capability profile — "
        "it does not replace live tender discovery. When a separate SIMAP "
        "MCP server (e.g. 'simap-fixed') is also connected, that server is "
        "the sole source for live tender search: do not call this server's "
        "own search_tenders/select_tenders automatically after, or instead "
        "of, a SIMAP-fixed search — they run their own adapter chain "
        "(simap_bridge -> simap -> tavily -> local_sample) which can return "
        "different candidates. Use them only to (a) score/rank a known "
        "candidate set purely for HPE-capability fit, or (b) search when no "
        "live SIMAP source is reachable at all (in that case, every result "
        "is clearly labeled 'local_sample'/'local_fallback', never presented "
        "as live SIMAP data). To qualify a tender already identified "
        "elsewhere (e.g. via SIMAP-fixed), call it by tender_id directly: "
        "get_tender -> extract_requirements -> match_hpe_capabilities -> "
        "qualify_tender -> create_briefing -> submit_human_decision -> "
        "create_draft. select_tenders (when used) is the explicit SELECT "
        "phase: it scores every search_tenders candidate (relevance to the "
        "query, HPE capability fit, deadline, canton/location if given, "
        "document availability) and flags non-actionable ones (already "
        "awarded, direct award not open, expired, revoked, cancelled) via a "
        "real SIMAP status check — never assuming NO-GO just because a "
        "status is unknown. This MVP's document retrieval only reads local "
        "sample fixtures (data/sample_tenders/<id>/*.txt) — it does not yet "
        "download real SIMAP documents. For a tender_id with no matching "
        "local fixture (typical for a live SIMAP-fixed result), "
        "extract_requirements/match_hpe_capabilities/qualify_tender/"
        "create_briefing/submit_human_decision report "
        "documents_status='NOT_RETRIEVED', confidence='LOW' "
        "(qualification_status='BLOCKED' for the qualification tools), and "
        "keep already-known SIMAP search-result metadata "
        "('simap_metadata_facts') strictly separate from document-derived "
        "facts (none) and UNKNOWN items — this is never presented as a "
        "complete document analysis or a real GO/MAYBE/NO-GO recommendation. "
        "Every tool returns structured JSON with 'sources'/'citations'/"
        "'unknowns' fields; unresolved facts are reported as UNKNOWN rather "
        "than guessed, and UNKNOWN is never silently upgraded to MATCH. A "
        "recommendation (GO/MAYBE/NO-GO) is never final on its own: always "
        "call submit_human_decision with the reviewer's actual "
        "approved/rejected/more_research choice before treating a tender as "
        "closed — never assume approval. create_draft refuses to run unless "
        "that decision was 'approved' — a draft is never produced without a "
        "recorded human approval."
    ),
)

_orchestrator: WorkflowOrchestrator | None = None

# Process-lifetime cache, keyed by Tender.id: avoids re-issuing a search
# (a real SIMAP MCP round-trip once simap_bridge/simap is configured) on
# every single tool call for a tender already seen this session. A single
# review pass (search -> get -> extract -> match -> qualify -> briefing ->
# decision) would otherwise call orchestrator.search("") up to six times for
# the exact same lookup. Populated by every search_tenders() call and by
# _find_tender()'s own fallback search; never invalidated/expired within a
# process lifetime — restart the server for a guaranteed-fresh search. Tests
# reset it explicitly (see tests/test_mcp_server.py) for isolation.
_tender_cache: dict[str, Tender] = {}


def _get_orchestrator() -> WorkflowOrchestrator:
    """Lazily build the single WorkflowOrchestrator this server reuses.

    Read-only after construction (search/retrieval adapters + the loaded HPE
    profile), so one shared instance across calls is safe.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WorkflowOrchestrator()
    return _orchestrator


def _cache_tenders(tenders: list[Tender]) -> None:
    for t in tenders:
        _tender_cache[t.id] = t


def _find_tender(orchestrator: WorkflowOrchestrator, tender_id: str) -> Tender | None:
    """Cache-first lookup — see `_tender_cache`'s module-level docstring.

    Falls back to a real `orchestrator.search("")` call on a cache miss (and
    caches that result, so a second miss never happens for the same id
    within this process's lifetime) — but that call can resolve to a live
    adapter (simap_bridge/simap) instead of local_sample whenever one is
    `.available` (see `TenderSearchTool.search_tenders`: it only moves to
    the next candidate on `AdapterUnavailableError`, not merely on "few/no
    results"). When that happens, the synthetic demo fixtures in
    data/sample_tenders.json are never reached by that call, so a known
    sample id (e.g. "cloud-infra-2026") would incorrectly report "Unknown
    tender id" even though its fixture is real and complete on disk.

    Guaranteed last resort: query `LocalSampleSearchAdapter` directly (not
    the live/priority-ordered chain) for the exact same registry
    search_tenders/select_tenders already use as their own fallback, and
    cache whatever it returns. This never calls a live adapter, never
    fabricates a "live"/SIMAP tender (every result here is already labeled
    source="local_sample" by data/sample_tenders.json itself), and never
    changes which tender search_tenders/select_tenders present as live —
    it only makes the always-available local registry reachable by id for
    get_tender/extract_requirements/match_hpe_capabilities/qualify_tender/
    create_briefing/submit_human_decision, exactly like it already is by
    query.
    """
    cached = _tender_cache.get(tender_id)
    if cached is not None:
        return cached
    _cache_tenders(orchestrator.search(""))
    cached = _tender_cache.get(tender_id)
    if cached is not None:
        return cached
    try:
        _cache_tenders(LocalSampleSearchAdapter().search(""))
    except AdapterUnavailableError:
        pass
    return _tender_cache.get(tender_id)


_PROVENANCE_NOTES = {
    # Keyed by `Tender.source.value` (TenderSource: simap/tavily/local_sample)
    # — what search_tenders' `sources` list is built from.
    "local_sample": (
        "Sourced from local sample fixtures under data/ "
        "(data/sample_tenders.json, data/sample_tenders/) — NOT a live SIMAP connection."
    ),
    "simap": "Sourced from a live SIMAP connection.",
    "tavily": "Sourced from a live Tavily search.",
    # Keyed by `Tender.source_type` (ResearchMode: simap_mcp/local_fallback)
    # — what select_tenders' `sources` list is built from instead (see
    # tender_selection.select_tenders' entries). Same underlying provider
    # set as above, coarser signal — "simap_mcp" is real live SIMAP via the
    # SimapAdapter MCP/bridge path, never local or unknown.
    "simap_mcp": "Sourced from live SIMAP via the SIMAP MCP bridge.",
    "local_fallback": "Sourced from a local/non-live fallback index — NOT a live SIMAP connection.",
}


def _provenance_note(source: str) -> str:
    return _PROVENANCE_NOTES.get(source, f"Unrecognized source '{source}' — provenance UNKNOWN.")


# Caps how many of select_tenders' per-candidate justification entries are
# actually serialized to Hermes. This is a transport-compactness cap applied
# *after* the full candidate set has already been scored/ranked/excluded by
# src.agents.tender_selection.select_tenders — it never changes which
# candidate is selected or which are excluded, only how many of the
# resulting entries are echoed back. 10 is not a scoring cutoff; it is
# "enough runner-ups to be useful in one Hermes turn without spilling to
# disk". The selected candidate is always included even if its rank would
# otherwise place it past this cap (see select_tenders below) — see
# `total_candidates`/`omitted_candidates` in the response for the rest.
_MAX_CANDIDATES_IN_RESPONSE = 10

# The subset of a tender_selection.select_tenders() entry that actually
# reaches Hermes — see _compact_candidate.
_CANDIDATE_FIELDS = (
    "tender_id",
    "project_id",
    "publication_id",
    "title",
    "source_type",
    "relevance_score",
    "status",
    "exclusion_reason",
    "selected",
    "unknowns",
)


_MAX_SELECTION_REASONS = 3
_MAX_REASON_LENGTH = 240


def _truncate_reason(reason: str, max_len: int = _MAX_REASON_LENGTH) -> str:
    """Shortens one existing reason string to at most `max_len` characters —
    never rewrites or summarizes its content, only cuts it, so nothing it
    says is invented. An ellipsis marks a cut; the string is left alone
    (no ellipsis) when it already fits."""
    if len(reason) <= max_len:
        return reason
    return reason[: max_len - 1].rstrip() + "…"


def _selection_reasons(entry: dict[str, Any]) -> list[str]:
    """The compact, bounded justification for one candidate's status —
    always derived from `entry["reasons"]` (tender_selection.select_tenders'
    full per-dimension breakdown), never a new fact. `reasons` is ordered
    query-relevance-first, then the HPE-fit breakdown, then perimeter/status
    (see tender_selection.select_tenders' docstring) — the first
    `_MAX_SELECTION_REASONS` are kept as-is (deterministic, most-relevant
    ones first), each individually capped at `_MAX_REASON_LENGTH` chars.
    """
    return [_truncate_reason(r) for r in entry["reasons"][:_MAX_SELECTION_REASONS]]


def _compact_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    """MCP-facing shape for one select_tenders candidate.

    Keeps every field the workflow actually needs downstream (SELECT phase
    identity, source_type, publication_id/project_id, relevance_score,
    status, exclusion_reason, selected, unknowns) plus `selection_reasons` —
    a bounded (<= `_MAX_SELECTION_REASONS`), per-reason-truncated
    (<= `_MAX_REASON_LENGTH` chars) excerpt of
    `tender_selection.select_tenders`'s internal `reasons` list (up to ~9
    full-sentence notes per candidate — real, transparent per-dimension
    justification, but more than a Hermes tool response should carry in
    full). `reason_summary` stays as a one-line supplement (the existing
    `exclusion_reason` verbatim for an excluded candidate, or a short
    statement of why the selected one won) — it is never the *only*
    explanation returned; `selection_reasons` is the actual reasoning,
    verbatim excerpts of `entry["reasons"]`, never re-derived or invented.
    """
    compact = {field: entry[field] for field in _CANDIDATE_FIELDS}
    compact["selection_reasons"] = _selection_reasons(entry)
    compact["reason_summary"] = entry["exclusion_reason"] or (
        f"Selected — highest-relevance actionable candidate (relevance_score={entry['relevance_score']})."
    )
    return compact


def _tender_citation(tender: Tender) -> dict[str, Any]:
    """A traceability record for a Tender search-result — same shape as schemas.common.Citation."""
    document = "data/sample_tenders.json" if tender.source.value == "local_sample" else (tender.url or "search index")
    return {"document": document, "page": None, "section": None, "quote": None}


# This MVP's only document retrieval adapter reads local sample fixtures
# (data/sample_tenders/<id>/*.txt — see src/adapters/document_retrieval.py);
# it does not download real SIMAP documents. A live SIMAP-sourced tender_id
# (from search_tenders/select_tenders or an external SIMAP MCP server) has
# no matching local folder, so DocumentRetrievalTool.retrieve_documents
# raises AdapterUnavailableError for it — expected, not a bug. The tools
# below must never present that as a completed document analysis: see
# `_documents_blocked`.
_DOCUMENT_RETRIEVAL_BLOCKED_NOTE = (
    "Tender documents were not retrieved for this tender_id. This MVP's document "
    "retrieval only reads local sample fixtures (data/sample_tenders/<id>/) — it "
    "does not yet download real SIMAP documents, even when SIMAP itself reports "
    "project documents as available (see get_tender's details.has_project_documents). "
    "SIMAP/search-result metadata already known is reported separately under "
    "simap_metadata_facts; every document-derived fact below is UNKNOWN. This is "
    "NOT a complete document analysis, and no GO/MAYBE/NO-GO recommendation should "
    "be inferred from it."
)


def _simap_metadata_facts(tender: Tender) -> dict[str, Any]:
    """Facts already known from the tender's *search-result* metadata only —
    never from a document, never inferred. Kept as an explicitly separate
    block (vs. document-derived facts, which are empty here, and
    inferences, which this deterministic pipeline never makes) so a blocked
    document-dependent tool still surfaces what it honestly can."""
    return {
        "title": tender.title,
        "buyer": tender.buyer,
        "location": tender.location,
        "publication_date": tender.publication_date.isoformat() if tender.publication_date else None,
        "submission_deadline": tender.submission_deadline.isoformat() if tender.submission_deadline else None,
        "url": tender.url,
        "source_type": tender.source_type,
        "publication_id": tender.publication_id,
    }


def _documents_blocked(tool: str, tender: Tender, exc: AdapterUnavailableError, **extra_fields: Any) -> dict[str, Any]:
    """Structured, honest result for a document-dependent tool when this
    tender's documents could not be retrieved (see
    `_DOCUMENT_RETRIEVAL_BLOCKED_NOTE`) — used instead of a bare `_error()`
    so the caller gets a machine-readable, non-fabricated result rather than
    just a failure message: `documents_status`/`confidence` (and, for the
    qualification tools, `qualification_status`) make the limitation
    explicit, `simap_metadata_facts` keeps search-result metadata strictly
    separate from document_facts (empty) and inferences (empty, this
    pipeline never infers), and `unknowns` spells out exactly what remains
    unresolved — never silently guessed or upgraded to a MATCH/recommendation.
    `status` stays "ok": this is a legitimate, fully-described outcome, not
    a tool failure.
    """
    return _ok(
        tool,
        tender_id=tender.id,
        documents_status="NOT_RETRIEVED",
        confidence="LOW",
        simap_metadata_facts=_simap_metadata_facts(tender),
        document_facts=[],
        inferences=[],
        sources=[tender.source.value],
        citations=[_tender_citation(tender)],
        notes=[_provenance_note(tender.source.value), _DOCUMENT_RETRIEVAL_BLOCKED_NOTE],
        unknowns=[
            str(exc),
            "Mandatory/technical/commercial requirements: UNKNOWN (documents not retrieved).",
        ],
        **extra_fields,
    )


def _fetch_tender_details(tender: Tender) -> dict[str, Any]:
    """Real `get_tender_details` call for a SIMAP-sourced tender, using the
    exact project_id (`tender.id`) / publication_id propagated from its
    search result (see `Tender.publication_id`) — never derived or guessed.

    Thin wrapper around `src.adapters.tender_search.fetch_tender_details`
    (the one shared implementation of "try each adapter that supports
    get_tender_details" — also reused by `src.agents.tender_selection`'s
    SELECT phase, so this logic exists in exactly one place). Supplies
    `get_search_adapters()` from *this* module's own namespace (not
    imported freshly inside the call) so tests can substitute a fixed
    adapter list by patching `mcp_server.get_search_adapters`.

    Only ever called for `tender.source == TenderSource.SIMAP` — local_fallback
    tenders never reach this function at all, so their behavior is
    completely unaffected. Never fabricates a deadline/status/documents/URL:
    see that shared function's docstring for the exact unavailable cases.
    """
    return fetch_tender_details(tender, get_search_adapters())


def _dump(model: Any) -> Any:
    """model_dump via JSON round-trip, so date/datetime/enum values serialize cleanly."""
    return json.loads(model.model_dump_json())


def _ok(tool: str, **fields: Any) -> dict[str, Any]:
    return {"tool": tool, "status": "ok", **fields}


def _error(tool: str, message: str, **fields: Any) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": "error",
        "message": message,
        "sources": [],
        "citations": [],
        "unknowns": [message],
        **fields,
    }


@mcp.tool()
def search_tenders(query: str) -> dict[str, Any]:
    """Search Swiss public tenders relevant to HPE's qualification workflow.

    Reuses TenderSearchTool (src/agents/search.py over src/adapters/tender_search.py),
    which prefers SIMAP/Tavily when reachable and otherwise falls back to the local
    sample index at data/sample_tenders.json. Each result's true `source` field
    ("simap" | "tavily" | "local_sample") is preserved — local sample results are
    never presented as if they came from a live SIMAP connection.

    NOT the canonical live search when a dedicated SIMAP MCP server (e.g.
    "simap-fixed") is also connected — that server is the single source of
    truth for live tender discovery. Do not call this tool automatically
    after, or as a substitute for, a SIMAP-fixed search: it can legitimately
    return a different candidate set (this adapter chain, its own ranking).
    Use it only when no live SIMAP source is reachable at all, or when
    explicitly asked for HPE's own local/bridge search. To qualify a tender
    already found via SIMAP-fixed, call get_tender/extract_requirements/
    qualify_tender directly with its tender_id — no re-search needed here.
    """
    orchestrator = _get_orchestrator()
    try:
        tenders = orchestrator.search(query)
    except AdapterUnavailableError as exc:
        return _error("search_tenders", str(exc), query=query)

    # Every result seen here is immediately available to get_tender/
    # extract_requirements/etc. for the rest of this process's lifetime
    # without another search call — see _tender_cache's docstring.
    _cache_tenders(tenders)

    sources = sorted({t.source.value for t in tenders})
    return _ok(
        "search_tenders",
        query=query,
        count=len(tenders),
        tenders=[_dump(t) for t in tenders],
        sources=sources,
        citations=[_tender_citation(t) for t in tenders],
        notes=[_provenance_note(s) for s in sources] or ["No tenders matched this query."],
        unknowns=[],
    )


@mcp.tool()
def select_tenders(query: str, cantons: list[str] | None = None, location: str | None = None) -> dict[str, Any]:
    """The explicit SELECT phase: search_tenders -> select_tenders ->
    get_tender -> qualification.

    Same caveat as search_tenders: when a dedicated SIMAP MCP server (e.g.
    "simap-fixed") is connected, it is the canonical live search — do not
    call this tool automatically after, or instead of, a SIMAP-fixed
    search. Use it to score/rank a known candidate set for HPE-capability
    fit, or as the guaranteed local/bridge search when no live SIMAP source
    is reachable. A tender already selected via SIMAP-fixed should go
    straight to get_tender/extract_requirements/qualify_tender by tender_id.

    Searches (reusing search_tenders' exact machinery — same cache, same
    simap_bridge/simap/tavily/local_sample adapter chain, never a second
    search path) then scores every candidate via
    `src.agents.tender_selection.select_tenders` — the same relevance engine
    (`rank_candidates`/`score_tender`) `WorkflowOrchestrator.run()` already
    uses for automatic selection, extended (not duplicated) with: relevance
    to this exact query, canton/location perimeter (only considered when
    `cantons`/`location` are actually given here — never fabricated), and
    publication-status / non-actionable detection (already-awarded, direct
    award not open, expired, revoked, cancelled) via one real
    `get_tender_details` call per SIMAP-sourced candidate that actually has
    a `publication_id` — never more than once per candidate, and never at
    all for local_fallback candidates.

    Returns one compact justification entry per candidate (see
    `_compact_candidate`) — `selected` (true for exactly the best-ranked
    *actionable* candidate, or none at all if every candidate turned out
    non-actionable — never forced), `relevance_score`, `status`,
    `selection_reasons` (the actual, bounded justification — verbatim
    excerpts of the underlying `reasons`, never invented), `reason_summary`
    (a one-line supplement, never the only explanation), `exclusion_reason`,
    `source_type`, `publication_id`, and `project_id` (== `tender_id`). A
    `status` of "unknown" (no publication data available) never excludes a
    candidate by itself — see `tender_selection.classify_publication_status`.

    Full scoring/ranking/status-resolution runs over *every* candidate
    before any of this is truncated — `total_candidates`/`omitted_candidates`
    report if the `candidates` list below was capped for compactness
    (see `_MAX_CANDIDATES_IN_RESPONSE`); the selected candidate's entry is
    always present regardless. No document content, raw SIMAP/bridge
    payload, or per-dimension scoring breakdown is ever included here — use
    get_tender for a specific candidate's real SIMAP details.
    """
    orchestrator = _get_orchestrator()
    try:
        candidates = orchestrator.search(query)
    except AdapterUnavailableError as exc:
        return _error("select_tenders", str(exc), query=query)

    # Same cache search_tenders populates — a later get_tender/qualify_tender
    # call for the selected id needs no second search.
    _cache_tenders(candidates)

    if not candidates:
        return _ok(
            "select_tenders",
            query=query,
            count=0,
            total_candidates=0,
            omitted_candidates=0,
            candidates=[],
            selected_tender_id=None,
            sources=[],
            citations=[],
            notes=["No tenders matched this query."],
            unknowns=[],
        )

    filters: dict[str, Any] = {}
    if cantons:
        filters["cantons"] = cantons
    if location:
        filters["location"] = location

    entries = tender_selection.select_tenders(
        candidates,
        query,
        orchestrator.hpe_profile,
        orchestrator.retrieval_tool,
        filters=filters or None,
    )

    # Full scoring/ranking/exclusion already happened above, over every
    # candidate — this only truncates the *serialized* list for compactness.
    # The selected entry is always kept even if truncation would otherwise
    # drop it (see _MAX_CANDIDATES_IN_RESPONSE's docstring).
    total_candidates = len(entries)
    kept = entries[:_MAX_CANDIDATES_IN_RESPONSE]
    selected_entry = next((e for e in entries if e["selected"]), None)
    if selected_entry is not None and selected_entry not in kept:
        kept.append(selected_entry)
    omitted_candidates = total_candidates - len(kept)

    tenders_by_id = {t.id: t for t in candidates}
    sources = sorted({e["source_type"] for e in entries})
    unknowns = [u for entry in kept for u in entry["unknowns"]]
    citations = [_tender_citation(tenders_by_id[entry["tender_id"]]) for entry in kept]

    notes = [_provenance_note(s) for s in sources]
    if omitted_candidates:
        notes.append(
            f"{omitted_candidates} lower-relevance candidate(s) omitted from this response for "
            f"compactness (total_candidates={total_candidates}); the selected candidate is always "
            "included. Narrow the query/cantons/location to see different candidates, or call "
            "get_tender for a specific tender_id."
        )

    return _ok(
        "select_tenders",
        query=query,
        count=len(kept),
        total_candidates=total_candidates,
        omitted_candidates=omitted_candidates,
        candidates=[_compact_candidate(e) for e in kept],
        selected_tender_id=next((e["tender_id"] for e in entries if e["selected"]), None),
        sources=sources,
        citations=citations,
        notes=notes,
        unknowns=unknowns,
    )


@mcp.tool()
def get_tender(tender_id: str) -> dict[str, Any]:
    """Look up a single tender by id from the current search index.

    tender_id must match a `Tender.id` previously returned by search_tenders
    (e.g. "cloud-infra-2026"). Returns status="error" with the tender field
    set to null (UNKNOWN) if no tender with that id exists.

    For a tender actually sourced from a live SIMAP search (source ==
    "simap"), this additionally calls the real get_tender_details MCP tool
    using the project_id/publication_id propagated from that search result
    (see Tender.publication_id) — via the same simap_bridge/simap adapter
    chain search_tenders already uses, never a second connection path — and
    returns it under `details` (deadline, document availability, url).
    local_fallback/local_sample results never carry a publication_id, so
    this path never triggers for them — their response shape and behavior
    are completely unchanged. Nothing here is ever guessed: a missing
    publication_id or a failed/unavailable lookup is reported explicitly
    under `details.reason`, and the corresponding field stays null.
    """
    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("get_tender", f"Unknown tender id: {tender_id!r}", tender_id=tender_id, tender=None)

    result = _ok(
        "get_tender",
        tender_id=tender_id,
        tender=_dump(tender),
        sources=[tender.source.value],
        citations=[_tender_citation(tender)],
        notes=[_provenance_note(tender.source.value)],
        unknowns=[],
    )

    if tender.source == TenderSource.SIMAP:
        details = _fetch_tender_details(tender)
        result["details"] = details
        if not details["available"]:
            result["notes"].append(details["reason"])
            result["unknowns"].append(details["reason"])
        elif details.get("url"):
            # Confirmed by the real get_tender_details response -- not the
            # project_id-derived guess buildSimapUrl() would produce.
            result["citations"].append({"document": details["url"], "page": None, "section": None, "quote": None})

    return result


@mcp.tool()
def extract_requirements(tender_id: str) -> dict[str, Any]:
    """Retrieve a tender's documents and extract structured, cited requirements.

    Reuses DocumentRetrievalTool (src/agents/retrieval.py) and
    src.agents.ingestion.extract_requirements unmodified. Every requirement
    carries a `citation` back to its source document/section when known;
    facts that could not be determined are listed in `unknowns` rather than
    inferred.
    """
    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("extract_requirements", f"Unknown tender id: {tender_id!r}", tender_id=tender_id)

    try:
        documents = orchestrator.retrieval_tool.retrieve_documents(tender)
    except AdapterUnavailableError as exc:
        return _documents_blocked("extract_requirements", tender, exc, extracted_requirements=None)

    extracted = run_extraction(tender, documents)
    payload = _dump(extracted)
    return _ok(
        "extract_requirements",
        tender_id=tender_id,
        extracted_requirements=payload,
        sources=extracted.source_documents,
        citations=payload["citations"],
        notes=[_provenance_note(tender.source.value)],
        unknowns=extracted.unknowns,
    )


@mcp.tool()
def match_hpe_capabilities(tender_id: str) -> dict[str, Any]:
    """Match a tender's extracted requirements against the HPE capability profile.

    Reuses src/agents/matching.py `match_all` unmodified — deterministic
    keyword-overlap matching, no scoring/matching logic duplicated here.
    Every match is MATCH / PARTIAL_MATCH / NO_MATCH / UNKNOWN with a
    justification and, when available, a citation. UNKNOWN is used whenever
    the HPE profile (data/hpe_profile.json) has no sourced entry to confirm
    or deny a requirement — it is never guessed as a match.
    """
    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("match_hpe_capabilities", f"Unknown tender id: {tender_id!r}", tender_id=tender_id)

    try:
        documents = orchestrator.retrieval_tool.retrieve_documents(tender)
    except AdapterUnavailableError as exc:
        return _documents_blocked("match_hpe_capabilities", tender, exc, matches=[])

    extracted = run_extraction(tender, documents)
    matches = matching.match_all(extracted.all_requirements(), orchestrator.hpe_profile)
    payload = [_dump(m) for m in matches]
    unknown_descriptions = [m["requirement_description"] for m in payload if m["status"] == "unknown"]
    citations = [m["citation"] for m in payload if m["citation"] is not None]

    return _ok(
        "match_hpe_capabilities",
        tender_id=tender_id,
        matches=payload,
        sources=[*extracted.source_documents, "data/hpe_profile.json"],
        citations=citations,
        notes=[_provenance_note(tender.source.value)],
        unknowns=[*unknown_descriptions, *extracted.unknowns],
    )


def _run_qualification(orchestrator: WorkflowOrchestrator, tender: Tender):
    """retrieve -> extract -> qualify, via WorkflowOrchestrator.analyze_tender (unmodified)."""
    return orchestrator.analyze_tender(tender)


@mcp.tool()
def qualify_tender(tender_id: str) -> dict[str, Any]:
    """Run the full eligibility-gate + fit-scoring qualification for a tender.

    Reuses src/agents/qualification.py `qualify_tender` (itself composing
    eligibility_gate + fit_scoring + briefing, all unmodified) via
    WorkflowOrchestrator.analyze_tender — no scoring rule is reimplemented
    here. Returns the resulting GO / MAYBE / NO-GO recommendation, score
    breakdown, gaps, risks, and unknowns.
    """
    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("qualify_tender", f"Unknown tender id: {tender_id!r}", tender_id=tender_id)

    try:
        briefing_result = _run_qualification(orchestrator, tender)
    except AdapterUnavailableError as exc:
        return _documents_blocked("qualify_tender", tender, exc, briefing=None, qualification_status="BLOCKED")

    payload = _dump(briefing_result)
    sources = sorted({c["document"] for c in payload["citations"]} | {"data/hpe_profile.json"})
    return _ok(
        "qualify_tender",
        tender_id=tender_id,
        briefing=payload,
        sources=sources,
        citations=payload["citations"],
        notes=[_provenance_note(tender.source.value)],
        unknowns=payload["unknowns"],
    )


@mcp.tool()
def create_briefing(tender_id: str) -> dict[str, Any]:
    """Produce and persist the final structured qualification briefing for a tender.

    Runs the same pipeline as qualify_tender (search -> retrieve -> extract ->
    qualify, all unmodified) and additionally writes the briefing JSON to
    data/briefings/<tender_id>.json — mirroring
    `python -m src.pipeline analyze <id> --out ...` — so Hermes/NemoClaw gets
    back a durable, re-readable artifact rather than only an in-memory result.
    """
    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("create_briefing", f"Unknown tender id: {tender_id!r}", tender_id=tender_id)

    try:
        briefing_result = _run_qualification(orchestrator, tender)
    except AdapterUnavailableError as exc:
        return _documents_blocked(
            "create_briefing", tender, exc, briefing=None, qualification_status="BLOCKED", saved_to=None
        )

    payload = _dump(briefing_result)
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFINGS_DIR / f"{tender_id}.json"
    out_path.write_text(briefing_result.model_dump_json(indent=2), encoding="utf-8")

    sources = sorted({c["document"] for c in payload["citations"]} | {"data/hpe_profile.json"})
    return _ok(
        "create_briefing",
        tender_id=tender_id,
        briefing=payload,
        saved_to=str(out_path.relative_to(REPO_ROOT)) if out_path.is_relative_to(REPO_ROOT) else str(out_path),
        sources=sources,
        citations=payload["citations"],
        notes=[_provenance_note(tender.source.value)],
        unknowns=payload["unknowns"],
    )


_VALID_DECISIONS = {d.value for d in HumanDecision}


@mcp.tool()
def submit_human_decision(
    tender_id: str,
    decision: str,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a human reviewer's decision on a tender's qualification briefing.

    This is the mandatory last step of the workflow — a GO/MAYBE/NO-GO
    recommendation from qualify_tender/create_briefing is a machine-generated
    proposal, never a final decision. `decision` must be exactly one of
    "approved", "rejected", or "more_research" (src.schemas.briefing.
    HumanDecision) — any other value is rejected as an error rather than
    guessed or defaulted.

    Reuses src.agents.feedback.record_feedback unmodified (the same function
    app.py's Approve/Reject/Request-more-research buttons call): re-runs the
    same qualification pipeline as qualify_tender to get a fresh briefing,
    attaches the review to it, appends an entry to data/feedback_log.json,
    and persists the reviewed briefing to data/briefings/<tender_id>.json —
    the same file create_briefing writes, now carrying the human_review field.
    """
    if decision not in _VALID_DECISIONS:
        return _error(
            "submit_human_decision",
            f"Invalid decision {decision!r} — must be one of {sorted(_VALID_DECISIONS)}.",
            tender_id=tender_id,
        )

    orchestrator = _get_orchestrator()
    tender = _find_tender(orchestrator, tender_id)
    if tender is None:
        return _error("submit_human_decision", f"Unknown tender id: {tender_id!r}", tender_id=tender_id)

    try:
        briefing_result = _run_qualification(orchestrator, tender)
    except AdapterUnavailableError as exc:
        # No briefing exists to attach a decision to — nothing is recorded
        # to feedback_log.json/data/briefings, unlike the success path below.
        return _documents_blocked(
            "submit_human_decision",
            tender,
            exc,
            decision=decision,
            decision_recorded=False,
            briefing=None,
            qualification_status="BLOCKED",
            saved_to=None,
            feedback_log=None,
        )

    record_feedback(
        briefing_result,
        HumanDecision(decision),
        reviewer=reviewer,
        notes=notes,
        log_path=FEEDBACK_LOG_PATH,
    )

    payload = _dump(briefing_result)
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFINGS_DIR / f"{tender_id}.json"
    out_path.write_text(briefing_result.model_dump_json(indent=2), encoding="utf-8")

    sources = sorted({c["document"] for c in payload["citations"]} | {"data/hpe_profile.json"})
    return _ok(
        "submit_human_decision",
        tender_id=tender_id,
        decision=decision,
        briefing=payload,
        saved_to=str(out_path.relative_to(REPO_ROOT)) if out_path.is_relative_to(REPO_ROOT) else str(out_path),
        feedback_log=str(FEEDBACK_LOG_PATH.relative_to(REPO_ROOT))
        if FEEDBACK_LOG_PATH.is_relative_to(REPO_ROOT)
        else str(FEEDBACK_LOG_PATH),
        sources=sources,
        citations=payload["citations"],
        notes=[_provenance_note(tender.source.value)],
        unknowns=payload["unknowns"],
    )


def _render_readiness_memo(briefing: dict[str, Any]) -> str:
    """Build the DRAFT phase's only artifact: a bid-readiness memo.

    Deliberately not a bid/proposal letter — this repo has no source of real
    HPE proposal content to draw from, and inventing any (a claimed
    certification, reference, legal presence, or deadline) is exactly what
    the reliability constraints forbid. Every line below is copied from a
    field already present on the approved `QualificationBriefing` JSON
    (score, recommendation, capability_matches, gaps, risks, unknowns,
    next_actions, citations, deadlines) — nothing is computed or guessed
    here. An empty `deadlines` list is rendered as UNKNOWN, never a date.
    """
    tender = briefing["tender"]
    review = briefing.get("human_review") or {}
    lines: list[str] = [f"# Draft readiness memo — {tender['title']}", ""]

    lines.append(f"- Tender ID: {tender['id']}")
    lines.append(f"- Buyer: {tender.get('buyer') or 'UNKNOWN'}")
    lines.append(f"- Location: {tender.get('location') or 'UNKNOWN'}")
    lines.append(f"- Source: {tender.get('source_type') or tender.get('source', 'UNKNOWN')}")
    status_line = f"- Human review: {(review.get('decision') or 'UNKNOWN').upper()}"
    if review.get("reviewer"):
        status_line += f" by {review['reviewer']}"
    if review.get("timestamp"):
        status_line += f" on {review['timestamp']}"
    lines.append(status_line)
    if review.get("notes"):
        lines.append(f"- Reviewer notes: {review['notes']}")
    lines.append("")

    lines.append(f"## Recommendation: {briefing['recommendation']} — score {briefing['score']:.1f}/100 ({briefing['confidence']} confidence)")
    lines.append("")
    lines.append(briefing["executive_summary"])
    lines.append("")

    lines.append("## Submission deadline")
    deadlines = briefing.get("deadlines") or []
    if deadlines:
        for d in deadlines:
            doc = (d.get("citation") or {}).get("document", "UNKNOWN source")
            lines.append(f"- {d['label']}: {d['date']} (source: {doc})")
    else:
        lines.append("- UNKNOWN — no deadline could be confirmed from the retrieved documents.")
    lines.append("")

    matches = briefing.get("capability_matches") or []
    confirmed = [m for m in matches if m.get("status") == "match"]
    lines.append("## Confirmed HPE capability matches")
    if confirmed:
        for m in confirmed:
            cap = f" — HPE capability: {m['hpe_capability']}" if m.get("hpe_capability") else ""
            lines.append(f"- {m['requirement_description']}{cap}")
    else:
        lines.append("- None confirmed.")
    lines.append("")

    for heading, key, empty_note in (
        ("Confirmed gaps to close before bidding", "gaps", "None confirmed."),
        ("Open unknowns to resolve", "unknowns", "None."),
        ("Next actions", "next_actions", "None."),
    ):
        lines.append(f"## {heading}")
        items = briefing.get(key) or []
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append(f"- {empty_note}")
        lines.append("")

    lines.append("## Risks")
    risks = briefing.get("risks") or []
    if risks:
        for r in risks:
            lines.append(f"- [{r['severity'].upper()}] {r['description']}")
    else:
        lines.append("- None identified.")
    lines.append("")

    lines.append("## Sources / citations")
    citations = briefing.get("citations") or []
    if citations:
        seen: set[str] = set()
        for c in citations:
            doc = c.get("document")
            if not doc or doc in seen:
                continue
            seen.add(doc)
            loc = ", ".join(
                filter(None, [f"§{c['section']}" if c.get("section") else None, f"p.{c['page']}" if c.get("page") else None])
            )
            lines.append(f"- {doc}" + (f" ({loc})" if loc else ""))
    else:
        lines.append("- None recorded.")
    lines.append("")

    return "\n".join(lines)


@mcp.tool()
def create_draft(tender_id: str) -> dict[str, Any]:
    """Produce the final draft — the mandatory last step, only after a human
    has actually approved the qualification briefing.

    Reads the already-persisted briefing from data/briefings/<tender_id>.json
    (written by submit_human_decision) rather than recomputing qualification
    fresh, so the draft always matches exactly what was approved — never a
    newer recomputation that could disagree with it. Refuses
    (status="error", nothing written) unless that briefing's
    human_review.decision is "approved". The draft is a bid-readiness memo
    assembled only from fields already on that briefing (score,
    recommendation, confirmed matches, gaps, unknowns, risks, next actions,
    citations, deadline) — no proposal content, certification, reference, or
    deadline is invented; an unresolved deadline renders as UNKNOWN, never a
    guessed date.
    """
    briefing_path = BRIEFINGS_DIR / f"{tender_id}.json"
    if not briefing_path.exists():
        return _error(
            "create_draft",
            f"No qualification briefing found for {tender_id!r} — call qualify_tender or "
            "create_briefing first.",
            tender_id=tender_id,
        )

    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    decision = (briefing.get("human_review") or {}).get("decision")
    if decision != HumanDecision.APPROVED.value:
        return _error(
            "create_draft",
            f"Human review required before drafting — recorded decision is {decision!r}, not "
            f"{HumanDecision.APPROVED.value!r}. Call submit_human_decision with "
            f"decision={HumanDecision.APPROVED.value!r} first.",
            tender_id=tender_id,
        )

    draft_text = _render_readiness_memo(briefing)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DRAFTS_DIR / f"{tender_id}.md"
    out_path.write_text(draft_text, encoding="utf-8")

    citations = briefing.get("citations") or []
    sources = sorted({c["document"] for c in citations if c.get("document")})
    draft_note = (
        "Draft assembled only from fields already recorded on the approved qualification "
        "briefing — no new content invented."
    )
    return _ok(
        "create_draft",
        tender_id=tender_id,
        draft_markdown=draft_text,
        saved_to=str(out_path.relative_to(REPO_ROOT)) if out_path.is_relative_to(REPO_ROOT) else str(out_path),
        sources=sources,
        citations=citations,
        notes=[draft_note],
        unknowns=briefing.get("unknowns") or [],
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
