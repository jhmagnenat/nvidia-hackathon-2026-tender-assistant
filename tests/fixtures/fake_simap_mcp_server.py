"""Standalone stdio MCP server used only by tests, standing in for the real
`@digilac/simap-mcp` Node process so `SimapAdapter` tests exercise its real
MCP stdio transport/protocol code (spawn, initialize, call_tool, parse)
without depending on Node, npm, or network access.

Launched by tests as `<python> -m tests.fixtures.fake_simap_mcp_server` (see
`src.adapters.tender_search.SimapAdapter`'s `node_command`/`args`
constructor overrides — production code never sets those).

`_SEARCH_RESULT`/`_CANTONS_RESULT`/`_TENDER_DETAILS_RESULT` are formatted
with the exact same templates `@digilac/simap-mcp@1.4.0`'s
`dist/utils/formatting.js` (`formatProject`, `formatHeader`) and
`dist/tools/codes/list-cantons.js`/`dist/tools/get-tender-details.js`
(`# Tender Details` + `formatProjectHeader`) emit (verified by reading the
real, `npm pack`-downloaded package — see `integrations/simap/README.md`) —
the point is to test callers against the real shape, not a shape invented
for convenience.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-simap-mcp")

_SEARCH_RESULT = (
    "# simap Search Results\n\n**2 result(s)**\n\n"
    "## Fourniture de services d'infrastructure cloud hybride\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0001\n"
    "- **Project Number:** SIMAP-2026-0001\n"
    "- **Publication Number:** PUB-0001\n"
    "- **Publication Date:** 2026-08-15\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
    "- **Office:** Canton de Vaud - Direction des systèmes d'information\n"
    "- **Project ID:** PRJ-0001\n"
    "- **Publication ID:** PUBID-0001\n"
    "- **Location:** Lausanne, VD\n"
    "\n---\n\n"
    "## Services de cybersécurité managés\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0002\n"
    "- **Project Number:** SIMAP-2026-0002\n"
    "- **Publication Number:** PUB-0002\n"
    "- **Publication Date:** 2026-09-01\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
    "- **Office:** État de Genève - Office cantonal des systèmes d'information\n"
    "- **Project ID:** PRJ-0002\n"
    "- **Publication ID:** PUBID-0002\n"
    "\n---\n\n"
)

# A 3-candidate variant of the same search results, adding an
# already-awarded cloud-infrastructure tender (PRJ-0003) — used by
# tender_selection tests that need a non-actionable candidate to exclude.
_AWARDED_BLOCK = (
    "## Infrastructure cloud hybride pour le canton — décision d'adjudication\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0003\n"
    "- **Project Number:** SIMAP-2026-0003\n"
    "- **Publication Number:** PUB-0003\n"
    "- **Publication Date:** 2026-07-01\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
    "- **Office:** Canton de Vaud - Direction des systèmes d'information\n"
    "- **Project ID:** PRJ-0003\n"
    "- **Publication ID:** PUBID-0003\n"
    "\n---\n\n"
)
_SEARCH_RESULT_WITH_AWARDED = (
    _SEARCH_RESULT[: _SEARCH_RESULT.rindex("**2 result(s)**")]
    + "**3 result(s)**\n\n"
    + _SEARCH_RESULT[_SEARCH_RESULT.index("## Fourniture") :]
    + _AWARDED_BLOCK
)

_NO_RESULTS = "No tenders found matching these criteria."

# dist/tools/codes/list-cantons.js's real handler literal template — a
# 2-canton excerpt (not all 26) is enough to prove src/simap_bridge.py's
# /health check reacts to the real "# Swiss Cantons" heading.
_CANTONS_RESULT = (
    "# Swiss Cantons\n\n| Code | Name |\n|------|------|\n| VD | Vaud |\n| GE | Genève |\n"
    "\n*Use these codes with the cantons parameter of search_tenders.*"
)

# dist/tools/get-tender-details.js + formatProjectHeader()/
# formatPublicationDetails()'s real template (re-verified via a fresh
# `npm pack` before this was written, not assumed from memory) — includes
# the "## Publication Details" + "### Deadlines" sections this time, since
# that's the only place a real submission deadline / document-availability
# signal actually appears.
_TENDER_DETAILS_RESULT = (
    "# Tender Details\n\n## General Information\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0001\n"
    "- **Project Number:** SIMAP-2026-0001\n"
    "- **Title:** Fourniture de services d'infrastructure cloud hybride\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
    "\n### Latest Publication\n"
    "- **Date:** 2026-08-15\n"
    "- **Number:** PUB-0001\n"
    "- **Type:** tender\n"
    "\n## Publication Details\n\n"
    "- **Title:** Fourniture de services d'infrastructure cloud hybride\n"
    "- **Publication Number:** PUB-0001\n"
    "- **Project Number:** SIMAP-2026-0001\n"
    "- **Publication Date:** 2026-08-15\n"
    "- **Type:** tender · open\n"
    "- **Has Project Documents:** yes\n"
    "\n### Deadlines\n"
    "- **Submission Deadline:** 2026-11-02\n"
)

# PRJ-0003 — already-awarded publication (pub_type "award_tender" under
# "Latest Publication", the one unambiguous real status field — see
# _parse_tender_details_markdown's docstring). No Deadlines section, matching
# real award notices (dist/utils/formatting.js formatDeadlinesSection returns
# null when details.dates carries nothing displayable — common on awards).
_TENDER_DETAILS_RESULT_AWARDED = (
    "# Tender Details\n\n## General Information\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0003\n"
    "- **Project Number:** SIMAP-2026-0003\n"
    "- **Title:** Infrastructure cloud hybride pour le canton\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
    "\n### Latest Publication\n"
    "- **Date:** 2026-07-01\n"
    "- **Number:** PUB-0003\n"
    "- **Type:** award_tender\n"
    "\n## Publication Details\n\n"
    "- **Title:** Infrastructure cloud hybride pour le canton\n"
    "- **Publication Number:** PUB-0003\n"
    "- **Project Number:** SIMAP-2026-0003\n"
    "- **Publication Date:** 2026-07-01\n"
    "- **Type:** award_tender · open\n"
    "- **Has Project Documents:** yes\n"
)

# Same tender, but with no Publication Details section at all (header 404'd,
# or a publication with no "Deadlines" sub-section at all — e.g. an award
# notice) — used to prove get_tender_details never fabricates a deadline
# when the real response genuinely doesn't carry one.
_TENDER_DETAILS_RESULT_NO_DEADLINE = (
    "# Tender Details\n\n## General Information\n\n"
    "- **simap Link:** https://www.simap.ch/en/project-detail/PRJ-0002\n"
    "- **Project Number:** SIMAP-2026-0002\n"
    "- **Title:** Services de cybersécurité managés\n"
    "- **Type:** service\n"
    "- **Process:** open\n"
)


@mcp.tool()
def search_tenders(search: str = "", lang: str = "en", cantons: list[str] | None = None) -> str:
    if search and "nonexistent" in search:
        return _NO_RESULTS
    # "with-awarded" is a deliberate test-only marker (not a real SIMAP
    # search term) selecting the 3-candidate variant that includes an
    # already-awarded tender (PRJ-0003) — kept opt-in so every existing test
    # asserting exactly [PRJ-0001, PRJ-0002] is unaffected.
    if search and "with-awarded" in search:
        return _SEARCH_RESULT_WITH_AWARDED
    return _SEARCH_RESULT


@mcp.tool()
def list_cantons() -> str:
    return _CANTONS_RESULT


@mcp.tool()
def get_tender_details(projectId: str, publicationId: str, lang: str = "en", fullRaw: bool = False) -> str:
    if projectId == "PRJ-0001":
        return _TENDER_DETAILS_RESULT
    if projectId == "PRJ-0002":
        return _TENDER_DETAILS_RESULT_NO_DEADLINE
    if projectId == "PRJ-0003":
        return _TENDER_DETAILS_RESULT_AWARDED
    return "The requested resource was not found on simap (while retrieving tender details)."


if __name__ == "__main__":
    mcp.run(transport="stdio")
