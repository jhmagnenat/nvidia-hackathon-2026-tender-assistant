"""Document retrieval adapters.

`URLDocumentAdapter` is the seam for fetching real tender documents from their
published URLs. It's not enabled in this MVP: the sample data's URLs are
illustrative (simap.ch search-form links, not direct document links), and rule
6 requires the app to work with zero network calls. `LocalDocumentAdapter` is
the guaranteed fallback used by the demo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.adapters import AdapterUnavailableError
from src.schemas.common import Language
from src.schemas.tender import Tender, TenderDocument

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = REPO_ROOT / "data" / "sample_tenders"


class DocumentRetrievalAdapter:
    name: str = "base"

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def retrieve_documents(self, tender: Tender) -> list[TenderDocument]:
        raise NotImplementedError


class URLDocumentAdapter(DocumentRetrievalAdapter):
    """Seam for fetching documents from a tender's published URL(s). Disabled in this MVP."""

    name = "url"

    @property
    def available(self) -> bool:
        return False

    def retrieve_documents(self, tender: Tender) -> list[TenderDocument]:
        raise AdapterUnavailableError(
            "Live document retrieval over HTTP is disabled in this MVP "
            "(no network dependency, per the local-fallback-first design)."
        )


class LocalDocumentAdapter(DocumentRetrievalAdapter):
    """Guaranteed-available fallback: reads data/sample_tenders/<tender.id>/*.txt."""

    name = "local_sample"

    def __init__(self, base_dir: Path = DEFAULT_SAMPLE_DIR):
        self.base_dir = base_dir

    @property
    def available(self) -> bool:
        return self.base_dir.exists()

    def retrieve_documents(self, tender: Tender) -> list[TenderDocument]:
        folder = self.base_dir / tender.id
        if not folder.is_dir():
            raise AdapterUnavailableError(
                f"No local sample documents found for tender '{tender.id}' under {folder}"
            )

        documents = []
        for path in sorted(folder.glob("*.txt")):
            documents.append(
                TenderDocument(
                    tender_id=tender.id,
                    name=path.name,
                    local_path=str(path.relative_to(REPO_ROOT)),
                    language=Language.FR,
                    content_text=path.read_text(encoding="utf-8"),
                    retrieved_at=datetime.now(UTC),
                )
            )
        return documents


def get_document_adapter() -> DocumentRetrievalAdapter:
    """Return the best available document retrieval adapter (local fallback is guaranteed)."""
    candidates = [URLDocumentAdapter(), LocalDocumentAdapter()]
    for adapter in candidates:
        if adapter.available:
            return adapter
    raise AdapterUnavailableError("No document retrieval adapter is available, including the local fallback.")
