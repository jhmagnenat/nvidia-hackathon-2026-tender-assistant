"""Shared fixtures — minimal valid instances of the shared schemas.

Keep these minimal and generic; agent-specific tests build their own fixtures
on top of these where needed.
"""

from datetime import UTC, date, datetime

import pytest

from src.schemas.briefing import QualificationBriefing, ScoreBreakdown
from src.schemas.common import Citation, Confidence, Language, Recommendation
from src.schemas.hpe_profile import Capability, HPEProfile
from src.schemas.tender import (
    Deadline,
    ExtractedTenderData,
    Requirement,
    RequirementCategory,
    Tender,
    TenderSource,
)


@pytest.fixture
def sample_citation() -> Citation:
    return Citation(document="cahier_des_charges.txt", section="4.2")


@pytest.fixture
def sample_tender_meta() -> Tender:
    return Tender(
        id="cloud-infra-2026",
        title="Fourniture de services d'infrastructure cloud hybride",
        buyer="Canton de Vaud",
        location="Lausanne, VD",
        publication_date=date(2026, 8, 15),
        submission_deadline=date(2026, 11, 2),
        url="https://www.simap.ch/example",
        source=TenderSource.LOCAL_SAMPLE,
        scope="Infrastructure cloud hybride et support technique.",
    )


@pytest.fixture
def sample_extracted(sample_tender_meta: Tender, sample_citation: Citation) -> ExtractedTenderData:
    return ExtractedTenderData(
        tender=sample_tender_meta,
        source_documents=["notice.txt", "cahier_des_charges.txt"],
        source_language=Language.FR,
        deadlines=[
            Deadline(label="Submission deadline", date=date(2026, 11, 2), citation=sample_citation)
        ],
        mandatory_requirements=[
            Requirement(
                id="req-1",
                category=RequirementCategory.MANDATORY,
                description="ISO/IEC 27001 certification required.",
                mandatory=True,
                citation=sample_citation,
            )
        ],
        eligibility_criteria=[
            Requirement(
                id="elig-1",
                category=RequirementCategory.ELIGIBILITY,
                description="Registered in the Swiss commercial register.",
                mandatory=True,
                citation=sample_citation,
            )
        ],
        technical_requirements=[
            Requirement(
                id="tech-1",
                category=RequirementCategory.TECHNICAL,
                description="Hyperconverged infrastructure with geo-redundancy.",
                mandatory=False,
                citation=sample_citation,
            )
        ],
        evaluation_criteria=[
            Requirement(
                id="eval-1",
                category=RequirementCategory.EVALUATION,
                description="Price",
                mandatory=False,
                weight_percent=40.0,
                citation=sample_citation,
            )
        ],
        required_certifications=[
            Requirement(
                id="cert-1",
                category=RequirementCategory.CERTIFICATION,
                description="ISO/IEC 27001",
                mandatory=True,
                citation=sample_citation,
            )
        ],
        risks=["Tight implementation timeline."],
        unknowns=[],
        citations=[sample_citation],
    )


@pytest.fixture
def sample_hpe_profile() -> HPEProfile:
    return HPEProfile(
        capabilities=[
            Capability(name="hybrid cloud"),
            Capability(name="managed cloud infrastructure"),
            Capability(name="cybersecurity"),
        ],
        certifications=[],
        references=[],
        languages_supported=[Language.FR, Language.EN],
    )


@pytest.fixture
def sample_briefing(sample_tender_meta: Tender) -> QualificationBriefing:
    breakdown = ScoreBreakdown(
        capability_fit=20,
        mandatory_requirement_fit=20,
        eligibility_fit=10,
        delivery_feasibility=8,
        strategic_relevance=7,
        information_confidence=5,
        explanation="Example.",
    )
    return QualificationBriefing(
        tender=sample_tender_meta,
        recommendation=Recommendation.MAYBE,
        score=70,
        score_breakdown=breakdown,
        confidence=Confidence.MEDIUM,
        executive_summary="Example summary.",
        generated_at=datetime.now(UTC),
    )
