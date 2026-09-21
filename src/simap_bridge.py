"""SIMAP MCP HTTP bridge — lets a process in a *different* environment than
the SIMAP MCP stdio server (Streamlit, running outside the NemoClaw sandbox)
reach it over plain HTTP.

Why this exists: MCP stdio is a 1:1, same-machine-process-tree transport —
it cannot cross the boundary between this Streamlit environment and the
NemoClaw/OpenShell sandbox where `@digilac/simap-mcp` actually runs (Node,
the proxy, the CA bundle, network access to www.simap.ch). No HTTP/MCP
endpoint for calling a specific tool is documented anywhere in this repo for
Hermes/OpenShell/NemoClaw (see IMPLEMENTATION_LOG.md's SIMAP/NemoHermes
procedure analysis) — only the Hermes *dashboard* ingress
(`deploy/hermes-ingress/`), which is a chat UI, not a tool-call API. So this
bridge is deliberately minimal: it MUST run *inside* the NemoClaw sandbox
(same place `simap-fixed` already runs) and does nothing but relay three
real MCP tool calls over HTTP — it never substitutes local/sample data for a
failed SIMAP call (that stays LocalSampleSearchAdapter's job, one layer up,
in `src/adapters/tender_search.py`).

Reuses `src.adapters.tender_search.SimapAdapter` unchanged for the actual
MCP transport (spawn, handshake, tool call, error mapping) — this file adds
only the HTTP surface, no new SIMAP client logic.

Endpoints (exactly these three, per this task's scope — nothing else):
    GET  /health          -> real liveness check (calls list_cantons)
    POST /search_tenders  -> relays the search_tenders tool
    POST /get_tender      -> relays the get_tender_details tool

Run it:
    python -m src.simap_bridge

Configuration (env vars — same SIMAP_MCP_* vars SimapAdapter already reads,
plus two new ones for the HTTP layer itself):
    SIMAP_MCP_ENTRYPOINT   path to @digilac/simap-mcp's dist/index.js (required)
    SIMAP_MCP_NODE_COMMAND node binary (default: "node")
    SIMAP_BRIDGE_HOST      bind host (default: "127.0.0.1")
    SIMAP_BRIDGE_PORT      bind port (default: 8135 — not a real/existing
                            port, just this module's default; not reachable
                            from outside the sandbox unless the operator
                            binds/exposes it deliberately)

See deploy/simap-bridge/README.md for the deployment procedure inside the
NemoClaw sandbox — not runnable from this repo's own environment.
"""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import SimapAdapter

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8135


def _adapter() -> SimapAdapter:
    # A fresh SimapAdapter per request/health-check, exactly like every other
    # SimapAdapter caller — stdio is 1:1, there is no persistent connection
    # to reuse across requests (see module docstring).
    return SimapAdapter()


async def health(request: Request) -> JSONResponse:
    """Real liveness check — actually calls list_cantons through the live
    MCP subprocess, not just "is this HTTP port open". Never fabricates a
    canton count."""
    adapter = _adapter()
    if not adapter.available:
        return JSONResponse(
            {
                "status": "unavailable",
                "detail": f"SimapAdapter not configured/reachable (entrypoint={adapter.entrypoint!r}, "
                f"node_command={adapter.node_command!r}). Set SIMAP_MCP_ENTRYPOINT.",
            },
            status_code=503,
        )
    try:
        text = await adapter.call_tool("list_cantons", {})
    except AdapterUnavailableError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
    # dist/tools/codes/list-cantons.js's real handler starts its response
    # with this exact literal heading — a cheap, non-fabricated liveness
    # signal (distinct from just "the HTTP port answered").
    looks_real = text.startswith("# Swiss Cantons")
    return JSONResponse({"status": "ok" if looks_real else "unexpected_response", "response_preview": text[:200]})


async def search_tenders(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"status": "error", "detail": "invalid JSON body"}, status_code=400)

    query = body.get("query", "")
    filters = body.get("filters") or {}
    if not isinstance(query, str):
        return JSONResponse({"status": "error", "detail": "'query' must be a string"}, status_code=400)

    adapter = _adapter()
    try:
        markdown = await adapter.asearch_raw(query, filters)
    except AdapterUnavailableError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
    return JSONResponse({"status": "ok", "markdown": markdown})


async def get_tender(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"status": "error", "detail": "invalid JSON body"}, status_code=400)

    project_id = body.get("project_id")
    publication_id = body.get("publication_id")
    lang = body.get("lang", "en")
    if not project_id or not publication_id:
        # get_tender_details genuinely requires both real UUIDs — see
        # dist/tools/get-tender-details.js's Zod schema. Never guessed/derived.
        return JSONResponse(
            {"status": "error", "detail": "'project_id' and 'publication_id' are both required"},
            status_code=400,
        )

    adapter = _adapter()
    try:
        markdown = await adapter.call_tool(
            "get_tender_details",
            {"projectId": project_id, "publicationId": publication_id, "lang": lang},
        )
    except AdapterUnavailableError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
    return JSONResponse({"status": "ok", "markdown": markdown})


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/search_tenders", search_tenders, methods=["POST"]),
        Route("/get_tender", get_tender, methods=["POST"]),
    ]
)


def main() -> None:
    import uvicorn

    host = os.environ.get("SIMAP_BRIDGE_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("SIMAP_BRIDGE_PORT", _DEFAULT_PORT))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
