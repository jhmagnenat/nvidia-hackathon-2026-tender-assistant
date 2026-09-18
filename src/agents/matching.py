"""Deterministic requirement <-> HPE-capability matching.

Shared by eligibility_gate.py (mandatory/eligibility) and fit_scoring.py
(technical/commercial/evaluation) so both use one matching rule, per the
brief's "must distinguish MATCH / PARTIAL_MATCH / UNKNOWN / NO_MATCH" and
"never claim a specific certification/reference without evidence" rules.

No LLM call is made here (none of the required infra — NeMo Agent Toolkit,
an LLM API key — is available in this environment; see IMPLEMENTATION_LOG.md).
Matching is keyword-overlap based, which is transparent, deterministic, and
testable, at the cost of missing paraphrases an LLM would catch. The
`match_requirement` signature is the seam where an LLM-based matcher could be
substituted later without touching callers.
"""

from __future__ import annotations

import re
import unicodedata

from src.schemas.briefing import CapabilityMatch
from src.schemas.common import MatchStatus
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import Requirement, RequirementCategory

_STOPWORDS = {
    "le", "la", "les", "de", "des", "du", "et", "ou", "un", "une", "au", "aux",
    "sur", "dans", "pour", "par", "avec", "sans", "doit", "doivent", "être",
    "est", "sont", "ainsi", "que", "qui", "son", "sa", "ses", "ces", "cette",
    "the", "and", "for", "with", "must", "shall", "this", "that", "are", "not",
    "section", "moins", "plus", "non", "aucun", "aucune", "tout", "tous",
}

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ]{4,}")

_CERT_HINTS = ("certifi", "iso ", "iso/", "iso27", "iso 9001", "soc 2", "soc2")
_REFERENCE_HINTS = ("référence", "reference", "références", "references")
_INSURANCE_HINTS = ("assurance", "insurance")
_LEGAL_HINTS = (
    "registre du commerce", "commercial register", "établissement stable",
    "swiss entity", "entité suisse",
)

_CHF_AMOUNT_RE = re.compile(r"chf\s*([\d'’ ]{3,})", re.IGNORECASE)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def significant_tokens(text: str) -> set[str]:
    tokens = {_fold(w.lower()) for w in _WORD_RE.findall(text)}
    return {t for t in tokens if _fold(t) not in {_fold(s) for s in _STOPWORDS}}


def _capability_overlap(requirement_text: str, profile: HPEProfile) -> tuple[MatchStatus, str | None, str]:
    if not profile.capabilities:
        return MatchStatus.UNKNOWN, None, "HPE profile lists no capabilities to match against."

    req_tokens = significant_tokens(requirement_text)
    if not req_tokens:
        return MatchStatus.UNKNOWN, None, "Requirement text has no significant keywords to match on."

    best_ratio = 0.0
    best_capability = None
    for capability in profile.capabilities:
        cap_tokens = significant_tokens(f"{capability.name} {capability.description or ''}")
        overlap = req_tokens & cap_tokens
        ratio = len(overlap) / len(req_tokens)
        if ratio > best_ratio:
            best_ratio = ratio
            best_capability = capability

    if best_ratio >= 0.25 and best_capability is not None:
        return (
            MatchStatus.MATCH,
            best_capability.name,
            f"Requirement keywords overlap with HPE capability '{best_capability.name}' ({best_ratio:.0%} of significant terms).",
        )
    if best_ratio > 0 and best_capability is not None:
        return (
            MatchStatus.PARTIAL_MATCH,
            best_capability.name,
            f"Partial keyword overlap with HPE capability '{best_capability.name}' ({best_ratio:.0%} of significant terms).",
        )
    return (
        MatchStatus.NO_MATCH,
        None,
        "No HPE capability in the profile shares significant keywords with this requirement.",
    )


def _certification_match(requirement_text: str, profile: HPEProfile) -> tuple[MatchStatus, str | None, str]:
    req_tokens = significant_tokens(requirement_text)
    for cert in profile.certifications:
        cert_tokens = significant_tokens(cert.name)
        if cert_tokens and cert_tokens <= req_tokens or (cert.name.lower() in requirement_text.lower()):
            return (
                MatchStatus.MATCH,
                cert.name,
                f"HPE profile lists certification '{cert.name}'"
                + (f" (source: {cert.citation.document})" if cert.citation else ""),
            )
    return (
        MatchStatus.UNKNOWN,
        None,
        (
            "No matching certification is listed in the HPE profile with a source citation — "
            "add one to data/hpe_profile.json to confirm, rather than assuming it's held."
        ),
    )


def _reference_match(requirement_text: str, profile: HPEProfile) -> tuple[MatchStatus, str | None, str]:
    req_tokens = significant_tokens(requirement_text)
    for ref in profile.references:
        ref_tokens = significant_tokens(f"{ref.project_description} {ref.client} {ref.location or ''}")
        if req_tokens & ref_tokens:
            return (
                MatchStatus.MATCH,
                ref.client,
                f"HPE profile lists a matching reference: '{ref.project_description}' ({ref.client})"
                + (f" (source: {ref.citation.document})" if ref.citation else ""),
            )
    return (
        MatchStatus.UNKNOWN,
        None,
        (
            "No matching reference is listed in the HPE profile with a source citation — "
            "add one to data/hpe_profile.json to confirm, rather than assuming HPE has a qualifying reference."
        ),
    )


def _insurance_match(requirement_text: str, profile: HPEProfile) -> tuple[MatchStatus, str | None, str]:
    if profile.insurance_coverage_chf is None:
        return (
            MatchStatus.UNKNOWN,
            None,
            "HPE profile does not record an insurance coverage figure — add a sourced value to confirm.",
        )
    match = _CHF_AMOUNT_RE.search(requirement_text)
    if not match:
        return MatchStatus.UNKNOWN, None, "Could not parse a required CHF amount from the requirement text."
    required = float(match.group(1).replace("'", "").replace("’", "").replace(" ", ""))
    if profile.insurance_coverage_chf >= required:
        return (
            MatchStatus.MATCH,
            "insurance coverage",
            (
                f"HPE profile records CHF {profile.insurance_coverage_chf:,.0f} coverage, "
                f"meeting the required CHF {required:,.0f}."
            ),
        )
    return (
        MatchStatus.NO_MATCH,
        "insurance coverage",
        (
            f"HPE profile records CHF {profile.insurance_coverage_chf:,.0f} coverage, "
            f"below the required CHF {required:,.0f}."
        ),
    )


def _legal_match(requirement_text: str) -> tuple[MatchStatus, str | None, str]:
    return (
        MatchStatus.UNKNOWN,
        None,
        "Legal/registration status is not modeled in the HPE profile — verify directly rather than assume.",
    )


def match_requirement(requirement: Requirement, profile: HPEProfile) -> CapabilityMatch:
    """Match one Requirement against the HPE profile. Deterministic, no LLM call."""
    text = requirement.description.lower()

    if any(hint in text for hint in _LEGAL_HINTS):
        status, capability, justification = _legal_match(text)
    elif requirement.category == RequirementCategory.CERTIFICATION or any(hint in text for hint in _CERT_HINTS):
        status, capability, justification = _certification_match(text, profile)
    elif requirement.category == RequirementCategory.REFERENCE or any(hint in text for hint in _REFERENCE_HINTS):
        status, capability, justification = _reference_match(text, profile)
    elif any(hint in text for hint in _INSURANCE_HINTS):
        status, capability, justification = _insurance_match(text, profile)
    else:
        status, capability, justification = _capability_overlap(text, profile)

    return CapabilityMatch(
        requirement_id=requirement.id,
        requirement_description=requirement.description,
        status=status,
        hpe_capability=capability,
        justification=justification,
        citation=requirement.citation,
    )


def match_all(requirements: list[Requirement], profile: HPEProfile) -> list[CapabilityMatch]:
    return [match_requirement(r, profile) for r in requirements]
