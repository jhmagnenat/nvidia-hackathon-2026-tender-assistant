"""matching.py — deterministic MatchStatus rules.

Key invariant from the brief: certifications/references must be UNKNOWN, never
NO_MATCH, when the profile simply doesn't list one — profile incompleteness is
not a confirmed gap.
"""

from src.agents.matching import match_requirement
from src.schemas.common import MatchStatus
from src.schemas.hpe_profile import Capability, Certification, HPEProfile
from src.schemas.tender import Requirement, RequirementCategory


def _req(description, category=RequirementCategory.TECHNICAL, mandatory=False):
    return Requirement(id="r-1", category=category, description=description, mandatory=mandatory)


def test_capability_match_when_keywords_overlap():
    profile = HPEProfile(capabilities=[Capability(name="cybersecurity", description="cybersécurité, SOC")])
    match = match_requirement(_req("Le prestataire doit assurer la cybersécurité du réseau."), profile)
    assert match.status == MatchStatus.MATCH
    assert match.hpe_capability == "cybersecurity"


def test_capability_no_match_when_profile_has_data_but_no_overlap():
    profile = HPEProfile(capabilities=[Capability(name="cybersecurity")])
    match = match_requirement(_req("Fourniture de mobilier de bureau ergonomique durable."), profile)
    assert match.status == MatchStatus.NO_MATCH


def test_capability_unknown_when_profile_has_no_capabilities():
    profile = HPEProfile(capabilities=[])
    match = match_requirement(_req("Support technique disponible en continu."), profile)
    assert match.status == MatchStatus.UNKNOWN


def test_certification_unknown_when_not_listed_never_no_match():
    profile = HPEProfile(certifications=[])
    match = match_requirement(
        _req("Certification ISO/IEC 27001 requise.", category=RequirementCategory.CERTIFICATION, mandatory=True),
        profile,
    )
    assert match.status == MatchStatus.UNKNOWN


def test_certification_match_when_listed_with_citation(sample_citation):
    profile = HPEProfile(certifications=[Certification(name="ISO/IEC 27001", citation=sample_citation)])
    match = match_requirement(
        _req("Certification ISO/IEC 27001 requise.", category=RequirementCategory.CERTIFICATION, mandatory=True),
        profile,
    )
    assert match.status == MatchStatus.MATCH
    assert match.hpe_capability == "ISO/IEC 27001"


def test_reference_unknown_when_not_listed_never_no_match():
    profile = HPEProfile(references=[])
    match = match_requirement(
        _req("Au moins 1 référence de modernisation en Suisse.", category=RequirementCategory.REFERENCE, mandatory=True),
        profile,
    )
    assert match.status == MatchStatus.UNKNOWN


def test_insurance_no_match_when_below_required_amount():
    profile = HPEProfile(insurance_coverage_chf=1_000_000)
    match = match_requirement(_req("Assurance responsabilité civile d'au moins CHF 5'000'000."), profile)
    assert match.status == MatchStatus.NO_MATCH


def test_insurance_match_when_above_required_amount():
    profile = HPEProfile(insurance_coverage_chf=10_000_000)
    match = match_requirement(_req("Assurance responsabilité civile d'au moins CHF 5'000'000."), profile)
    assert match.status == MatchStatus.MATCH


def test_insurance_unknown_when_profile_has_no_figure():
    profile = HPEProfile(insurance_coverage_chf=None)
    match = match_requirement(_req("Assurance responsabilité civile d'au moins CHF 5'000'000."), profile)
    assert match.status == MatchStatus.UNKNOWN


def test_legal_registration_always_unknown():
    profile = HPEProfile(capabilities=[Capability(name="public-sector technology services")])
    match = match_requirement(_req("Inscription au registre du commerce suisse requise."), profile)
    assert match.status == MatchStatus.UNKNOWN
