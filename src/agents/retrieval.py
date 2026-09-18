"""DocumentRetrievalTool — the brief's named retrieval interface, over src/adapters/document_retrieval.py."""

from __future__ import annotations

from src.adapters.document_retrieval import DocumentRetrievalAdapter, get_document_adapter
from src.schemas.tender import Tender, TenderDocument


class DocumentRetrievalTool:
    def __init__(self, adapter: DocumentRetrievalAdapter | None = None):
        self.adapter = adapter or get_document_adapter()

    def retrieve_documents(self, tender: Tender) -> list[TenderDocument]:
        return self.adapter.retrieve_documents(tender)
