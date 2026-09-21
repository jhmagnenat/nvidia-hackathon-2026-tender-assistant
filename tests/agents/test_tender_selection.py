import sys
import threading
import time
from datetime import date
from unittest import mock

from src.adapters.tender_search import REPO_ROOT, SimapAdapter
from src.agents.retrieval import DocumentRetrievalTool
from src.agents.tender_selection import (
    build_alternatives,
    classify_publication_status,
    override_selection_reason,
    rank_candidates,
    score_tender,
    select_tenders,
)
from src.schemas.common import PublicationStatus, ResearchMode
from src.schemas.hpe_profile import Capability, HPEProfile
from src.schemas.tender import Tender, TenderSource

_FAKE_SERVER_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]


def _fake_simap_adapter() -> SimapAdapter:
    return SimapAdapter(node_command=sys.executable, args=_FAKE_SERVER_ARGS, cwd=str(REPO_ROOT))


def _tender(**overrides) -> Tender:
    defaults = {
        "id": "t-1",
        "title": "Fourniture de services d'infrastructure cloud hybride",
        "buyer": "Canton de Vaud",
        "location": "Lausanne, VD",
        "submission_deadline": None,
        "source": TenderSource.LOCAL_SAMPLE,
        "scope": "Infrastructure cloud hybride et support technique.",
    }
    defaults.update(overrides)
    return Tender(**defaults)


def _profile(**overrides) -> HPEProfile:
    defaults = {
        "capabilities": [
            Capability(name="hybrid cloud", description="Cloud hybride, migration cloud."),
            Capability(name="managed cloud infrastructure", description="Infrastructure cloud gérée, support."),
            Capability(name="cybersecurity", description="Cybersécurité, SOC, sécurité."),
        ],
    }
    defaults.update(overrides)
    return HPEProfile(**defaults)


def test_score_tender_rewards_cloud_and_cyber_keyword_overlap():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()  # real local adapter, real documents

    cloud_tender = _tender(id="cloud-infra-2026", title="Fourniture de services d'infrastructure cloud hybride")
    furniture_tender = _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau", scope="Mobilier de bureau ergonomique.")

    cloud_result = score_tender(cloud_tender, profile, retrieval_tool, date(2026, 9, 18))
    furniture_result = score_tender(furniture_tender, profile, retrieval_tool, date(2026, 9, 18))

    assert cloud_result.breakdown.cloud_infrastructure_fit > furniture_result.breakdown.cloud_infrastructure_fit
    assert cloud_result.total > furniture_result.total


def test_score_tender_empty_theme_capability_subset_is_neutral_not_zero():
    profile = _profile(capabilities=[Capability(name="AI infrastructure", description="Infrastructure IA.")])
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau")

    result = score_tender(tender, profile, retrieval_tool, date(2026, 9, 18))

    # No "cybersecurity"-named capability at all in the profile -> can't judge
    # this dimension -> neutral half points, never a punitive 0.
    assert result.breakdown.cybersecurity_fit == 10.0  # half of _MAX_CYBER (20)
    assert "no matching HPE capability" in " ".join(result.breakdown.notes)


def test_score_tender_deadline_unknown_is_neutral():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="cloud-infra-2026", submission_deadline=None)

    result = score_tender(tender, profile, retrieval_tool, date(2026, 9, 18))

    assert result.breakdown.deadline_fit == 5.0  # half of _MAX_DEADLINE (10)
    assert any("UNKNOWN" in n for n in result.breakdown.notes)


def test_score_tender_deadline_already_passed_scores_zero():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="cloud-infra-2026", submission_deadline=date(2026, 1, 1))

    result = score_tender(tender, profile, retrieval_tool, date(2026, 9, 18))

    assert result.breakdown.deadline_fit == 0.0


def test_score_tender_documents_present_for_local_sample_fixtures():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="cloud-infra-2026")

    result = score_tender(tender, profile, retrieval_tool, date(2026, 9, 18))

    assert result.breakdown.documents_available == 10.0
    assert result.documents  # reused later for extraction -- must be populated


def test_score_tender_documents_missing_for_unknown_id_scores_zero_not_fabricated():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="does-not-exist-anywhere")

    result = score_tender(tender, profile, retrieval_tool, date(2026, 9, 18))

    assert result.breakdown.documents_available == 0.0
    assert result.documents == []


def test_rank_candidates_sorts_best_first():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    cloud_tender = _tender(id="cloud-infra-2026", title="Fourniture de services d'infrastructure cloud hybride")
    furniture_tender = _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau", scope="Mobilier de bureau.")

    ranked = rank_candidates([furniture_tender, cloud_tender], profile, retrieval_tool, as_of=date(2026, 9, 18))

    assert [r.tender.id for r in ranked] == ["cloud-infra-2026", "office-furniture-2026"]
    assert ranked[0].total >= ranked[1].total


def test_build_alternatives_excludes_selected_and_limits_to_three():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tenders = [_tender(id=f"t-{i}", title="Fourniture de services d'infrastructure cloud hybride") for i in range(5)]
    ranked = rank_candidates(tenders, profile, retrieval_tool, as_of=date(2026, 9, 18))

    alternatives = build_alternatives(ranked, exclude_id="t-0")

    assert "t-0" not in {a.tender_id for a in alternatives}
    assert len(alternatives) <= 3
    assert [a.rank for a in alternatives] == list(range(1, len(alternatives) + 1))


def test_override_selection_reason_names_both_candidates():
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tenders = [
        _tender(id="cloud-infra-2026", title="Fourniture de services d'infrastructure cloud hybride"),
        _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau", scope="Mobilier."),
    ]
    ranked = rank_candidates(tenders, profile, retrieval_tool, as_of=date(2026, 9, 18))
    auto_pick = ranked[0]
    override = next(r for r in ranked if r.tender.id != auto_pick.tender.id)

    reason = override_selection_reason(override, auto_pick)

    assert override.tender.id in reason
    assert auto_pick.tender.id in reason
    assert "override" in reason.lower()


# --- classify_publication_status --------------------------------------------


def test_classify_publication_status_already_awarded():
    status, note = classify_publication_status("award_tender", "open", None, date(2026, 9, 18))
    assert status == PublicationStatus.ALREADY_AWARDED
    assert "award_tender" in note


def test_classify_publication_status_direct_award_not_open_is_excluded():
    status, _ = classify_publication_status("direct_award", "direct", None, date(2026, 9, 18))
    assert status == PublicationStatus.DIRECT_AWARD_NOT_OPEN


def test_classify_publication_status_direct_award_open_stays_actionable():
    """Requirement — "direct award si non ouvert": a direct_award whose
    process IS open must NOT be excluded."""
    status, _ = classify_publication_status("direct_award", "open", None, date(2026, 9, 18))
    assert status == PublicationStatus.OPEN


def test_classify_publication_status_revoked_and_cancelled():
    assert classify_publication_status("revocation", None, None, date(2026, 9, 18))[0] == PublicationStatus.REVOKED
    assert classify_publication_status("abandonment", None, None, date(2026, 9, 18))[0] == PublicationStatus.CANCELLED


def test_classify_publication_status_expired_from_a_real_deadline():
    status, note = classify_publication_status(None, None, date(2026, 1, 1), date(2026, 9, 18))
    assert status == PublicationStatus.EXPIRED
    assert "2026-01-01" in note


def test_classify_publication_status_unknown_when_no_pub_type_never_guessed():
    """Rule 6 — never invent a status: missing pub_type stays UNKNOWN, not
    OPEN and not excluded."""
    status, note = classify_publication_status(None, None, None, date(2026, 9, 18))
    assert status == PublicationStatus.UNKNOWN
    assert "no status field available" in note


def test_classify_publication_status_unrecognized_pub_type_stays_unknown_not_guessed():
    status, _ = classify_publication_status("some_future_pub_type_not_in_our_mapping", "open", None, date(2026, 9, 18))
    assert status == PublicationStatus.OPEN  # falls through to the generic "open/ongoing" bucket, never excluded


# --- select_tenders — the explicit SELECT phase -----------------------------


def test_select_tenders_selects_the_most_relevant_candidate():
    """Requirement 1 — selection of a relevant tender: among two local
    candidates, the one actually matching both the query and HPE's
    capabilities must be the one marked selected=True."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    cloud_tender = _tender(id="cloud-infra-2026", title="Fourniture de services d'infrastructure cloud hybride")
    furniture_tender = _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau", scope="Mobilier de bureau.")

    results = select_tenders(
        [furniture_tender, cloud_tender], "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 18)
    )

    selected = [r for r in results if r["selected"]]
    assert len(selected) == 1
    assert selected[0]["tender_id"] == "cloud-infra-2026"
    assert selected[0]["relevance_score"] > 0
    assert selected[0]["reasons"]  # structured justification, not empty
    assert selected[0]["exclusion_reason"] is None

    furniture_entry = next(r for r in results if r["tender_id"] == "office-furniture-2026")
    assert furniture_entry["selected"] is False
    assert furniture_entry["exclusion_reason"] is not None


def test_select_tenders_excludes_an_already_awarded_tender():
    """Requirement 2 — exclusion of an already-awarded tender: among three
    SIMAP-sourced candidates (one already awarded), the awarded one must
    never be selected, regardless of how well it otherwise scores."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    adapter = _fake_simap_adapter()
    candidates = adapter.search("with-awarded cloud infrastructure")
    assert {t.id for t in candidates} == {"PRJ-0001", "PRJ-0002", "PRJ-0003"}

    with mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]):
        results = select_tenders(candidates, "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 20))

    awarded = next(r for r in results if r["tender_id"] == "PRJ-0003")
    assert awarded["status"] == "already_awarded"
    assert awarded["selected"] is False
    assert awarded["exclusion_reason"] is not None
    assert "awarded" in awarded["exclusion_reason"].lower()

    selected = [r for r in results if r["selected"]]
    assert len(selected) == 1
    assert selected[0]["tender_id"] != "PRJ-0003"


def test_select_tenders_status_unknown_when_information_missing_never_excludes_alone():
    """Requirement 3/6 — status UNKNOWN when information is missing: a
    local_fallback candidate (no publication_id, so no SIMAP status check is
    even possible) must report status "unknown" and record it under
    `unknowns`, but must NOT be excluded on that basis alone — it can still
    be `selected` if it's the best candidate."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    tender = _tender(id="cloud-infra-2026")
    assert tender.publication_id is None

    results = select_tenders([tender], "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 18))

    entry = results[0]
    assert entry["status"] == "unknown"
    assert entry["unknowns"]
    assert entry["selected"] is True  # the only candidate, and status alone never disqualifies it
    assert entry["exclusion_reason"] is None


def test_select_tenders_preserves_publication_id_and_project_id():
    """Requirement 4 — publication_id/project_id conservation through SELECT."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    adapter = _fake_simap_adapter()
    candidates = adapter.search("cloud infrastructure")

    with mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]):
        results = select_tenders(candidates, "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 20))

    by_id = {r["tender_id"]: r for r in results}
    assert by_id["PRJ-0001"]["project_id"] == "PRJ-0001"
    assert by_id["PRJ-0001"]["publication_id"] == "PUBID-0001"
    assert by_id["PRJ-0002"]["publication_id"] == "PUBID-0002"


def test_select_tenders_preserves_source_type_for_both_simap_and_local():
    """Requirement 5 — source_type provenance conservation."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    local_tender = _tender(id="cloud-infra-2026")
    simap_tender = Tender(
        id="PRJ-0001",
        title="Fourniture de services d'infrastructure cloud hybride",
        source=TenderSource.SIMAP,
        research_mode=ResearchMode.SIMAP_MCP,
        publication_id="PUBID-0001",
    )

    results = select_tenders(
        [local_tender, simap_tender], "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 18)
    )

    by_id = {r["tender_id"]: r for r in results}
    assert by_id["cloud-infra-2026"]["source_type"] == "local_fallback"
    assert by_id["PRJ-0001"]["source_type"] == "simap_mcp"


def test_select_tenders_calls_get_tender_details_at_most_once_per_simap_candidate():
    """Requirement 6 — no unnecessary SIMAP calls: exactly one
    get_tender_details call per SIMAP-sourced candidate that actually has a
    publication_id, never more (and zero for local_fallback candidates,
    which never even attempt one). Status resolution now runs concurrently
    (see _resolve_statuses_concurrently) — the lock only guards this test's
    own counter against a genuine race between threads, it doesn't change
    what's being asserted."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    adapter = _fake_simap_adapter()
    candidates = adapter.search("with-awarded cloud infrastructure")  # 3 SIMAP candidates
    local_tender = _tender(id="office-furniture-2026", title="Fourniture de mobilier de bureau", scope="Mobilier.")

    call_count = 0
    count_lock = threading.Lock()
    real_get_details = adapter.get_tender_details

    def counting_get_tender_details(*args, **kwargs):
        nonlocal call_count
        with count_lock:
            call_count += 1
        return real_get_details(*args, **kwargs)

    with (
        mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]),
        mock.patch.object(adapter, "get_tender_details", counting_get_tender_details),
    ):
        select_tenders([*candidates, local_tender], "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 20))

    assert call_count == 3  # exactly one per SIMAP candidate, none for the local_fallback one


def test_select_tenders_resolves_simap_statuses_concurrently_not_sequentially():
    """Requirement — the fix for select_tenders being slow on a broad query:
    resolving N SIMAP candidates' publication status must take roughly one
    round-trip's worth of wall time, not N round-trips added together."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    per_call_delay = 0.2
    num_candidates = 6

    class _SlowOpenAdapter:
        name = "fake_slow"
        available = True

        def get_tender_details(self, project_id, publication_id, lang="en"):
            time.sleep(per_call_delay)
            return {
                "available": True,
                "reason": None,
                "title": "Slow tender",
                "url": None,
                "publication_date": None,
                "submission_deadline": None,
                "has_project_documents": True,
                "pub_type": "tender",
                "process_type": "open",
            }

    candidates = [
        Tender(
            id=f"PRJ-SLOW-{i}",
            title="Fourniture de services d'infrastructure cloud hybride",
            source=TenderSource.SIMAP,
            research_mode=ResearchMode.SIMAP_MCP,
            publication_id=f"PUBID-SLOW-{i}",
        )
        for i in range(num_candidates)
    ]

    with mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[_SlowOpenAdapter()]):
        start = time.monotonic()
        results = select_tenders(candidates, "cloud infrastructure", profile, retrieval_tool, as_of=date(2026, 9, 20))
        elapsed = time.monotonic() - start

    # Sequential would take >= num_candidates * per_call_delay (1.2s here).
    # Concurrent (bounded by _MAX_PARALLEL_STATUS_CHECKS >= num_candidates)
    # should land close to one call's delay plus overhead.
    assert elapsed < per_call_delay * num_candidates * 0.6
    assert all(r["status"] == "open" for r in results)
    assert len([r for r in results if r["selected"]]) == 1


# --- query-relevance gate -----------------------------------------------------
# Regression coverage for the live-Hermes finding: select_tenders must never
# pick an actionable candidate that has zero meaningful keyword overlap with
# the requested query, just because everything else scored worse (e.g. a
# wastewater-treatment-plant construction tender for a "cloud infrastructure,
# managed services and cybersecurity" query).

_QUERY = "cloud infrastructure, managed services and cybersecurity"


def _wastewater_tender(**overrides) -> Tender:
    defaults = {
        "id": "wastewater-2026",
        "title": "Construction d'une station d'épuration des eaux usées",
        "scope": "Travaux de génie civil pour le traitement des eaux usées et la construction du bassin.",
    }
    defaults.update(overrides)
    return _tender(**defaults)


def test_select_tenders_query_relevance_gate_excludes_unrelated_candidate():
    """An unrelated tender (0% query keyword match) must never be selected,
    even though it's the only candidate left once a relevant one is absent —
    the reported bug: SELECT picked a wastewater-treatment tender for a
    cloud/managed-services/cybersecurity query purely because it was the
    least-bad actionable score."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    wastewater = _wastewater_tender()

    results = select_tenders([wastewater], _QUERY, profile, retrieval_tool, as_of=date(2026, 9, 18))

    entry = results[0]
    assert entry["selected"] is False
    assert entry["exclusion_reason"] == "No meaningful keyword match with the requested query."
    assert any("no meaningful keyword match" in u.lower() for u in entry["unknowns"])


def test_select_tenders_query_relevance_gate_returns_no_selection_when_every_candidate_is_irrelevant():
    """Rule 4/5 — when every candidate has zero query relevance, no
    tender_id is selected at all: selected=False for every candidate, each
    carries the gate exclusion_reason, and there's a clear unknown/note
    explaining why nothing was picked. Candidates stay in the response for
    human inspection — they just aren't auto-selected."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    wastewater = _wastewater_tender()
    furniture = _tender(
        id="office-furniture-2026",
        title="Fourniture de mobilier de bureau",
        scope="Mobilier de bureau ergonomique pour les écoles.",
    )

    results = select_tenders([wastewater, furniture], _QUERY, profile, retrieval_tool, as_of=date(2026, 9, 18))

    assert len(results) == 2
    assert all(r["selected"] is False for r in results)
    assert all(r["exclusion_reason"] == "No meaningful keyword match with the requested query." for r in results)
    assert all(any("no meaningful keyword match" in u.lower() for u in r["unknowns"]) for r in results)
    # Never invent a GO/NO-GO pick — this is exactly how mcp_server.select_tenders
    # derives selected_tender_id from these entries.
    assert next((r["tender_id"] for r in results if r["selected"]), None) is None


def test_select_tenders_query_relevance_gate_still_selects_the_relevant_cloud_tender():
    """Requirement — a genuinely relevant candidate must still win selection
    when it's mixed in with an unrelated one; the gate excludes the
    irrelevant candidate, not the whole query."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    cloud_tender = _tender(id="cloud-infra-2026", title="Fourniture de services d'infrastructure cloud hybride")
    wastewater = _wastewater_tender()

    results = select_tenders([wastewater, cloud_tender], _QUERY, profile, retrieval_tool, as_of=date(2026, 9, 18))

    selected = [r for r in results if r["selected"]]
    assert len(selected) == 1
    assert selected[0]["tender_id"] == "cloud-infra-2026"
    assert selected[0]["exclusion_reason"] is None

    wastewater_entry = next(r for r in results if r["tender_id"] == "wastewater-2026")
    assert wastewater_entry["selected"] is False
    assert wastewater_entry["exclusion_reason"] == "No meaningful keyword match with the requested query."


def test_select_tenders_query_relevance_gate_does_not_override_already_awarded_exclusion():
    """Rule 7 — status-based exclusion (already-awarded, etc.) stays the
    reported reason even for a candidate that would also fail the query
    relevance gate; status exclusion is checked first and is unchanged."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    awarded_wastewater = _wastewater_tender(id="wastewater-awarded-2026")

    with mock.patch("src.agents.tender_selection._resolve_status", return_value=(PublicationStatus.ALREADY_AWARDED, "Already awarded.")):
        results = select_tenders([awarded_wastewater], _QUERY, profile, retrieval_tool, as_of=date(2026, 9, 18))

    entry = results[0]
    assert entry["selected"] is False
    assert entry["status"] == "already_awarded"
    assert "awarded" in entry["exclusion_reason"].lower()


def test_select_tenders_query_relevance_gate_preserves_identity_fields():
    """Rule 2 — source_type/publication_id/project_id/status stay intact on
    a gated-out candidate, same as any other excluded candidate."""
    profile = _profile()
    retrieval_tool = DocumentRetrievalTool()
    adapter = _fake_simap_adapter()
    wastewater = Tender(
        id="PRJ-0001",
        title="Construction d'une station d'épuration des eaux usées",
        scope="Travaux de génie civil pour le traitement des eaux usées.",
        source=TenderSource.SIMAP,
        research_mode=ResearchMode.SIMAP_MCP,
        publication_id="PUBID-0001",
    )

    with mock.patch("src.agents.tender_selection.get_search_adapters", return_value=[adapter]):
        results = select_tenders([wastewater], _QUERY, profile, retrieval_tool, as_of=date(2026, 9, 20))

    entry = results[0]
    assert entry["tender_id"] == "PRJ-0001"
    assert entry["project_id"] == "PRJ-0001"
    assert entry["publication_id"] == "PUBID-0001"
    assert entry["source_type"] == "simap_mcp"
    assert entry["selected"] is False
    assert entry["exclusion_reason"] == "No meaningful keyword match with the requested query."
