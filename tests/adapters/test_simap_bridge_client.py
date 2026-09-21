"""SimapBridgeAdapter — the HTTP client side.

Runs src/simap_bridge.py as a *real* local HTTP server (uvicorn, in a
background thread, bound to 127.0.0.1 on an OS-assigned port) backed by the
fake MCP stdio server (tests/fixtures/fake_simap_mcp_server.py) — so
SimapBridgeAdapter does genuine HTTP requests over a real socket, not an
in-process TestClient shortcut. This still does not touch NemoClaw: it
proves the client/bridge HTTP contract is correct, not that a real NemoClaw
deployment is reachable (see src/simap_bridge.py's module docstring). No
test here claims to have called the real simap-fixed server in NemoClaw.
"""

from __future__ import annotations

import pytest

from src.adapters import AdapterUnavailableError
from src.adapters.simap_bridge_client import SimapBridgeAdapter
from src.schemas.common import ResearchMode
from src.schemas.tender import TenderSource
from tests.fixtures.run_bridge_server import run_bridge_server

_HAPPY_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]
_ERROR_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_error_server"]


@pytest.fixture
def happy_bridge_url():
    with run_bridge_server(_HAPPY_ARGS) as url:
        yield url


@pytest.fixture
def error_bridge_url():
    with run_bridge_server(_ERROR_ARGS) as url:
        yield url


def test_bridge_adapter_unconfigured_by_default(monkeypatch):
    monkeypatch.delenv("SIMAP_BRIDGE_URL", raising=False)
    adapter = SimapBridgeAdapter()
    assert adapter.available is False
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud")


def test_bridge_adapter_available_against_a_real_running_bridge(happy_bridge_url):
    adapter = SimapBridgeAdapter(base_url=happy_bridge_url)
    assert adapter.available is True


def test_bridge_adapter_unavailable_when_bridge_reports_mcp_failure(error_bridge_url):
    # The bridge process itself is up and answering HTTP; its own /health
    # call to the (fake, always-erroring) MCP server is what must fail here.
    adapter = SimapBridgeAdapter(base_url=error_bridge_url)
    assert adapter.available is False


def test_bridge_adapter_search_gets_a_real_response_over_real_http(happy_bridge_url):
    """Requirement — a real SIMAP response reaching this Streamlit-side
    client over an actual HTTP socket (not a mock, not local sample data)."""
    adapter = SimapBridgeAdapter(base_url=happy_bridge_url)

    results = adapter.search("cloud infrastructure")

    assert [t.id for t in results] == ["PRJ-0001", "PRJ-0002"]
    assert results[0].source == TenderSource.SIMAP
    assert results[0].research_mode == ResearchMode.SIMAP_MCP
    assert results[0].source_type == "simap_mcp"


def test_bridge_adapter_search_raises_when_bridge_relays_a_real_mcp_error(error_bridge_url):
    """Requirement — SIMAP error surfaced through the bridge must raise, not
    return an empty/fabricated result; falling back to local data is
    TenderSearchTool's job, one layer up."""
    adapter = SimapBridgeAdapter(base_url=error_bridge_url)
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud infrastructure")


def test_bridge_adapter_unreachable_url_raises_not_silently_empty():
    adapter = SimapBridgeAdapter(base_url="http://127.0.0.1:1", timeout=2.0)
    assert adapter.available is False
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud")


def test_bridge_adapter_get_tender_details_over_real_http(happy_bridge_url):
    """Requirement B.5 — get_tender_details reachable through the bridge
    over a real HTTP socket, using the propagated project_id/publication_id,
    with a genuine (fake-backed) submission deadline coming back."""
    adapter = SimapBridgeAdapter(base_url=happy_bridge_url)

    details = adapter.get_tender_details("PRJ-0001", "PUBID-0001")

    assert details["available"] is True
    assert details["submission_deadline"] == "2026-11-02"
    assert details["has_project_documents"] is True


def test_bridge_adapter_get_tender_details_not_found_over_real_http(happy_bridge_url):
    adapter = SimapBridgeAdapter(base_url=happy_bridge_url)

    details = adapter.get_tender_details("does-not-exist", "does-not-exist")

    assert details["available"] is False
    assert details["submission_deadline"] is None


def test_bridge_adapter_get_tender_details_raises_when_bridge_relays_a_real_mcp_error(error_bridge_url):
    adapter = SimapBridgeAdapter(base_url=error_bridge_url)
    with pytest.raises(AdapterUnavailableError):
        adapter.get_tender_details("PRJ-0001", "PUBID-0001")


def test_bridge_adapter_get_tender_details_unconfigured_by_default(monkeypatch):
    monkeypatch.delenv("SIMAP_BRIDGE_URL", raising=False)
    adapter = SimapBridgeAdapter()
    with pytest.raises(AdapterUnavailableError):
        adapter.get_tender_details("PRJ-0001", "PUBID-0001")
