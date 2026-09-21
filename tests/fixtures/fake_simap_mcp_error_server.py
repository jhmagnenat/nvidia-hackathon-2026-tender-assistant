"""Standalone stdio MCP server used only by tests to simulate a genuine
runtime SIMAP MCP failure (e.g. the real "Network or timeout error while
retrieving cantons" class of failure documented in
integrations/simap/README.md "Troubleshooting") — as opposed to
`fake_simap_mcp_server.py`, which simulates the happy path.

Its `search_tenders` tool always raises, so FastMCP turns the call into a
real MCP `isError: true` result — no fabricated SIMAP data is ever returned,
this only proves `SimapAdapter`/`TenderSearchTool` react correctly to a
real failure signal.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-simap-mcp-error")


@mcp.tool()
def search_tenders(search: str = "", lang: str = "en", cantons: list[str] | None = None) -> str:
    raise RuntimeError("simulated SIMAP MCP failure (e.g. network/proxy error)")


if __name__ == "__main__":
    mcp.run(transport="stdio")
