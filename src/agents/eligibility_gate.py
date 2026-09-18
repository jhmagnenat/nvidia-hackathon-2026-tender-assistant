"""EligibilityGate (Track B) — deterministic mandatory-requirement pass/fail.

Evaluates every requirement flagged `mandatory=True` (across
mandatory_requirements, eligibility_criteria, required_certifications,
required_references) against the HPE profile via matching.py. Intentionally
deterministic — a missed mandatory item should not be left to probabilistic
drift.

A single NO_MATCH mandatory item is a hard gate failure (should drive the
briefing agent to NO-GO). UNKNOWN mandatory items don't fail the gate — the
profile may simply be missing a sourced entry — but must not be silently
treated as passing either; the briefing agent caps the recommendation at
MAYBE when any remain unresolved.
"""

from src.agents.matching import match_all
from src.schemas.briefing import CapabilityMatch
from src.schemas.common import MatchStatus
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import ExtractedTenderData, Requirement


def mandatory_requirements(tender_data: ExtractedTenderData) -> list[Requirement]:
    """Every requirement flagged mandatory, across all extracted categories."""
    return [
        r
        for r in [
            *tender_data.mandatory_requirements,
            *tender_data.eligibility_criteria,
            *tender_data.required_certifications,
            *tender_data.required_references,
        ]
        if r.mandatory
    ]


def run_eligibility_gate(tender_data: ExtractedTenderData, profile: HPEProfile) -> list[CapabilityMatch]:
    """Return one CapabilityMatch per mandatory requirement."""
    return match_all(mandatory_requirements(tender_data), profile)


def gate_has_hard_failure(matches: list[CapabilityMatch]) -> bool:
    """True if any mandatory requirement is a confirmed NO_MATCH — should force NO-GO."""
    return any(m.status == MatchStatus.NO_MATCH for m in matches)


def gate_has_unknown(matches: list[CapabilityMatch]) -> bool:
    """True if any mandatory requirement couldn't be resolved — caps recommendation at MAYBE."""
    return any(m.status == MatchStatus.UNKNOWN for m in matches)
