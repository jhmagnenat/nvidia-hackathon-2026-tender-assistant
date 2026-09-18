import pytest

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import (
    LocalSampleSearchAdapter,
    SimapAdapter,
    TavilyAdapter,
    get_search_adapter,
)


def test_simap_adapter_reports_unavailable_in_this_environment():
    adapter = SimapAdapter()
    assert adapter.available is False
    with pytest.raises(AdapterUnavailableError):
        adapter.search("cloud")


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


def test_get_search_adapter_falls_back_to_local_sample():
    adapter = get_search_adapter()
    assert adapter.name == "local_sample"
