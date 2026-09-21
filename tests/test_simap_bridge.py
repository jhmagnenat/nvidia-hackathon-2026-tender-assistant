"""src/simap_bridge.py — the HTTP bridge server.

These tests run the real Starlette app (via starlette.testclient.TestClient,
which drives it with a real HTTP request/response cycle) against the
*fake* MCP stdio server (tests/fixtures/fake_simap_mcp_server.py), not a
live NemoClaw deployment — this repo's environment has no network path to
the real NemoClaw sandbox (see IMPLEMENTATION_LOG.md). What these tests do
prove: the bridge's routing, request/response shapes, and error handling
are correct against the real MCP stdio protocol end-to-end. They do NOT
prove the bridge is reachable from inside NemoClaw — that can only be
verified by actually deploying it there (see deploy/simap-bridge/README.md).
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest
from starlette.testclient import TestClient

import src.simap_bridge as bridge
from src.adapters.tender_search import REPO_ROOT, SimapAdapter

_HAPPY_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_server"]
_ERROR_ARGS = ["-m", "tests.fixtures.fake_simap_mcp_error_server"]


def _fake_backed_adapter(args: list[str]) -> SimapAdapter:
    return SimapAdapter(node_command=sys.executable, args=args, cwd=str(REPO_ROOT))


@pytest.fixture
def happy_client():
    with mock.patch.object(bridge, "_adapter", lambda: _fake_backed_adapter(_HAPPY_ARGS)):
        yield TestClient(bridge.app)


@pytest.fixture
def error_client():
    with mock.patch.object(bridge, "_adapter", lambda: _fake_backed_adapter(_ERROR_ARGS)):
        yield TestClient(bridge.app)


@pytest.fixture
def unconfigured_client():
    with mock.patch.object(bridge, "_adapter", SimapAdapter):
        yield TestClient(bridge.app)


def test_health_reports_ok_against_a_real_working_mcp_server(happy_client):
    resp = happy_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "Swiss Cantons" in body["response_preview"]


def test_health_reports_unavailable_when_simap_mcp_entrypoint_is_unset(unconfigured_client):
    resp = unconfigured_client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"


def test_health_reports_error_on_a_real_runtime_mcp_failure(error_client):
    resp = error_client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


def test_search_tenders_relays_the_real_mcp_tool_and_returns_markdown(happy_client):
    resp = happy_client.post("/search_tenders", json={"query": "cloud infrastructure"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "Fourniture de services d'infrastructure cloud hybride" in body["markdown"]


def test_search_tenders_surfaces_a_real_mcp_failure_as_503(error_client):
    resp = error_client.post("/search_tenders", json={"query": "cloud infrastructure"})
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


def test_search_tenders_rejects_non_string_query(happy_client):
    resp = happy_client.post("/search_tenders", json={"query": 123})
    assert resp.status_code == 400


def test_get_tender_relays_the_real_get_tender_details_tool(happy_client):
    resp = happy_client.post("/get_tender", json={"project_id": "PRJ-0001", "publication_id": "PUBID-0001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "Tender Details" in body["markdown"]


def test_get_tender_requires_both_real_ids_never_guesses(happy_client):
    resp = happy_client.post("/get_tender", json={"project_id": "PRJ-0001"})
    assert resp.status_code == 400
    assert "publication_id" in resp.json()["detail"]


def test_get_tender_unavailable_when_unconfigured(unconfigured_client):
    resp = unconfigured_client.post("/get_tender", json={"project_id": "x", "publication_id": "y"})
    assert resp.status_code == 503
