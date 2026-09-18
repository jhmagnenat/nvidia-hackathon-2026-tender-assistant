"""TenderSearchTool — the brief's named search interface, over src/adapters/tender_search.py."""

from __future__ import annotations

from src.adapters.tender_search import TenderSearchAdapter, get_search_adapter
from src.schemas.tender import Tender


class TenderSearchTool:
    def __init__(self, adapter: TenderSearchAdapter | None = None):
        self.adapter = adapter or get_search_adapter()

    def search_tenders(self, query: str, filters: dict | None = None) -> list[Tender]:
        return self.adapter.search(query, filters)
