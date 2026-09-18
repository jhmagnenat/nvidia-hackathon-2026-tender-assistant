"""RequirementExtractionAgent — deterministic section-header parsing, exercised
against the real committed sample-tender fixtures (data/sample_tenders/)."""

import json
from datetime import date
from pathlib import Path

from src.adapters.document_retrieval import LocalDocumentAdapter
from src.agents.ingestion import extract_requirements
from src.schemas.tender import RequirementCategory, Tender

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_tender(tender_id: str) -> Tender:
    raw = json.loads((REPO_ROOT / "data" / "sample_tenders.json").read_text(encoding="utf-8"))
    entry = next(e for e in raw if e["id"] == tender_id)
    return Tender.model_validate(entry)


def test_extract_requirements_cloud_infra_end_to_end():
    tender = _load_tender("cloud-infra-2026")
    docs = LocalDocumentAdapter().retrieve_documents(tender)
    data = extract_requirements(tender, docs)

    assert data.tender.id == "cloud-infra-2026"
    assert data.deadlines and data.deadlines[0].date == date(2026, 11, 2)
    assert any("ISO/IEC 27001" in r.description for r in data.mandatory_requirements)
    assert data.required_certifications and all(
        r.category == RequirementCategory.CERTIFICATION for r in data.required_certifications
    )
    assert data.eligibility_criteria and data.eligibility_criteria[0].mandatory is True
    assert all(r.citation is not None for r in data.all_requirements())


def test_extract_requirements_joins_wrapped_bullet_lines():
    tender = _load_tender("cloud-infra-2026")
    docs = LocalDocumentAdapter().retrieve_documents(tender)
    data = extract_requirements(tender, docs)
    insurance_req = next(r for r in data.mandatory_requirements if "assurance" in r.description.lower())
    assert "CHF 5'000'000" in insurance_req.description


def test_extract_requirements_parses_evaluation_weights():
    tender = _load_tender("cloud-infra-2026")
    docs = LocalDocumentAdapter().retrieve_documents(tender)
    data = extract_requirements(tender, docs)
    price = next(r for r in data.evaluation_criteria if "Prix" in r.description)
    assert price.weight_percent == 40.0


def test_extract_requirements_optional_certification_not_mandatory():
    tender = _load_tender("cloud-infra-2026")
    docs = LocalDocumentAdapter().retrieve_documents(tender)
    data = extract_requirements(tender, docs)
    iso9001 = next(r for r in data.required_certifications if "9001" in r.description)
    assert iso9001.mandatory is False


def test_extract_requirements_no_documents_reports_unknowns(sample_tender_meta):
    empty_tender = sample_tender_meta.model_copy(update={"submission_deadline": None, "scope": None})
    data = extract_requirements(empty_tender, [])
    assert data.mandatory_requirements == []
    assert any("mandatory-requirements" in u for u in data.unknowns)
    assert any("Submission deadline" in u for u in data.unknowns)
