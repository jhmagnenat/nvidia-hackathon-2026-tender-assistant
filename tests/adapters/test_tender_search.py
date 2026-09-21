import sys

import pytest

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import (
    REPO_ROOT,
    LocalSampleSearchAdapter,
    SimapAdapter,
    TavilyAdapter,
    _parse_search_tenders_markdown,
    _parse_tender_details_markdown,
    get_search_adapter,
)
from src.schemas.common import ResearchMode
from src.schemas.tender import TenderSource

_FAKE_SERVER_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]


def _fake_server_adapter(**kwargs) -> SimapAdapter:
    """A SimapAdapter wired to the Python stand-in server (see
    tests/fixtures/fake_simap_mcp_server.py) instead of the real Node
    package — exercises the same MCP stdio transport/protocol code with no
    Node/npm/network dependency."""
    return SimapAdapter(
        node_command=sys.executable,
        args=_FAKE_SERVER_ARGS,
        cwd=str(REPO_ROOT),
        **kwargs,
    )


def test_simap_adapter_unconfigured_is_unavailable_in_this_environment(monkeypatch):
    monkeypatch.delenv("SIMAP_MCP_ENTRYPOINT", raising=False)
    adapter = SimapAdapter()
    assert adapter.available is False
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud")


def test_simap_adapter_missing_entrypoint_file_is_unavailable(tmp_path):
    adapter = SimapAdapter(entrypoint=tmp_path / "does-not-exist" / "dist" / "index.js")
    assert adapter.available is False


def test_simap_adapter_becomes_available_once_entrypoint_and_node_resolve(tmp_path):
    fake_entrypoint = tmp_path / "dist" / "index.js"
    fake_entrypoint.parent.mkdir(parents=True)
    fake_entrypoint.write_text("// placeholder — existence is all `available` checks here", encoding="utf-8")
    adapter = SimapAdapter(entrypoint=fake_entrypoint, node_command=sys.executable)
    assert adapter.available is True


def test_simap_adapter_default_args_shape_matches_hermes_config():
    adapter = SimapAdapter(entrypoint="/some/dist/index.js", node_command="/usr/local/bin/node")
    assert adapter._resolved_args() == ["--use-env-proxy", "/some/dist/index.js"]


def test_simap_adapter_search_calls_the_real_mcp_protocol_and_parses_results():
    adapter = _fake_server_adapter()
    assert adapter.available is True

    results = adapter.search("cloud infrastructure")

    assert [t.id for t in results] == ["PRJ-0001", "PRJ-0002"]
    first = results[0]
    assert first.title == "Fourniture de services d'infrastructure cloud hybride"
    assert first.buyer == "Canton de Vaud - Direction des systèmes d'information"
    assert first.location == "Lausanne, VD"
    assert first.url == "https://www.simap.ch/en/project-detail/PRJ-0001"
    assert first.publication_date.isoformat() == "2026-08-15"
    assert first.source == TenderSource.SIMAP
    assert first.research_mode == ResearchMode.SIMAP_MCP
    assert first.source_type == "simap_mcp"
    # publication_id must be retained (distinct from id/project_id) -- without
    # it, get_tender_details can never be called for this tender.
    assert first.publication_id == "PUBID-0001"
    # Honestly UNKNOWN — search_tenders never carries a deadline, so this must
    # stay None rather than being guessed.
    assert first.submission_deadline is None

    second = results[1]
    assert second.location is None  # fixture's 2nd entry has no Location line — must stay None
    assert second.publication_id == "PUBID-0002"


def test_simap_adapter_search_no_results_returns_empty_list():
    adapter = _fake_server_adapter()
    assert adapter.search("nonexistent query") == []


def test_simap_adapter_search_raises_on_a_real_runtime_failure():
    """Simulates the "Network or timeout error" class of real SIMAP MCP
    failure (see integrations/simap/README.md Troubleshooting) via a fake
    server whose search_tenders tool always errors — confirms SimapAdapter
    surfaces it as AdapterUnavailableError instead of returning [] or
    fabricated results."""
    adapter = SimapAdapter(
        node_command=sys.executable,
        args=["-m", "tests.fixtures.fake_simap_mcp_error_server"],
        cwd=str(REPO_ROOT),
    )
    assert adapter.available is True
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud infrastructure")


def test_parse_search_tenders_markdown_no_results_sentinel():
    assert _parse_search_tenders_markdown("No tenders found matching these criteria.") == []


def test_parse_search_tenders_markdown_ignores_unparseable_blocks():
    # A "## " block with no "Project ID" line must be skipped, not fabricated.
    assert _parse_search_tenders_markdown("# header\n\n## Some Title\n\n- **Office:** X\n") == []


def _fake_server_simap_adapter() -> SimapAdapter:
    return SimapAdapter(node_command=sys.executable, args=_FAKE_SERVER_ARGS, cwd=str(REPO_ROOT))


def test_simap_adapter_get_tender_details_propagates_the_real_deadline():
    """Requirement B.5 — get_tender can retrieve real details from the
    propagated ids: a genuine submission_deadline/has_project_documents/url
    come back when the real response actually carries them."""
    adapter = _fake_server_simap_adapter()

    details = adapter.get_tender_details("PRJ-0001", "PUBID-0001")

    assert details["available"] is True
    assert details["submission_deadline"] == "2026-11-02"
    assert details["publication_date"] == "2026-08-15"
    assert details["has_project_documents"] is True
    assert details["url"] == "https://www.simap.ch/en/project-detail/PRJ-0001"


def test_simap_adapter_get_tender_details_never_fabricates_a_missing_deadline():
    """Requirement B.6/7 — a real response with no Deadlines section at all
    must leave submission_deadline None (UNKNOWN), never a guessed date."""
    adapter = _fake_server_simap_adapter()

    details = adapter.get_tender_details("PRJ-0002", "PUBID-0002")

    assert details["available"] is True  # the tender itself was found...
    assert details["submission_deadline"] is None  # ...but it genuinely has no deadline
    assert details["has_project_documents"] is None


def test_simap_adapter_get_tender_details_not_found_is_unavailable_not_guessed():
    adapter = _fake_server_simap_adapter()

    details = adapter.get_tender_details("PRJ-9999", "PUBID-9999")

    assert details["available"] is False
    assert "not found" in details["reason"].lower()
    assert details["submission_deadline"] is None
    assert details["url"] is None


def test_simap_adapter_get_tender_details_uses_the_exact_ids_passed_in():
    """Requirement B.3 — the ids actually used must correspond to the
    selected tender, not to whatever the adapter happened to see last: a
    wrong/mismatched project_id gets the fake server's honest "not found"
    response, proving the ids are forwarded verbatim, not substituted."""
    adapter = _fake_server_simap_adapter()

    assert adapter.get_tender_details("PRJ-0001", "PUBID-0001")["available"] is True
    assert adapter.get_tender_details("PRJ-0002", "wrong-publication-id")["available"] is True  # fake server only checks projectId
    assert adapter.get_tender_details("wrong-project-id", "PUBID-0001")["available"] is False


def test_parse_tender_details_markdown_not_found_sentinel():
    result = _parse_tender_details_markdown(
        "The requested resource was not found on simap (while retrieving tender details)."
    )
    assert result["available"] is False
    assert result["submission_deadline"] is None


def test_parse_tender_details_markdown_empty_response_is_unavailable():
    assert _parse_tender_details_markdown("") == _parse_tender_details_markdown("   ")
    assert _parse_tender_details_markdown("")["available"] is False


def test_tavily_adapter_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    adapter = TavilyAdapter()
    assert adapter.available is False


def test_local_sample_adapter_is_always_available():
    adapter = LocalSampleSearchAdapter()
    assert adapter.available is True


def test_local_sample_search_matches_relevant_tenders_only():
    adapter = LocalSampleSearchAdapter()
    results = adapter.search("cloud infrastructure managed services cybersecurity")
    ids = [t.id for t in results]
    assert "cloud-infra-2026" in ids
    assert "cybersec-managed-2026" in ids
    assert "office-furniture-2026" not in ids


def test_local_sample_search_location_filter():
    adapter = LocalSampleSearchAdapter()
    results = adapter.search("infrastructure", filters={"location": "Zürich"})
    assert all("Zürich" in (t.location or "") for t in results)


def test_local_sample_results_are_tagged_local_fallback():
    adapter = LocalSampleSearchAdapter()
    results = adapter.search("cloud")
    assert results
    assert all(t.research_mode == ResearchMode.LOCAL_FALLBACK for t in results)


def test_get_search_adapter_falls_back_to_local_sample():
    adapter = get_search_adapter()
    assert adapter.name == "local_sample"


def test_get_search_adapters_priority_order_puts_bridge_first():
    """simap_bridge is the realistic real-SIMAP path when this process runs
    outside the NemoClaw sandbox (see src/adapters/simap_bridge_client.py) —
    it must be tried before the direct-stdio simap adapter."""
    from src.adapters.tender_search import get_search_adapters

    names = [a.name for a in get_search_adapters()]
    assert names == ["simap_bridge", "simap", "tavily", "local_sample"]
