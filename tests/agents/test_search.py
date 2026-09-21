"""TenderSearchTool — runtime fallback behavior.

These tests use fake stdio MCP servers (tests/fixtures/) so SimapAdapter's
real MCP transport/protocol code runs end-to-end, without depending on
Node/npm/network — see tests/adapters/test_tender_search.py for the same
pattern.
"""

from __future__ import annotations

import sys

from src.adapters.simap_bridge_client import SimapBridgeAdapter
from src.adapters.tender_search import REPO_ROOT, LocalSampleSearchAdapter, SimapAdapter
from src.agents.search import TenderSearchTool
from src.agents.workflow import WorkflowOrchestrator
from src.schemas.common import ResearchMode
from tests.fixtures.run_bridge_server import run_bridge_server

_HAPPY_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]
_ERROR_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_error_server"]


def _fake_simap(args: list[str]) -> SimapAdapter:
    return SimapAdapter(node_command=sys.executable, args=args, cwd=str(REPO_ROOT))


def test_search_tool_uses_simap_when_it_actually_succeeds():
    """Requirement 1 — real SIMAP response: TenderSearchTool must prefer a
    working SimapAdapter over the local fallback, and tag results accordingly."""
    tool = TenderSearchTool(candidates=[_fake_simap(_HAPPY_ARGS), LocalSampleSearchAdapter()])

    results = tool.search_tenders("cloud infrastructure")

    assert results
    assert all(t.research_mode == ResearchMode.SIMAP_MCP for t in results)
    assert all(t.source_type == "simap_mcp" for t in results)
    assert tool.adapter.name == "simap"


def test_search_tool_falls_back_to_local_sample_when_simap_errors_at_runtime():
    """Requirement 2 — SIMAP error with local fallback: a SimapAdapter that
    is `available` but whose `.search()` call fails must not take the whole
    workflow down — TenderSearchTool must catch it and use the guaranteed
    local adapter instead, never fabricate a SIMAP result."""
    tool = TenderSearchTool(candidates=[_fake_simap(_ERROR_ARGS), LocalSampleSearchAdapter()])

    results = tool.search_tenders("cloud infrastructure managed services cybersecurity")

    assert results
    assert all(t.research_mode == ResearchMode.LOCAL_FALLBACK for t in results)
    assert all(t.source_type == "local_fallback" for t in results)
    assert tool.adapter.name == "local_sample"


def test_search_tool_adapter_reflects_the_provider_that_actually_served_the_call():
    """`.adapter` must be updated per call, not frozen at construction time —
    app.py's "System status" caption and the per-tender source display both
    rely on it being current."""
    failing_tool = TenderSearchTool(candidates=[_fake_simap(_ERROR_ARGS), LocalSampleSearchAdapter()])
    failing_tool.search_tenders("cloud")
    assert failing_tool.adapter.name == "local_sample"

    working_tool = TenderSearchTool(candidates=[_fake_simap(_HAPPY_ARGS), LocalSampleSearchAdapter()])
    working_tool.search_tenders("cloud infrastructure")
    assert working_tool.adapter.name == "simap"


def test_search_tool_explicit_adapter_bypasses_fallback_list():
    """An explicitly passed adapter (existing constructor behavior) is used
    as-is, with no other candidates to fall back to."""
    local = LocalSampleSearchAdapter()
    tool = TenderSearchTool(adapter=local)
    assert tool.adapter is local
    results = tool.search_tenders("cloud")
    assert results
    assert tool.adapter is local


def test_workflow_orchestrator_search_uses_the_bridge_when_it_actually_succeeds():
    """Objective 8 — WorkflowOrchestrator.search() connected to the bridge:
    end-to-end through a real local HTTP server (not a mock) backed by the
    fake MCP stdio server. This proves the wiring, not a live NemoClaw
    deployment — see src/simap_bridge.py's module docstring."""
    with run_bridge_server(_HAPPY_ARGS) as url:
        orchestrator = WorkflowOrchestrator(
            search_tool=TenderSearchTool(candidates=[SimapBridgeAdapter(base_url=url), LocalSampleSearchAdapter()])
        )
        results = orchestrator.search("cloud infrastructure")

    assert results
    assert all(t.source_type == "simap_mcp" for t in results)
    assert orchestrator.search_tool.adapter.name == "simap_bridge"


def test_workflow_orchestrator_search_falls_back_to_local_when_bridge_fails():
    with run_bridge_server(_ERROR_ARGS) as url:
        orchestrator = WorkflowOrchestrator(
            search_tool=TenderSearchTool(candidates=[SimapBridgeAdapter(base_url=url), LocalSampleSearchAdapter()])
        )
        results = orchestrator.search("cloud infrastructure managed services cybersecurity")

    assert results
    assert all(t.source_type == "local_fallback" for t in results)
    assert orchestrator.search_tool.adapter.name == "local_sample"
