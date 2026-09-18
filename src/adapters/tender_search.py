"""Tender search adapters.

`SimapAdapter` / `TavilyAdapter` are real seams for the MCP-backed services
named in the brief. Per the Phase 0 audit (see IMPLEMENTATION_LOG.md), neither
is reachable from this environment: no MCP client is wired in, no Tavily
package/key is present, and the SIMAP MCP config in `integrations/simap/`
targets a separate external Hermes sandbox this shell cannot reach. Both
adapters therefore report themselves as unavailable rather than pretending to
call a service that isn't there.

`LocalSampleSearchAdapter` is the guaranteed fallback: it reads
`data/sample_tenders.json` and keyword-matches the query against title/scope.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.adapters import AdapterUnavailableError
from src.schemas.tender import Tender

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_INDEX = REPO_ROOT / "data" / "sample_tenders.json"

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ]{3,}")


class TenderSearchAdapter:
    name: str = "base"

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        raise NotImplementedError


class SimapAdapter(TenderSearchAdapter):
    """Seam for the SIMAP MCP server. Not reachable from this environment."""

    name = "simap"

    @property
    def available(self) -> bool:
        # No MCP client is configured in this repo, and the documented SIMAP MCP
        # server (integrations/simap/) runs inside a separate Hermes sandbox that
        # this process cannot reach. Report unavailable rather than fabricate a call.
        return False

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        raise AdapterUnavailableError(
            "SIMAP MCP is not reachable from this environment "
            "(see integrations/simap/README.md and IMPLEMENTATION_LOG.md)."
        )


class TavilyAdapter(TenderSearchAdapter):
    """Seam for Tavily search. Not configured/available in this environment."""

    name = "tavily"

    @property
    def available(self) -> bool:
        return bool(os.environ.get("TAVILY_API_KEY"))

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        if not self.available:
            raise AdapterUnavailableError(
                "Tavily is not configured (no TAVILY_API_KEY) — no tavily-python "
                "package is installed either. Falling back to local sample search."
            )
        raise AdapterUnavailableError("Tavily adapter has no implementation in this MVP.")


class LocalSampleSearchAdapter(TenderSearchAdapter):
    """Guaranteed-available fallback: keyword search over data/sample_tenders.json."""

    name = "local_sample"

    def __init__(self, index_path: Path = DEFAULT_SAMPLE_INDEX):
        self.index_path = index_path

    @property
    def available(self) -> bool:
        return self.index_path.exists()

    def _load(self) -> list[Tender]:
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [Tender.model_validate(entry) for entry in raw]

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        if not self.available:
            raise AdapterUnavailableError(f"Local sample index not found at {self.index_path}")

        tenders = self._load()
        filters = filters or {}

        if location := filters.get("location"):
            tenders = [t for t in tenders if t.location and location.lower() in t.location.lower()]

        query_terms = {w.lower() for w in _WORD_RE.findall(query)}
        if not query_terms:
            return tenders

        scored: list[tuple[int, Tender]] = []
        for tender in tenders:
            haystack = f"{tender.title} {tender.scope or ''}".lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score > 0:
                scored.append((score, tender))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [tender for _, tender in scored]


def get_search_adapter(prefer: list[str] | None = None) -> TenderSearchAdapter:
    """Return the best available search adapter.

    `prefer` sets provider preference order (e.g. ["simap", "tavily"]); the
    local sample adapter is always appended last as the guaranteed fallback.
    """
    candidates: dict[str, TenderSearchAdapter] = {
        "simap": SimapAdapter(),
        "tavily": TavilyAdapter(),
        "local_sample": LocalSampleSearchAdapter(),
    }
    order = (prefer or []) + [name for name in candidates if name not in (prefer or [])]
    for name in order:
        adapter = candidates.get(name)
        if adapter and adapter.available:
            return adapter
    # Unreachable in practice: local_sample.available is True whenever the repo's
    # data/sample_tenders.json exists, which it does.
    raise AdapterUnavailableError("No search adapter is available, including the local fallback.")
