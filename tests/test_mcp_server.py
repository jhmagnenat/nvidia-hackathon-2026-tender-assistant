"""Tests for the HPE tender qualification MCP stdio server (src/mcp_server.py).

Two layers:
- direct calls to the tool functions (src.mcp_server.search_tenders, etc.),
  since @mcp.tool() leaves the underlying function callable and this is the
  fastest way to check the JSON contract (sources/citations/unknowns, UNKNOWN
  handling, no-SIMAP-claim-on-local-data);
- one true protocol-level test that drives the actual FastMCP server over an
  in-memory MCP ClientSession (mcp.shared.memory), proving tool discovery and
  tool-call responses are valid MCP, not just "the Python function works".

No asyncio pytest plugin is added as a dependency — the protocol test just
wraps its body in asyncio.run().
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from unittest import mock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from src import mcp_server
from src.adapters.tender_search import REPO_ROOT, SimapAdapter
from src.schemas.common import ResearchMode
from src.schemas.tender import Tender, TenderSource

_FAKE_SERVER_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]


def _fake_simap_adapter() -> SimapAdapter:
    """Same fake-stdio-server pattern used in test_tender_search.py /
    test_simap_bridge_client.py — a real SimapAdapter, just pointed at the
    Python stand-in server instead of the real Node package."""
    return SimapAdapter(node_command=sys.executable, args=_FAKE_SERVER_ARGS, cwd=str(REPO_ROOT))


def _simap_tender(tender_id: str = "PRJ-0001", publication_id: str | None = "PUBID-0001") -> Tender:
    """A tender shaped exactly like what _parse_search_tenders_markdown
    would have produced from a real search_tenders response — source=SIMAP,
    research_mode=SIMAP_MCP, and (unless explicitly omitted) the real
    propagated publication_id."""
    return Tender(
        id=tender_id,
        title="Fourniture de services d'infrastructure cloud hybride",
        source=TenderSource.SIMAP,
        research_mode=ResearchMode.SIMAP_MCP,
        publication_id=publication_id,
    )


@pytest.fixture(autouse=True)
def _reset_tender_cache():
    """_tender_cache is process-lifetime by design (see its docstring in
    src/mcp_server.py) — reset it between tests so one test's cache can't
    mask another's (e.g. the call-counting test below needs a clean slate)."""
    mcp_server._tender_cache.clear()
    yield
    mcp_server._tender_cache.clear()


def test_search_tenders_returns_local_sample_labeled_results():
    result = mcp_server.search_tenders("cloud infrastructure cybersecurity")
    assert result["status"] == "ok"
    assert result["count"] == len(result["tenders"])
    assert result["tenders"], "expected at least one match from the local sample index"
    assert all(t["source"] == "local_sample" for t in result["tenders"])
    # Rule: never claim local sample data came from SIMAP.
    assert any("NOT a live SIMAP" in note for note in result["notes"])
    assert not any("live simap" in note.lower() and "not" not in note.lower() for note in result["notes"])
    assert result["citations"] and all(c["document"] == "data/sample_tenders.json" for c in result["citations"])


def test_search_tenders_no_match_has_empty_results_and_note():
    result = mcp_server.search_tenders("xyzzy nonexistent query terms zzz")
    assert result["status"] == "ok"
    assert result["count"] == 0
    assert result["tenders"] == []
    assert result["notes"] == ["No tenders matched this query."]


# --- select_tenders (the explicit SELECT phase, exposed on this same server) ---


def test_select_tenders_tool_selects_a_relevant_local_candidate():
    result = mcp_server.select_tenders("cloud infrastructure managed services cybersecurity")

    assert result["status"] == "ok"
    assert result["count"] >= 1
    assert result["total_candidates"] == result["count"]
    assert result["omitted_candidates"] == 0
    assert result["selected_tender_id"] is not None
    selected = next(c for c in result["candidates"] if c["selected"])
    assert selected["tender_id"] == result["selected_tender_id"]
    assert selected["source_type"] == "local_fallback"
    assert selected["exclusion_reason"] is None
    assert selected["reason_summary"]
    # The actual selection justification — not just the generic summary.
    assert selected["selection_reasons"]
    assert isinstance(selected["selection_reasons"], list)
    assert 1 <= len(selected["selection_reasons"]) <= mcp_server._MAX_SELECTION_REASONS
    assert all(len(r) <= mcp_server._MAX_REASON_LENGTH for r in selected["selection_reasons"])
    # Compactness: no verbose full per-dimension breakdown reaches the MCP response.
    assert "reasons" not in selected
    assert "documents" not in selected


def test_select_tenders_tool_no_results():
    result = mcp_server.select_tenders("xyzzy nonexistent query terms zzz")
    assert result["status"] == "ok"
    assert result["count"] == 0
    assert result["total_candidates"] == 0
    assert result["omitted_candidates"] == 0
    assert result["candidates"] == []
    assert result["selected_tender_id"] is None


def test_select_tenders_tool_excludes_an_already_awarded_simap_candidate():
    """Requirement — select_tenders as an MCP tool must produce the same
    exclusion behavior as the underlying agent function: an already-awarded
    candidate is never selected, and the reason is explicit."""
    orchestrator = mcp_server._get_orchestrator()
    adapter = _fake_simap_adapter()

    with (
        mock.patch.object(orchestrator, "search", lambda query, filters=None: adapter.search(query)),
        mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]),
    ):
        result = mcp_server.select_tenders("with-awarded cloud infrastructure")

    assert result["status"] == "ok"
    assert result["count"] == 3
    assert result["total_candidates"] == 3
    assert result["omitted_candidates"] == 0
    awarded = next(c for c in result["candidates"] if c["tender_id"] == "PRJ-0003")
    assert awarded["selected"] is False
    assert awarded["status"] == "already_awarded"
    assert awarded["exclusion_reason"] is not None
    assert "awarded" in awarded["reason_summary"].lower()
    assert awarded["selection_reasons"]
    assert 1 <= len(awarded["selection_reasons"]) <= mcp_server._MAX_SELECTION_REASONS
    assert result["selected_tender_id"] not in (None, "PRJ-0003")
    assert all(c["source_type"] == "simap_mcp" for c in result["candidates"])
    assert all(c["project_id"] == c["tender_id"] for c in result["candidates"])
    assert {c["publication_id"] for c in result["candidates"]} == {"PUBID-0001", "PUBID-0002", "PUBID-0003"}
    for c in result["candidates"]:
        assert c["selection_reasons"]
        assert "reasons" not in c
        assert "documents" not in c
        assert "markdown" not in c


def test_provenance_note_for_simap_mcp_source_is_not_unknown():
    """Regression for the live-Hermes finding — select_tenders' `sources`
    are keyed by `source_type` (ResearchMode: "simap_mcp"/"local_fallback"),
    not `Tender.source.value` (TenderSource: "simap"/"tavily"/"local_sample")
    that search_tenders uses. _provenance_note must recognize both key sets,
    so a genuinely live SIMAP-via-bridge candidate is never mislabeled
    "Unrecognized source ... provenance UNKNOWN"."""
    note = mcp_server._provenance_note("simap_mcp")
    assert "unrecognized" not in note.lower()
    assert "unknown" not in note.lower()
    assert "live simap" in note.lower()


def test_provenance_note_for_local_fallback_is_explicitly_non_live():
    """local_fallback (and local_sample) must stay explicitly labeled as
    NOT a live SIMAP connection — the fix for simap_mcp must not blur that
    distinction."""
    fallback_note = mcp_server._provenance_note("local_fallback")
    sample_note = mcp_server._provenance_note("local_sample")
    assert "not a live simap" in fallback_note.lower()
    assert "not a live simap" in sample_note.lower()


def test_select_tenders_tool_reports_accurate_provenance_for_live_simap_candidates():
    """The select_tenders MCP response for real SIMAP-sourced candidates
    (source_type="simap_mcp") must carry an accurate live-SIMAP provenance
    note, not the "Unrecognized source" fallback."""
    orchestrator = mcp_server._get_orchestrator()
    adapter = _fake_simap_adapter()

    with (
        mock.patch.object(orchestrator, "search", lambda query, filters=None: adapter.search(query)),
        mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]),
    ):
        result = mcp_server.select_tenders("cloud infrastructure")

    assert all(c["source_type"] == "simap_mcp" for c in result["candidates"])
    assert any("live simap" in note.lower() for note in result["notes"])
    assert not any("unrecognized source" in note.lower() for note in result["notes"])
    assert not any("provenance unknown" in note.lower() for note in result["notes"])


def test_select_tenders_tool_query_relevance_gate_still_null_with_accurate_simap_provenance():
    """Combines both fixes: an all-irrelevant SIMAP candidate set must still
    have selected_tender_id=null (the relevance gate), while the response's
    provenance note correctly describes the live simap_mcp source instead of
    claiming it's unrecognized/unknown."""
    orchestrator = mcp_server._get_orchestrator()
    wastewater_simap = Tender(
        id="PRJ-9001",
        title="Construction d'une station d'épuration des eaux usées",
        scope="Travaux de génie civil pour le traitement des eaux usées.",
        source=TenderSource.SIMAP,
        research_mode=ResearchMode.SIMAP_MCP,
        publication_id="PUBID-9001",
    )

    with mock.patch.object(orchestrator, "search", lambda query, filters=None: [wastewater_simap]):
        result = mcp_server.select_tenders("cloud infrastructure, managed services and cybersecurity")

    assert result["selected_tender_id"] is None
    assert result["candidates"][0]["source_type"] == "simap_mcp"
    assert any("live simap" in note.lower() for note in result["notes"])
    assert not any("unrecognized source" in note.lower() for note in result["notes"])


def test_select_tenders_tool_query_relevance_gate_returns_no_selection_for_unrelated_candidates():
    """Regression for the live-Hermes finding — an unrelated tender (e.g.
    wastewater treatment plant construction) must not be auto-selected for a
    "cloud infrastructure, managed services and cybersecurity" query just
    because it's the only/least-bad actionable candidate. Compact response
    shape (selection_reasons/reason_summary/source_type/etc.) stays exactly
    as before — only `selected`/`exclusion_reason`/`selected_tender_id`
    change."""
    orchestrator = mcp_server._get_orchestrator()
    wastewater = Tender(
        id="wastewater-2026",
        title="Construction d'une station d'épuration des eaux usées",
        scope="Travaux de génie civil pour le traitement des eaux usées.",
        source=TenderSource.LOCAL_SAMPLE,
        research_mode=ResearchMode.LOCAL_FALLBACK,
    )

    with mock.patch.object(orchestrator, "search", lambda query, filters=None: [wastewater]):
        result = mcp_server.select_tenders("cloud infrastructure, managed services and cybersecurity")

    assert result["status"] == "ok"
    assert result["selected_tender_id"] is None
    assert result["count"] == 1
    entry = result["candidates"][0]
    assert entry["selected"] is False
    assert entry["exclusion_reason"] == "No meaningful keyword match with the requested query."
    assert entry["source_type"] == "local_fallback"
    assert entry["project_id"] == "wastewater-2026"
    # Compact serializer shape unchanged: still bounded/truncated selection_reasons,
    # still a reason_summary, still no raw `reasons`/`documents`.
    assert entry["selection_reasons"]
    assert 1 <= len(entry["selection_reasons"]) <= mcp_server._MAX_SELECTION_REASONS
    assert entry["reason_summary"] == entry["exclusion_reason"]
    assert "reasons" not in entry
    assert "documents" not in entry
    assert any("no meaningful keyword match" in u.lower() for u in result["unknowns"])


def test_select_tenders_tool_caps_candidates_but_always_keeps_the_selected_one(monkeypatch):
    """Requirement — compact response: a broad query returning many more
    candidates than _MAX_CANDIDATES_IN_RESPONSE must not serialize all of
    them, but must still report the true total and always include the
    selected candidate's own entry, never silently drop it."""
    orchestrator = mcp_server._get_orchestrator()
    many_tenders = [
        Tender(
            id=f"local-{i}",
            title="Fourniture de mobilier de bureau",
            source=TenderSource.LOCAL_SAMPLE,
            research_mode=ResearchMode.LOCAL_FALLBACK,
            scope="Mobilier de bureau ergonomique.",
        )
        for i in range(mcp_server._MAX_CANDIDATES_IN_RESPONSE + 5)
    ]
    # One clearly-relevant candidate, ranked to win selection regardless of
    # where it lands among the many irrelevant ones above.
    winner = Tender(
        id="cloud-winner",
        title="Fourniture de services d'infrastructure cloud hybride",
        source=TenderSource.LOCAL_SAMPLE,
        research_mode=ResearchMode.LOCAL_FALLBACK,
        scope="Infrastructure cloud hybride et support technique.",
    )
    all_tenders = [*many_tenders, winner]

    with mock.patch.object(orchestrator, "search", lambda query, filters=None: all_tenders):
        result = mcp_server.select_tenders("cloud infrastructure managed services cybersecurity")

    assert result["status"] == "ok"
    assert result["total_candidates"] == len(all_tenders)
    assert result["omitted_candidates"] == result["total_candidates"] - result["count"]
    assert result["omitted_candidates"] > 0
    assert result["count"] <= mcp_server._MAX_CANDIDATES_IN_RESPONSE + 1
    assert result["selected_tender_id"] == "cloud-winner"
    winner_entry = next(c for c in result["candidates"] if c["tender_id"] == "cloud-winner" and c["selected"])
    assert winner_entry["selection_reasons"]
    assert any("omitted" in note.lower() for note in result["notes"])


def test_compact_candidate_selection_reasons_are_derived_from_original_reasons_and_bounded():
    """Requirement — the compact serializer must not replace the real
    selection justification with only a generic summary: `selection_reasons`
    must be verbatim excerpts of the underlying `reasons` list (never
    invented), capped at _MAX_SELECTION_REASONS entries, each individually
    capped at _MAX_REASON_LENGTH characters, keeping the first (most
    relevant, per tender_selection.select_tenders' ordering) ones."""
    long_reason = "Cloud infrastructure: " + ("x" * 400)
    entry = {
        "tender_id": "t-1",
        "project_id": "t-1",
        "publication_id": "PUBID-1",
        "title": "Some tender",
        "source_type": "simap_mcp",
        "relevance_score": 82.5,
        "status": "open",
        "reasons": [
            "Query relevance: 100% of the search query's keywords found in this tender's title/scope.",
            "Cloud infrastructure: 50% keyword overlap with HPE capabilities (hybrid cloud).",
            long_reason,
            "Deadline: in 30 day(s) — comfortable lead time.",
            "Documents: 2 available.",
            "Publication type 'tender' is an open/ongoing procurement step.",
        ],
        "unknowns": [],
        "exclusion_reason": None,
        "selected": True,
    }

    compact = mcp_server._compact_candidate(entry)

    assert compact["selection_reasons"] == [
        entry["reasons"][0],
        entry["reasons"][1],
        long_reason[: mcp_server._MAX_REASON_LENGTH - 1].rstrip() + "…",
    ]
    assert len(compact["selection_reasons"]) == mcp_server._MAX_SELECTION_REASONS
    assert all(len(r) <= mcp_server._MAX_REASON_LENGTH for r in compact["selection_reasons"])
    # reason_summary stays, but is not the only explanation returned.
    assert compact["reason_summary"]
    assert compact["selection_reasons"] != [compact["reason_summary"]]
    assert "reasons" not in compact
    assert "documents" not in compact
    for field in (
        "tender_id",
        "project_id",
        "publication_id",
        "title",
        "source_type",
        "relevance_score",
        "status",
        "selected",
        "exclusion_reason",
        "unknowns",
    ):
        assert compact[field] == entry[field]


def test_compact_candidate_short_reasons_list_is_not_padded():
    """Fewer than _MAX_SELECTION_REASONS real reasons must not be padded
    with invented content — selection_reasons is simply shorter."""
    entry = {
        "tender_id": "t-2",
        "project_id": "t-2",
        "publication_id": None,
        "title": "Another tender",
        "source_type": "local_fallback",
        "relevance_score": 10.0,
        "status": "unknown",
        "reasons": ["Only one real reason recorded."],
        "unknowns": ["Publication status UNKNOWN — no status field available."],
        "exclusion_reason": "Not the highest-relevance actionable candidate.",
        "selected": False,
    }

    compact = mcp_server._compact_candidate(entry)

    assert compact["selection_reasons"] == ["Only one real reason recorded."]
    assert compact["reason_summary"] == entry["exclusion_reason"]


def test_select_tenders_tool_populates_the_cache_for_a_later_get_tender_call():
    """Confirms select_tenders participates in the same dedup cache as
    search_tenders — a get_tender call right after it for the same id must
    not repeat the search."""
    orchestrator = mcp_server._get_orchestrator()
    call_count = 0
    real_search = orchestrator.search

    def counting_search(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_search(*args, **kwargs)

    with mock.patch.object(orchestrator, "search", counting_search):
        select_result = mcp_server.select_tenders("cloud infrastructure managed services cybersecurity")
        assert call_count == 1
        get_result = mcp_server.get_tender(select_result["selected_tender_id"])
        assert call_count == 1  # already cached by select_tenders -- no second search

    assert get_result["status"] == "ok"


def test_get_tender_known_id():
    result = mcp_server.get_tender("cloud-infra-2026")
    assert result["status"] == "ok"
    assert result["tender"]["id"] == "cloud-infra-2026"
    assert result["tender"]["source"] == "local_sample"
    assert result["citations"] == [{"document": "data/sample_tenders.json", "page": None, "section": None, "quote": None}]


def test_get_tender_unknown_id_is_an_error_not_a_guess():
    result = mcp_server.get_tender("does-not-exist-2099")
    assert result["status"] == "error"
    assert result["tender"] is None
    assert "does-not-exist-2099" in result["message"]


# --- get_tender's SIMAP get_tender_details propagation (B) -----------------
#
# These seed _tender_cache directly with a synthetic SIMAP-sourced Tender
# (exactly the shape _parse_search_tenders_markdown would have produced from
# a real search_tenders response) and monkeypatch mcp_server.get_search_adapters
# so get_tender's real get_tender_details call goes to the fake stdio MCP
# server (tests/fixtures/fake_simap_mcp_server.py) instead of attempting a
# real network call from this VM — this repo's environment has no path to
# call SIMAP directly, and never should (see src/adapters/tender_search.py).


def test_get_tender_propagates_publication_id_and_project_id_end_to_end():
    """Requirement 1 — publication_id/project_id propagation: get_tender
    must call get_tender_details with *exactly* the ids carried on the
    selected Tender (project_id = tender.id, publication_id =
    tender.publication_id), and the real deadline it returns must reach the
    caller under details.submission_deadline — not fabricated, not dropped."""
    tender = _simap_tender(tender_id="PRJ-0001", publication_id="PUBID-0001")
    mcp_server._tender_cache[tender.id] = tender

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[_fake_simap_adapter()]):
        result = mcp_server.get_tender("PRJ-0001")

    assert result["status"] == "ok"
    assert result["tender"]["id"] == "PRJ-0001"
    assert result["tender"]["publication_id"] == "PUBID-0001"
    assert "details" in result
    details = result["details"]
    assert details["available"] is True
    # The fake server only returns real content when BOTH ids it receives
    # match this exact tender (see fake_simap_mcp_server.py's
    # get_tender_details) — a non-fabricated deadline coming back proves the
    # real ids were forwarded, not substituted or dropped.
    assert details["submission_deadline"] == "2026-11-02"
    assert details["has_project_documents"] is True
    assert details["url"] == "https://www.simap.ch/en/project-detail/PRJ-0001"


def test_get_tender_uses_the_selected_tenders_own_ids_not_a_mismatched_pair():
    """Requirement 1/3 — if the ids don't correspond to the selected tender
    (e.g. a stale/wrong publication_id), get_tender_details must honestly
    report unavailable via the fake server's real "not found" response —
    never silently substitute a different tender's details."""
    # The fake server's get_tender_details only checks projectId, so to
    # actually exercise a real mismatch we target an unknown project_id.
    mismatched = _simap_tender(tender_id="not-a-real-project-id", publication_id="PUBID-0001")
    mcp_server._tender_cache[mismatched.id] = mismatched

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[_fake_simap_adapter()]):
        result = mcp_server.get_tender("not-a-real-project-id")

    assert result["details"]["available"] is False
    assert "not found" in result["details"]["reason"].lower()
    assert result["details"]["submission_deadline"] is None


def test_get_tender_does_not_repeat_the_search_call_across_two_lookups():
    """Requirement 2 — no unnecessary repeated *search* calls: looking up
    the same SIMAP tender twice must not re-issue orchestrator.search()
    (already cached — see _tender_cache), even though each call does
    perform its own real get_tender_details call (a different, deliberate
    MCP call each time get_tender is explicitly invoked, not a repeat of
    the same search)."""
    tender = _simap_tender()
    mcp_server._tender_cache[tender.id] = tender
    orchestrator = mcp_server._get_orchestrator()
    call_count = 0
    real_search = orchestrator.search

    def counting_search(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_search(*args, **kwargs)

    with (
        mock.patch.object(orchestrator, "search", counting_search),
        mock.patch.object(mcp_server, "get_search_adapters", return_value=[_fake_simap_adapter()]),
    ):
        mcp_server.get_tender("PRJ-0001")
        mcp_server.get_tender("PRJ-0001")

    assert call_count == 0, "PRJ-0001 was already cached -- orchestrator.search() must not be called at all"


def test_get_tender_never_silently_falls_back_when_no_simap_adapter_is_available():
    """Requirement 3 — no silent fallback: when no SIMAP adapter is
    available at all (e.g. simap_bridge/simap both unconfigured, exactly
    this VM's real state), get_tender must not omit `details`, return an
    empty-but-successful details block, or substitute local data — it must
    say explicitly, in details.reason, that no SIMAP adapter is available."""
    tender = _simap_tender()
    mcp_server._tender_cache[tender.id] = tender

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[]):
        result = mcp_server.get_tender("PRJ-0001")

    assert result["status"] == "ok"  # the tender itself was still found (from cache)
    assert result["details"]["available"] is False
    assert "no simap adapter" in result["details"]["reason"].lower()
    assert result["details"]["submission_deadline"] is None
    assert result["details"]["reason"] in result["unknowns"]
    assert result["details"]["reason"] in result["notes"]


def test_get_tender_reports_bridge_unavailable_explicitly_not_a_silent_gap():
    """Requirement 5 — explicit behavior when the bridge specifically is
    unavailable: a SimapBridgeAdapter with no SIMAP_BRIDGE_URL configured
    (this VM's actual default state) must surface its own AdapterUnavailableError
    message in details.reason, not just vanish."""
    from src.adapters.simap_bridge_client import SimapBridgeAdapter

    tender = _simap_tender()
    mcp_server._tender_cache[tender.id] = tender
    unconfigured_bridge = SimapBridgeAdapter(base_url=None)
    assert unconfigured_bridge.available is False  # confirms this test exercises the real "not configured" path

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[unconfigured_bridge]):
        result = mcp_server.get_tender("PRJ-0001")

    assert result["details"]["available"] is False
    assert "no simap adapter" in result["details"]["reason"].lower()


def test_get_tender_without_publication_id_is_explicit_not_a_guess():
    """A SIMAP tender search somehow produced with no publication_id (e.g. a
    real response missing that line) must report that specific reason —
    never attempt a call with a fabricated/derived id."""
    tender = _simap_tender(publication_id=None)
    mcp_server._tender_cache[tender.id] = tender

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[_fake_simap_adapter()]):
        result = mcp_server.get_tender("PRJ-0001")

    assert result["details"]["available"] is False
    assert "publication_id" in result["details"]["reason"]
    assert result["details"]["submission_deadline"] is None


def test_get_tender_source_type_is_preserved_through_the_details_call():
    """Requirement 4 — source_type conservation: fetching real
    get_tender_details must not alter the tender's own source/source_type —
    it stays "simap_mcp" throughout, and never flips to "local_fallback"."""
    tender = _simap_tender()
    mcp_server._tender_cache[tender.id] = tender

    with mock.patch.object(mcp_server, "get_search_adapters", return_value=[_fake_simap_adapter()]):
        result = mcp_server.get_tender("PRJ-0001")

    assert result["tender"]["source_type"] == "simap_mcp"
    assert result["tender"]["research_mode"] == "simap_mcp"


def test_get_tender_local_fallback_behavior_is_completely_unchanged():
    """Requirement 4 — local_fallback tenders keep source_type
    "local_fallback" and, critically, get_tender's response shape for them
    is byte-for-byte what it was before get_tender_details existed: no
    `details` key at all, no SIMAP call attempted (get_search_adapters is
    monkeypatched to raise if it's ever even called, to prove this)."""
    with mock.patch.object(mcp_server, "get_search_adapters", side_effect=AssertionError("must not be called for a local_fallback tender")):
        result = mcp_server.get_tender("cloud-infra-2026")

    assert result["status"] == "ok"
    assert result["tender"]["source"] == "local_sample"
    assert result["tender"]["source_type"] == "local_fallback"
    assert "details" not in result


def _make_live_search_intercept_the_generic_fallback(monkeypatch):
    """Regression setup for the "Unknown tender id" bug: in the NemoClaw
    sandbox, orchestrator.search("") can resolve to a live adapter
    (simap_bridge/simap) instead of local_sample whenever one reports
    itself `.available` — TenderSearchTool only moves to the next candidate
    on AdapterUnavailableError, never merely on "few/no results" (see
    src/agents/search.py). That live call returning e.g. no results for an
    empty query means the synthetic sample fixtures in
    data/sample_tenders.json are never reached by _find_tender's generic
    fallback, even though data/sample_tenders/<id>/ is real and complete on
    disk. Simulated here by monkeypatching the shared orchestrator's own
    `.search` to behave exactly like that interception, without needing a
    real live adapter."""
    orchestrator = mcp_server._get_orchestrator()
    monkeypatch.setattr(orchestrator, "search", lambda query, filters=None: [])


def test_get_tender_resolves_a_sample_id_even_when_the_generic_fallback_is_intercepted(monkeypatch):
    """Requirement — get_tender("cloud-infra-2026") must not report "Unknown
    tender id" just because a live adapter intercepted the generic
    orchestrator.search("") fallback: the local sample registry
    (data/sample_tenders.json) is always reachable by id as a last resort."""
    _make_live_search_intercept_the_generic_fallback(monkeypatch)

    result = mcp_server.get_tender("cloud-infra-2026")

    assert result["status"] == "ok"
    assert result["tender"]["id"] == "cloud-infra-2026"
    assert result["tender"]["source"] == "local_sample"
    assert result["tender"]["source_type"] == "local_fallback"  # never disguised as live


def test_qualify_tender_resolves_a_sample_id_even_when_the_generic_fallback_is_intercepted(monkeypatch):
    """Same bug, through qualify_tender — the tool actually reported broken
    in Hermes/NemoClaw ("Unknown tender id" for cloud-infra-2026 despite the
    fixture files being present and readable)."""
    _make_live_search_intercept_the_generic_fallback(monkeypatch)

    result = mcp_server.qualify_tender("cloud-infra-2026")

    assert result["status"] == "ok"
    assert "qualification_status" not in result  # a real qualification ran, not a BLOCKED stub
    assert result["briefing"]["recommendation"] in {"GO", "MAYBE", "NO-GO"}
    assert result["briefing"]["tender"]["source_type"] == "local_fallback"


def test_get_tender_unknown_id_still_reports_unknown_even_after_the_local_sample_fallback(monkeypatch):
    """The new last-resort local_sample lookup must not mask a genuinely
    unknown id — it only ever matches an exact id already present in
    data/sample_tenders.json, never a fuzzy/nearest match."""
    _make_live_search_intercept_the_generic_fallback(monkeypatch)

    result = mcp_server.get_tender("does-not-exist-2099")

    assert result["status"] == "error"
    assert "Unknown tender id" in result["message"]


def test_repeated_tool_calls_for_the_same_tender_do_not_repeat_the_search_call(monkeypatch):
    """Reliability constraint — never repeat the same MCP call unnecessarily:
    processing one tender through get_tender -> extract_requirements ->
    match_hpe_capabilities -> qualify_tender must issue at most one real
    orchestrator.search() call in total, not one per tool."""
    orchestrator = mcp_server._get_orchestrator()
    call_count = 0
    real_search = orchestrator.search

    def counting_search(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_search(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "search", counting_search)

    tender_id = "cloud-infra-2026"
    assert mcp_server.get_tender(tender_id)["status"] == "ok"
    assert mcp_server.extract_requirements(tender_id)["status"] == "ok"
    assert mcp_server.match_hpe_capabilities(tender_id)["status"] == "ok"
    assert mcp_server.qualify_tender(tender_id)["status"] == "ok"

    assert call_count == 1, f"expected exactly 1 orchestrator.search() call across 4 tool calls, got {call_count}"


def test_search_tenders_populates_the_cache_so_a_later_lookup_needs_no_search(monkeypatch):
    orchestrator = mcp_server._get_orchestrator()
    call_count = 0
    real_search = orchestrator.search

    def counting_search(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_search(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "search", counting_search)

    search_result = mcp_server.search_tenders("cloud infrastructure")
    assert search_result["status"] == "ok" and search_result["tenders"]
    seen_id = search_result["tenders"][0]["id"]
    assert call_count == 1

    assert mcp_server.get_tender(seen_id)["status"] == "ok"
    assert call_count == 1, "get_tender for an id already returned by search_tenders must not search again"


def test_extract_requirements_has_citations_and_unknowns():
    result = mcp_server.extract_requirements("cloud-infra-2026")
    assert result["status"] == "ok"
    extracted = result["extracted_requirements"]
    assert extracted["mandatory_requirements"], "fixture tender has mandatory requirements"
    for req in extracted["mandatory_requirements"]:
        assert req["citation"] is not None
        assert req["citation"]["document"]
    assert isinstance(result["unknowns"], list)
    assert result["sources"] == extracted["source_documents"]


def test_extract_requirements_unknown_tender_id():
    result = mcp_server.extract_requirements("does-not-exist-2099")
    assert result["status"] == "error"


def test_match_hpe_capabilities_uses_unknown_not_fabricated_match():
    # office-furniture-2026 has nothing to do with any HPE capability, so every
    # requirement should resolve to NO_MATCH/UNKNOWN, never a fabricated MATCH.
    result = mcp_server.match_hpe_capabilities("office-furniture-2026")
    assert result["status"] == "ok"
    statuses = {m["status"] for m in result["matches"]}
    assert "match" not in statuses
    assert statuses & {"unknown", "no_match"}
    assert "data/hpe_profile.json" in result["sources"]
    for m in result["matches"]:
        assert m["justification"]


def test_match_hpe_capabilities_certification_gap_is_unknown_never_fabricated():
    result = mcp_server.match_hpe_capabilities("cloud-infra-2026")
    assert result["status"] == "ok"
    cert_matches = [
        m for m in result["matches"] if "certif" in m["requirement_description"].lower() or "iso" in m["requirement_description"].lower()
    ]
    # data/hpe_profile.json ships zero certifications, so any certification
    # requirement must be UNKNOWN (never asserted as a match without a source).
    assert cert_matches
    assert all(m["status"] in {"unknown", "no_match"} for m in cert_matches)


def test_qualify_tender_end_to_end_reuses_existing_scoring():
    result = mcp_server.qualify_tender("cloud-infra-2026")
    assert result["status"] == "ok"
    briefing = result["briefing"]
    assert briefing["recommendation"] in {"GO", "MAYBE", "NO-GO"}
    assert 0 <= briefing["score"] <= 100
    assert result["citations"]
    assert "data/hpe_profile.json" in result["sources"]


def test_qualify_tender_office_furniture_is_no_go():
    result = mcp_server.qualify_tender("office-furniture-2026")
    assert result["status"] == "ok"
    assert result["briefing"]["recommendation"] == "NO-GO"


def test_create_briefing_persists_json_matching_qualify_tender(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    result = mcp_server.create_briefing("cloud-infra-2026")
    assert result["status"] == "ok"
    out_file = tmp_path / "cloud-infra-2026.json"
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["tender"]["id"] == "cloud-infra-2026"
    assert saved["recommendation"] == result["briefing"]["recommendation"]
    assert result["saved_to"].endswith("cloud-infra-2026.json")


def test_create_briefing_unknown_tender_does_not_write_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    result = mcp_server.create_briefing("does-not-exist-2099")
    assert result["status"] == "error"
    assert list(tmp_path.glob("*.json")) == []


def test_create_draft_refuses_without_a_prior_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "DRAFTS_DIR", tmp_path / "drafts")

    result = mcp_server.create_draft("cloud-infra-2026")

    assert result["status"] == "error"
    assert not (tmp_path / "drafts").exists()


def test_create_draft_refuses_when_decision_is_not_approved(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", tmp_path / "feedback_log.json")
    monkeypatch.setattr(mcp_server, "DRAFTS_DIR", tmp_path / "drafts")

    mcp_server.submit_human_decision("cloud-infra-2026", "more_research")
    result = mcp_server.create_draft("cloud-infra-2026")

    assert result["status"] == "error"
    assert "approved" in result["message"]
    assert not (tmp_path / "drafts").exists()


def test_create_draft_after_approval_writes_a_memo_from_the_approved_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", tmp_path / "feedback_log.json")
    drafts_dir = tmp_path / "drafts"
    monkeypatch.setattr(mcp_server, "DRAFTS_DIR", drafts_dir)

    approved = mcp_server.submit_human_decision("cloud-infra-2026", "approved", reviewer="jj")
    result = mcp_server.create_draft("cloud-infra-2026")

    assert result["status"] == "ok"
    out_file = drafts_dir / "cloud-infra-2026.md"
    assert out_file.exists()
    memo = out_file.read_text(encoding="utf-8")
    assert result["draft_markdown"] == memo

    # Every fact in the memo is copied from the already-approved briefing, not recomputed.
    briefing = approved["briefing"]
    assert briefing["recommendation"] in memo
    assert f"{briefing['score']:.1f}" in memo
    assert "jj" in memo
    assert "APPROVED" in memo
    assert result["citations"] == briefing["citations"]


def test_create_draft_never_fabricates_a_missing_deadline():
    """Unit-tests the memo renderer directly with a synthetic briefing whose
    deadlines list is empty -- must render UNKNOWN, never a guessed date."""
    synthetic_briefing = {
        "tender": {"id": "t-1", "title": "Synthetic tender", "buyer": None, "location": None, "source_type": "local_fallback"},
        "human_review": {"decision": "approved", "reviewer": "jj", "timestamp": "2026-09-20T00:00:00Z", "notes": None},
        "recommendation": "MAYBE",
        "score": 55.0,
        "confidence": "MEDIUM",
        "executive_summary": "Example.",
        "deadlines": [],
        "capability_matches": [],
        "gaps": [],
        "unknowns": [],
        "risks": [],
        "next_actions": [],
        "citations": [],
    }

    memo = mcp_server._render_readiness_memo(synthetic_briefing)

    assert "UNKNOWN" in memo
    assert "no deadline could be confirmed" in memo
    # No date-shaped string was invented anywhere near the deadline section.
    deadline_section = memo.split("## Submission deadline")[1].split("##")[0]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", deadline_section)


def test_submit_human_decision_persists_review_and_logs_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    log_path = tmp_path / "feedback_log.json"
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", log_path)

    result = mcp_server.submit_human_decision("cloud-infra-2026", "approved", reviewer="jj", notes="looks good")

    assert result["status"] == "ok"
    assert result["decision"] == "approved"
    assert result["briefing"]["human_review"]["decision"] == "approved"
    assert result["briefing"]["human_review"]["reviewer"] == "jj"

    saved = json.loads((tmp_path / "cloud-infra-2026.json").read_text(encoding="utf-8"))
    assert saved["human_review"]["decision"] == "approved"

    entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["tender_id"] == "cloud-infra-2026"
    assert entries[0]["human_review"]["reviewer"] == "jj"


def test_submit_human_decision_rejects_invalid_decision_string(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", tmp_path / "feedback_log.json")

    result = mcp_server.submit_human_decision("cloud-infra-2026", "sure-why-not")

    assert result["status"] == "error"
    assert "sure-why-not" in result["message"]
    assert list(tmp_path.glob("*.json")) == []


def test_submit_human_decision_unknown_tender_id(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", tmp_path / "feedback_log.json")

    result = mcp_server.submit_human_decision("does-not-exist-2099", "approved")

    assert result["status"] == "error"
    assert list(tmp_path.glob("*.json")) == []


def _live_simap_tender_with_no_local_documents() -> Tender:
    """A SIMAP-sourced tender shaped exactly like a real SIMAP-fixed search
    result (source=SIMAP, research_mode=SIMAP_MCP, publication_id present) —
    it will never have a data/sample_tenders/<id>/ folder, since this MVP's
    only document retrieval adapter reads local fixtures, not real SIMAP
    documents (see src/adapters/document_retrieval.py). Used to exercise the
    documents-blocked path deterministically, without mocking anything."""
    return _simap_tender(tender_id="PRJ-live-no-docs")


def test_extract_requirements_reports_blocked_not_a_bare_error_for_live_simap_tender():
    tender = _live_simap_tender_with_no_local_documents()
    mcp_server._tender_cache[tender.id] = tender

    result = mcp_server.extract_requirements(tender.id)

    assert result["status"] == "ok"  # a legitimate, fully-described outcome, not a tool failure
    assert result["documents_status"] == "NOT_RETRIEVED"
    assert result["confidence"] == "LOW"
    assert result["extracted_requirements"] is None
    # metadata facts (from the search result) vs document facts vs inferences, kept separate.
    assert result["simap_metadata_facts"]["title"] == tender.title
    assert result["simap_metadata_facts"]["source_type"] == "simap_mcp"
    assert result["simap_metadata_facts"]["publication_id"] == tender.publication_id
    assert result["document_facts"] == []
    assert result["inferences"] == []
    assert result["unknowns"]
    assert any("not retrieved" in n.lower() or "not a complete document analysis" in n.lower() for n in result["notes"])


def test_match_hpe_capabilities_reports_blocked_with_no_fabricated_matches():
    tender = _live_simap_tender_with_no_local_documents()
    mcp_server._tender_cache[tender.id] = tender

    result = mcp_server.match_hpe_capabilities(tender.id)

    assert result["status"] == "ok"
    assert result["documents_status"] == "NOT_RETRIEVED"
    assert result["confidence"] == "LOW"
    assert result["matches"] == []  # never a fabricated MATCH/UNKNOWN list without real requirements
    assert result["simap_metadata_facts"]["title"] == tender.title


def test_qualify_tender_reports_blocked_with_no_invented_recommendation():
    tender = _live_simap_tender_with_no_local_documents()
    mcp_server._tender_cache[tender.id] = tender

    result = mcp_server.qualify_tender(tender.id)

    assert result["status"] == "ok"
    assert result["qualification_status"] == "BLOCKED"
    assert result["documents_status"] == "NOT_RETRIEVED"
    assert result["confidence"] == "LOW"
    assert result["briefing"] is None  # no GO/MAYBE/NO-GO invented without documents
    assert result["simap_metadata_facts"]["title"] == tender.title


def test_create_briefing_blocked_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    tender = _live_simap_tender_with_no_local_documents()
    mcp_server._tender_cache[tender.id] = tender

    result = mcp_server.create_briefing(tender.id)

    assert result["status"] == "ok"
    assert result["qualification_status"] == "BLOCKED"
    assert result["briefing"] is None
    assert result["saved_to"] is None
    assert list(tmp_path.glob("*.json")) == []  # no partial/fake briefing ever persisted


def test_submit_human_decision_blocked_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "BRIEFINGS_DIR", tmp_path)
    log_path = tmp_path / "feedback_log.json"
    monkeypatch.setattr(mcp_server, "FEEDBACK_LOG_PATH", log_path)
    tender = _live_simap_tender_with_no_local_documents()
    mcp_server._tender_cache[tender.id] = tender

    result = mcp_server.submit_human_decision(tender.id, "approved", reviewer="jj")

    assert result["status"] == "ok"
    assert result["qualification_status"] == "BLOCKED"
    assert result["decision_recorded"] is False
    assert result["briefing"] is None
    assert result["saved_to"] is None
    assert result["feedback_log"] is None
    assert list(tmp_path.glob("*.json")) == []  # nothing written to data/briefings
    assert not log_path.exists()  # no decision recorded on a qualification that never ran


def test_local_fallback_qualification_is_unaffected_by_the_blocked_path():
    """Regression: the documents-blocked path only triggers on a real
    AdapterUnavailableError — local_fallback tenders with real fixtures
    keep qualifying fully, exactly as before."""
    result = mcp_server.qualify_tender("cloud-infra-2026")
    assert result["status"] == "ok"
    assert "qualification_status" not in result
    assert "documents_status" not in result
    assert result["briefing"]["recommendation"] in {"GO", "MAYBE", "NO-GO"}


def test_server_instructions_and_search_tools_warn_against_replacing_simap_fixed():
    """Rule — SIMAP-fixed stays the sole live-search source: this server's
    own instructions and search_tenders/select_tenders docstrings must tell
    Hermes not to auto-chain them after/instead of a SIMAP-fixed search."""
    instructions = " ".join(mcp_server.mcp.instructions.lower().split())
    assert "simap-fixed" in instructions
    assert "do not call this server's" in instructions or "do not call this tool" in instructions

    for doc in (mcp_server.search_tenders.__doc__, mcp_server.select_tenders.__doc__):
        normalized = " ".join(doc.lower().split())
        assert "simap-fixed" in normalized
        assert "do not call this tool" in normalized


def test_mcp_stdio_protocol_exposes_all_nine_tools_and_answers_calls():
    """Drive the real FastMCP server over an in-memory MCP ClientSession —
    proves the nine tools are discoverable and callable via the MCP protocol
    itself (list_tools / call_tool), not just as plain Python functions —
    and that select_tenders isn't a duplicate of any existing tool name.
    """

    async def run() -> None:
        async with create_connected_server_and_client_session(mcp_server.mcp._mcp_server) as session:
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {
                "search_tenders",
                "select_tenders",
                "get_tender",
                "extract_requirements",
                "match_hpe_capabilities",
                "qualify_tender",
                "create_briefing",
                "submit_human_decision",
                "create_draft",
            }
            assert len(names) == len(tools.tools)  # every name genuinely unique — no duplicated tool

            call = await session.call_tool("get_tender", {"tender_id": "cloud-infra-2026"})
            assert call.isError is False
            payload = json.loads(call.content[0].text)
            assert payload["status"] == "ok"
            assert payload["tender"]["id"] == "cloud-infra-2026"

            missing = await session.call_tool("get_tender", {"tender_id": "does-not-exist-2099"})
            payload = json.loads(missing.content[0].text)
            assert payload["status"] == "error"

    asyncio.run(run())
