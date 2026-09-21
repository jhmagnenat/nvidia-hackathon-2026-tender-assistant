"""TenderSearchTool — the brief's named search interface, over src/adapters/tender_search.py.

Runtime fallback: an explicit `adapter=` still pins one adapter (used by
tests, and by callers that want a single specific provider). Without one,
`TenderSearchTool` tries every candidate in priority order
(`get_search_adapters()` — simap -> tavily -> local_sample) and falls back to
the next one whenever a call raises `AdapterUnavailableError`, not only when
`.available` was already `False` beforehand — a live SIMAP adapter that is
configured/available but fails *during* a specific call (network blip, proxy
hiccup) must not take the whole workflow down when the guaranteed local
fallback is right there. `self.adapter` always reflects whichever adapter
actually served the most recent `search_tenders()` call (or, before any
call, the first one that reports itself available) — this is what app.py's
"System status" caption and the per-result `source`/`source_type` fields are
built on, so it must never lag behind what actually happened.
"""

from __future__ import annotations

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import TenderSearchAdapter, get_search_adapters
from src.schemas.tender import Tender


class TenderSearchTool:
    def __init__(
        self,
        adapter: TenderSearchAdapter | None = None,
        candidates: list[TenderSearchAdapter] | None = None,
    ):
        """`candidates` overrides the full priority-ordered fallback list
        (test-only — lets tests substitute fake adapters while exercising
        the real fallback logic below); `adapter` pins a single adapter with
        no fallback (existing behavior); neither given -> the real
        `get_search_adapters()` priority order.
        """
        if candidates is not None:
            self._candidates = candidates
        elif adapter is not None:
            self._candidates = [adapter]
        else:
            self._candidates = get_search_adapters()
        self.adapter = next((a for a in self._candidates if a.available), self._candidates[-1])

    def search_tenders(self, query: str, filters: dict | None = None) -> list[Tender]:
        errors: list[str] = []
        for adapter in self._candidates:
            if not adapter.available:
                continue
            try:
                results = adapter.search(query, filters)
            except AdapterUnavailableError as exc:
                errors.append(f"{adapter.name}: {exc}")
                continue
            self.adapter = adapter
            return results

        detail = "; ".join(errors) if errors else "no candidate adapter reported itself available"
        raise AdapterUnavailableError(f"All search adapters failed ({detail}).")
