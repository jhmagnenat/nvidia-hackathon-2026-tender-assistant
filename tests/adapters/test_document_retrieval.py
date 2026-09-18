import pytest

from src.adapters import AdapterUnavailableError
from src.adapters.document_retrieval import (
    LocalDocumentAdapter,
    URLDocumentAdapter,
    get_document_adapter,
)


def test_url_adapter_unavailable():
    adapter = URLDocumentAdapter()
    assert adapter.available is False
    with pytest.raises(AdapterUnavailableError):
        adapter.retrieve_documents(None)


def test_local_document_adapter_retrieves_sample_docs(sample_tender_meta):
    adapter = LocalDocumentAdapter()
    docs = adapter.retrieve_documents(sample_tender_meta)
    names = {d.name for d in docs}
    assert "notice.txt" in names
    assert "cahier_des_charges.txt" in names
    assert all(d.content_text for d in docs)


def test_local_document_adapter_missing_tender_raises(sample_tender_meta):
    adapter = LocalDocumentAdapter()
    missing = sample_tender_meta.model_copy(update={"id": "does-not-exist"})
    with pytest.raises(AdapterUnavailableError):
        adapter.retrieve_documents(missing)


def test_get_document_adapter_returns_local():
    adapter = get_document_adapter()
    assert adapter.name == "local_sample"
