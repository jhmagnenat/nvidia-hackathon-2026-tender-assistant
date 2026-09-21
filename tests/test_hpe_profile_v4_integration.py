"""Regression coverage for the HPE profile V4 research integration (Étape 8)
and its 2026-09-22 follow-up: the minimal compatible integration.

The V4 research was reviewed and normalized
(src/agents/hpe_research_normalization.py,
data/hpe_profile_canonical_v4.json). Two additive, officially-sourced
changes were then applied to the LIVE, scored profile
(data/hpe_profile.json, see its `notes` field for the full record):
- 'AI infrastructure' description enriched with real product names.
- a new 'HPC and supercomputing' capability added (HPE Cray EX / CSCS
  'Alps'), explicitly scoped to HPC/scientific-computing tenders only.

No certification/reference/legal/insurance claim was added or upgraded —
no sufficiently strong (official + current + Swiss-scoped) evidence was
found for any of those, so they stay exactly as they were (empty/UNKNOWN).

Disclosed consequence: adding the 11th capability entry shifted every
existing tender's score down slightly, because
src/agents/fit_scoring.py::_strategic_relevance divides by
len(profile.capabilities) — this is the deterministic, verified result of
adding genuinely new sourced data, not a manual score edit; the exact new
values are pinned below and in tests/test_mcp_server.py.
"""

import json

from src import mcp_server
from src.agents.workflow import load_hpe_profile
from src.schemas.hpe_research_profile import load_research_profile

_ORIGINAL_TEN_CAPABILITIES = {
    "hybrid cloud",
    "managed cloud infrastructure",
    "data center services",
    "networking",
    "cybersecurity",
    "AI infrastructure",
    "consulting",
    "technical support",
    "infrastructure modernization",
    "public-sector technology services",
}


def test_old_capabilities_remain_available_in_the_live_profile():
    """None of the original 10 capabilities were removed or renamed — the
    minimal integration only enriched 'AI infrastructure''s description
    (same name, same list position) and appended one new entry."""
    profile = load_hpe_profile()
    names = {c.name for c in profile.capabilities}
    assert _ORIGINAL_TEN_CAPABILITIES <= names  # every original name still present
    assert len(profile.capabilities) == 11  # 10 original + 1 new (HPC and supercomputing)


def test_live_profile_certifications_references_insurance_untouched():
    """No V4 evidence met the bar (official + current + Swiss-scoped) to
    populate these — see data/hpe_profile.json's notes field and
    docs/AGENT_CONTEXT.md's evidence policy."""
    profile = load_hpe_profile()
    assert profile.certifications == []
    assert profile.references == []
    assert profile.insurance_coverage_chf is None


def test_new_hpc_capability_is_integrated_into_the_live_profile_with_a_citation():
    """The one new capability from the minimal integration: sourced
    (real hpe.com press release), scoped in its own description to
    HPC/scientific-computing tenders, and citation-backed — unlike the
    original 10 illustrative entries, which carry no citation."""
    canonical = load_research_profile("data/hpe_profile_canonical_v4.json")
    canonical_ids = {c.capability_id for c in canonical.capabilities}
    assert "hpc_supercomputing" in canonical_ids  # confirms the live entry traces back to real V4 research

    live = load_hpe_profile()
    hpc = next(c for c in live.capabilities if c.name == "HPC and supercomputing")
    assert "HPC/scientific-computing tenders only" in hpc.description
    assert hpc.citation is not None
    assert hpc.citation.document.startswith("https://hpe.com") or hpc.citation.document.startswith("https://www.hpe.com")

    ai = next(c for c in live.capabilities if c.name == "AI infrastructure")
    assert "HPE Private Cloud AI" in ai.description
    assert ai.citation is not None


def test_context_dependent_areas_are_not_marked_as_confirmed_capabilities():
    canonical = load_research_profile("data/hpe_profile_canonical_v4.json")
    context_dependent = [c for c in canonical.capabilities if c.capability_strength == "CONTEXT_DEPENDENT"]
    assert context_dependent
    for cap in context_dependent:
        assert cap.evidence_status.value != "VERIFIED_PUBLIC"

    with open("data/hpe_profile_canonical_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    for area in raw["context_dependent_areas"]:
        assert area["status"] in {"CONTEXT_DEPENDENT", "UNKNOWN"}


def test_out_of_scope_categories_are_all_no_match():
    with open("data/hpe_profile_canonical_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["out_of_scope_categories"]
    assert all(c["status"] == "NO_MATCH" for c in raw["out_of_scope_categories"])


def test_incomplete_certifications_stay_unknown_or_partially_verified_never_verified_public():
    with open("data/hpe_profile_canonical_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["certifications"]
    assert all(c["evidence_status"] in {"PARTIALLY_VERIFIED", "UNKNOWN"} for c in raw["certifications"])


def test_unsourced_swiss_legal_eligibility_stays_unknown():
    with open("data/hpe_profile_canonical_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    swiss_topic = next(
        g for g in raw["geographic_coverage"] if "legal entity capability for a specific tender" in g["topic"]
    )
    assert swiss_topic["status"] == "UNKNOWN"

    entity = raw["legal_entities"][0]
    assert entity["status"] == "LEGAL_ENTITY_FOUND"
    assert entity["legal_eligibility_status"] == "LEGAL_ELIGIBILITY_UNKNOWN"


def test_cscs_reference_is_scoped_to_hpc_not_general_cloud_or_managed_services():
    with open("data/hpe_profile_canonical_v4.json", encoding="utf-8") as f:
        raw = json.load(f)
    cscs = raw["public_sector_references"][0]
    assert "HPC" in cscs["directly_comparable_to_swiss_tender"] or "scientific" in cscs["directly_comparable_to_swiss_tender"]
    assert "not for general administrative IT tenders" in cscs["directly_comparable_to_swiss_tender"]


def test_iso_27001_still_reports_unknown_for_cloud_infra_2026_never_match():
    result = mcp_server.match_hpe_capabilities("cloud-infra-2026")
    assert result["status"] == "ok"
    cert_matches = [m for m in result["matches"] if "27001" in m["requirement_description"].lower()]
    assert cert_matches
    assert all(m["status"] != "match" for m in cert_matches)


def test_swiss_registration_requirement_still_unknown():
    result = mcp_server.match_hpe_capabilities("cloud-infra-2026")
    legal_matches = [
        m for m in result["matches"] if "registre du commerce" in m["requirement_description"].lower()
    ]
    assert legal_matches
    assert all(m["status"] == "unknown" for m in legal_matches)


def test_cloud_infra_2026_score_reflects_the_disclosed_v4_integration_delta():
    """Score moved from 61.1 to 60.2 (2026-09-22) as the disclosed,
    deterministic consequence of adding one sourced capability (see this
    module's docstring and data/hpe_profile.json's notes) — not a manual
    edit. Same tenders, same documents, same matching rules; only
    len(profile.capabilities) changed (10 -> 11)."""
    result = mcp_server.qualify_tender("cloud-infra-2026")
    assert result["status"] == "ok"
    assert result["briefing"]["score"] == 60.2


def test_new_hpc_capability_does_not_change_which_requirements_were_already_resolved():
    """The three demo tenders are not HPC-shaped -- adding the new HPC
    capability must not turn any of their previously-UNKNOWN/NO_MATCH items
    into a MATCH (that would mean the new capability's keywords are being
    over-applied outside its stated scope)."""
    for tender_id in ("cloud-infra-2026", "cybersec-managed-2026", "datacenter-modernization-2026"):
        result = mcp_server.match_hpe_capabilities(tender_id)
        hpc_credited = [m for m in result["matches"] if m["hpe_capability"] == "HPC and supercomputing"]
        assert hpc_credited == []
