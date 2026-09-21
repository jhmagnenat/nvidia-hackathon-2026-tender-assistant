"""src.agents.hpe_research_normalization — deterministic source-tiering and
services-reshaping rules for the HPE web-research profile (Étape 2/4)."""

import json

from src.agents.hpe_research_normalization import (
    is_official_source,
    normalize_certifications,
    normalize_geographic_coverage,
    normalize_research_profile,
    normalize_services,
)


def test_is_official_source_recognizes_hpe_domains():
    assert is_official_source("https://www.hpe.com/us/en/about/enterprise-technology-us.html")
    assert is_official_source("https://developer.hpe.com/platform/hpe-greenlake/home/")
    assert is_official_source("https://newsroom.hpe.com/some-press-release")


def test_is_official_source_rejects_secondary_domains():
    assert not is_official_source("https://kavout.com/stocks/nyse-hpe/hewlett-packard-enterprise-co")
    assert not is_official_source("https://sp-edge.com/companies/341503")
    assert not is_official_source("https://en.wikipedia.org/wiki/Zerto")
    assert not is_official_source("https://www.northdata.com/some-entity")
    assert not is_official_source("https://www.s-ge.com/ko/node/2672")


def test_is_official_source_certification_body_only_counts_for_certification_claims():
    bsi_url = "https://www.bsigroup.com/en-US/about-bsi/Media-Center/Press-Releases/2015/"
    assert is_official_source(bsi_url, certification_claim=True)
    assert not is_official_source(bsi_url, certification_claim=False)


def test_normalize_certifications_downgrades_secondary_only_verified_public():
    entries = [
        {
            "certification_name": "ISO 9001 / ISO 27001",
            "official_evidence_url": "https://midisgroup.com/some-partner-press-release",
            "evidence_status": "VERIFIED_PUBLIC",
            "limitations": "Applies to a regional partner entity only.",
        }
    ]
    normalized = normalize_certifications(entries)
    assert normalized[0]["evidence_status"] == "PARTIALLY_VERIFIED"
    assert "Applies to a regional partner entity only." in normalized[0]["limitations"]
    assert "Downgraded" in normalized[0]["limitations"]


def test_normalize_certifications_never_upgrades_and_never_touches_already_lower_status():
    entries = [
        {
            "certification_name": "Global ISO bundle",
            "official_evidence_url": "https://www.bsigroup.com/some-press-release",
            "evidence_status": "PARTIALLY_VERIFIED",
            "limitations": "2015 announcement, current validity unconfirmed.",
        }
    ]
    normalized = normalize_certifications(entries)
    assert normalized[0]["evidence_status"] == "PARTIALLY_VERIFIED"
    assert normalized[0]["limitations"] == "2015 announcement, current validity unconfirmed."


def test_normalize_certifications_keeps_verified_public_when_officially_sourced():
    entries = [
        {
            "certification_name": "Some certification",
            "official_evidence_url": "https://www.bsigroup.com/official-press-release",
            "evidence_status": "VERIFIED_PUBLIC",
        }
    ]
    normalized = normalize_certifications(entries)
    assert normalized[0]["evidence_status"] == "VERIFIED_PUBLIC"


def test_normalize_geographic_coverage_downgrades_secondary_source():
    entries = [{"topic": "Swiss office presence", "status": "VERIFIED_PUBLIC", "source": "https://www.s-ge.com/x"}]
    normalized = normalize_geographic_coverage(entries)
    assert normalized[0]["status"] == "PARTIALLY_VERIFIED"


def test_normalize_services_converts_source_to_sources_and_reuses_registry_entry():
    services = [{"service": "AI factory delivery", "source": "https://www.hpe.com/press/ai-factory"}]
    sources_registry = [
        {"title": "AI factory PR", "url": "https://www.hpe.com/press/ai-factory", "publisher": "HPE"}
    ]

    normalized = normalize_services(services, sources_registry)

    assert "source" not in normalized[0]
    assert normalized[0]["sources"] == [{"title": "AI factory PR", "url": "https://www.hpe.com/press/ai-factory", "publisher": "HPE"}]


def test_normalize_services_wraps_bare_url_when_not_in_registry():
    services = [{"service": "Some service", "source": "https://example.com/not-in-registry"}]
    normalized = normalize_services(services, sources_registry=[])
    assert normalized[0]["sources"] == [{"url": "https://example.com/not-in-registry"}]


def test_normalize_research_profile_end_to_end_on_the_real_v4_file():
    """Regression against the actual data/hpe_profile_research_v4.json —
    proves the exact downgrades this migration report claims happen."""
    with open("data/hpe_profile_research_v4.json", encoding="utf-8") as f:
        raw = json.load(f)

    normalized = normalize_research_profile(raw)

    by_id = {c["capability_id"]: c for c in normalized["capabilities"]}
    # Secondary-source-only capabilities: downgraded.
    assert by_id["compute_infrastructure"]["evidence_status"] == "PARTIALLY_VERIFIED"
    assert by_id["storage_infrastructure"]["evidence_status"] == "PARTIALLY_VERIFIED"
    assert by_id["enterprise_networking"]["evidence_status"] == "PARTIALLY_VERIFIED"
    # Officially-sourced capabilities: left VERIFIED_PUBLIC.
    assert by_id["hybrid_private_cloud"]["evidence_status"] == "VERIFIED_PUBLIC"
    assert by_id["ai_infrastructure"]["evidence_status"] == "VERIFIED_PUBLIC"
    assert by_id["hpc_supercomputing"]["evidence_status"] == "VERIFIED_PUBLIC"
    # Already-PARTIALLY_VERIFIED entries (managed_services/backup): untouched.
    assert by_id["managed_services"]["evidence_status"] == "PARTIALLY_VERIFIED"
    assert by_id["backup_data_protection"]["evidence_status"] == "PARTIALLY_VERIFIED"

    # The Selectium (Slovenia) certification: secondary-sourced (midisgroup.com) -> downgraded.
    selectium = next(c for c in normalized["certifications"] if "Selectium" in c.get("holder", ""))
    assert selectium["evidence_status"] == "PARTIALLY_VERIFIED"

    # services[].source is gone; services[].sources is a non-empty list everywhere a source existed.
    for svc in normalized["services"]:
        assert "source" not in svc
        assert svc["sources"]

    # Nothing was invented: every UNKNOWN in the original stays UNKNOWN (never upgraded).
    original_unknowns = {a["area"] for a in raw["context_dependent_areas"] if a["status"] == "UNKNOWN"}
    normalized_unknowns = {a["area"] for a in normalized["context_dependent_areas"] if a["status"] == "UNKNOWN"}
    assert original_unknowns == normalized_unknowns
    assert raw["unknowns"] == normalized["unknowns"]
