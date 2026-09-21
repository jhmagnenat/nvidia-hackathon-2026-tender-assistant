"""Normalizes the raw HPE web-research profile
(data/hpe_profile_research_v4.json) into the canonical shape
(data/hpe_profile_canonical_v4.json) — see docs/AGENT_CONTEXT.md's
"evidence policy" section and the rules below.

Deterministic, rule-based, no LLM call: applies exactly the source-tiering
rule from the migration brief —

    A claim marked VERIFIED_PUBLIC but backed only by a secondary/
    commercial/aggregator source must be downgraded to PARTIALLY_VERIFIED.
    Official sources: hpe.com / developer.hpe.com / newsroom.hpe.com, and
    (for a certification claim specifically) the certifying body's own
    domain (e.g. bsigroup.com).

— and reshapes `services[].source` (a bare URL string) into
`services[].sources` (a list), reusing the matching full source object from
the profile's own `sources` registry when one exists.

Never invents a fact, a source, or a higher evidence tier than the research
data itself supports; never upgrades anything; never touches an entry
that's already below VERIFIED_PUBLIC. Only ever narrows/downgrades or
reshapes — see `normalize_research_profile`, the single entry point.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_OFFICIAL_HOST_SUFFIXES = ("hpe.com", "developer.hpe.com", "newsroom.hpe.com")
# Accredited/official certification bodies count as official evidence for a
# certification claim specifically (rule 1's "sources officielles des
# organismes de certification") even though their domain isn't hpe.com.
_OFFICIAL_CERTIFICATION_BODY_HOST_SUFFIXES = ("bsigroup.com",)

_DOWNGRADE_NOTE = (
    "Downgraded from VERIFIED_PUBLIC to PARTIALLY_VERIFIED: no official "
    "HPE/certification-body source among the evidence for this claim."
)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def is_official_source(url: str, *, certification_claim: bool = False) -> bool:
    """True only for hpe.com/developer.hpe.com/newsroom.hpe.com (any claim),
    or an accredited certification body's own domain (certification claims
    only) — see rule 1. Every other domain (financial-data aggregators,
    Wikipedia, commercial register aggregators, resellers/partners, PR
    distribution platforms, trade press, government-adjacent trade-promotion
    sites, ...) is secondary, per rule 2."""
    host = _host(url)
    if not host:
        return False
    suffixes = _OFFICIAL_HOST_SUFFIXES
    if certification_claim:
        suffixes = suffixes + _OFFICIAL_CERTIFICATION_BODY_HOST_SUFFIXES
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def _downgrade_if_secondary_only(
    entry: dict[str, Any],
    source_urls: list[str],
    *,
    status_key: str,
    limitation_key: str,
    certification_claim: bool = False,
) -> dict[str, Any]:
    """Copy of `entry`, downgraded (Étape 2 rule 3) only if `status_key` is
    exactly "VERIFIED_PUBLIC" and none of `source_urls` is official —
    already-lower statuses (PARTIALLY_VERIFIED/UNKNOWN) are left untouched,
    and nothing is ever upgraded."""
    entry = dict(entry)
    urls = [u for u in source_urls if u]
    has_official_source = any(is_official_source(u, certification_claim=certification_claim) for u in urls)
    if entry.get(status_key) == "VERIFIED_PUBLIC" and urls and not has_official_source:
        entry[status_key] = "PARTIALLY_VERIFIED"
        existing = entry.get(limitation_key)
        entry[limitation_key] = f"{existing} {_DOWNGRADE_NOTE}" if existing else _DOWNGRADE_NOTE
    return entry


def normalize_capabilities(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _downgrade_if_secondary_only(
            c, c.get("evidence_sources", []), status_key="evidence_status", limitation_key="limitations"
        )
        for c in capabilities
    ]


def normalize_geographic_coverage(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _downgrade_if_secondary_only(
            e, [e.get("source")], status_key="status", limitation_key="detail_limitation"
        )
        for e in entries
    ]


def normalize_delivery_capabilities(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _downgrade_if_secondary_only(e, [e.get("source")], status_key="status", limitation_key="limitation")
        for e in entries
    ]


def normalize_certifications(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _downgrade_if_secondary_only(
            e,
            [e.get("official_evidence_url")],
            status_key="evidence_status",
            limitation_key="limitations",
            certification_claim=True,
        )
        for e in entries
    ]


def normalize_services(services: list[dict[str, Any]], sources_registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`services[].source` (bare URL string) -> `services[].sources` (list) —
    reuses the matching full source object from `sources_registry` by URL
    when one exists there, otherwise wraps the bare URL so nothing is lost
    (Étape 4: "conserver les sources existantes ; ne perdre aucune
    limitation")."""
    by_url = {s.get("url"): s for s in sources_registry if s.get("url")}
    normalized = []
    for svc in services:
        svc = dict(svc)
        url = svc.pop("source", None)
        if url:
            svc["sources"] = [by_url[url]] if url in by_url else [{"url": url}]
        else:
            svc["sources"] = []
        normalized.append(svc)
    return normalized


def normalize_research_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Single entry point: returns a new dict (never mutates `raw`) with the
    downgrade + services-source-reshaping rules applied. Every other
    top-level section (profile_metadata, provider, products_and_platforms,
    context_dependent_areas, out_of_scope_categories, legal_entities,
    public_sector_references, commercial_models, qualification_rules,
    unknowns, sources) is carried through unchanged — already correctly
    scoped/sourced in the research data itself (see the migration report)."""
    profile = dict(raw)
    profile["capabilities"] = normalize_capabilities(raw.get("capabilities", []))
    profile["services"] = normalize_services(raw.get("services", []), raw.get("sources", []))
    profile["geographic_coverage"] = normalize_geographic_coverage(raw.get("geographic_coverage", []))
    profile["delivery_capabilities"] = normalize_delivery_capabilities(raw.get("delivery_capabilities", []))
    profile["certifications"] = normalize_certifications(raw.get("certifications", []))
    return profile
