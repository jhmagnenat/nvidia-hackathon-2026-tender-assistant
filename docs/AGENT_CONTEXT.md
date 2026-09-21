# Agent context — HPE Tender Qualification

Short, operational reference for any agent (human or LLM) driving this
codebase's tools. Not a marketing document — see `data/hpe_profile.json`
for the actual profile data and `IMPLEMENTATION_LOG.md` for build history.

## Purpose

Qualify a Swiss public tender against HPE's actual, sourced capabilities and
produce a transparent GO/MAYBE/NO-GO recommendation — never a guess dressed
up as a fact.

## Workflow

```
search_tenders/select_tenders -> get_tender -> extract_requirements
  -> match_hpe_capabilities -> qualify_tender -> create_briefing
  -> submit_human_decision (approved/rejected/more_research)
  -> resume_after_research_request (re-verify, no new search)
  -> create_draft (only after an approved decision)
```

All of this is exposed as MCP tools in `src/mcp_server.py`; the underlying
logic lives in `src/agents/*` (deterministic, no LLM call — see
`src/agents/matching.py`'s docstring for why).

## Qualification dimensions

`src/agents/fit_scoring.py`'s `ScoreBreakdown` (100 pts): capability_fit (30)
+ mandatory_requirement_fit (25) + eligibility_fit (15) + delivery_feasibility
(10) + strategic_relevance (10) + information_confidence (10).

## Requirement statuses (`src.schemas.common.MatchStatus`)

- `MATCH` — real keyword/data overlap with a *sourced* HPE profile entry.
- `PARTIAL_MATCH` — some overlap, not a full match.
- `UNKNOWN` — the HPE profile has no sourced data for this dimension.
  **Not a confirmed gap** — profile incompleteness, not proof of absence.
- `NO_MATCH` — the profile has real data for this dimension and it clearly
  doesn't cover the requirement. Only ever set when there's something
  concrete to compare against, never as a default.

`UNKNOWN` never silently becomes `MATCH`. There is no fifth status.

## Recommendation rules (`src/agents/briefing.py`)

- Any mandatory requirement with a confirmed `NO_MATCH` → **NO-GO**,
  regardless of score.
- Any mandatory requirement still `UNKNOWN` → capped at **MAYBE**, even with
  a high score.
- Otherwise: score ≥ 70 → GO, score ≥ 45 → MAYBE, else NO-GO.

Same flags, enforced in code (not just documented here):
`unknown_is_not_match = true`, `technical_fit_does_not_prove_eligibility =
true`, `unsupported_claims_are_forbidden = true`,
`mandatory_unknown_caps_recommendation_at = MAYBE`.

## Evidence policy

Applies to `data/hpe_profile.json` (the live, scored profile) and to the
research artifacts (`data/hpe_profile_research_v4.json`,
`data/hpe_profile_canonical_v4.json`, normalized by
`src/agents/hpe_research_normalization.py`):

- **Official sources** (may back a `VERIFIED_PUBLIC` claim): `hpe.com`,
  `developer.hpe.com`, `newsroom.hpe.com`, official certification pages, and
  — for a certification claim specifically — the certifying body's own
  domain (e.g. `bsigroup.com`).
- **Secondary sources** (financial-data aggregators, Wikipedia, commercial
  register aggregators, trade-promotion sites, resellers/partners, PR
  distribution platforms, trade press, ...) never count as equivalent
  proof. A claim backed only by a secondary source is `PARTIALLY_VERIFIED`
  or `UNKNOWN`, never `VERIFIED_PUBLIC`.
- A historical announcement (e.g. a 2015 global ISO certification press
  release) is not proof of *current* validity, nor of a *specific entity's*
  (HPE Switzerland, or the exact bidding entity) inclusion in that scope.
- `LEGAL_ENTITY_FOUND` (a Swiss legal entity exists) and
  `LEGAL_ELIGIBILITY_UNKNOWN` (whether it can actually contract for a given
  tender) are two different facts — never collapse one into the other.
- A reference project scoped to one domain (e.g. CSCS/Alps — HPC/scientific
  computing) is not general proof of fitness for an unrelated domain (e.g. a
  generic cloud or managed-services tender). Domain-scoping is part of the
  evidence, not a detail to drop.
- A general technical/product capability is never treated as proof of a
  certification, client reference, legal presence, insurance, financial
  capacity, security clearance, or tender eligibility. Those are separate
  claims requiring their own separate evidence.
- Incomplete evidence stays `UNKNOWN` plus an explicit limitation note —
  never rounded up to something stronger.

## Human validation

A GO/MAYBE/NO-GO recommendation is a machine-generated proposal, never a
final decision. `submit_human_decision` (approved/rejected/more_research) is
the mandatory last step before a tender is treated as closed.
`resume_after_research_request` re-verifies a tender after a
`more_research` decision using its *existing* documents/profile — it never
triggers a new general search, and never upgrades an `UNKNOWN` to `MATCH`
without new sourced evidence actually being added to `data/hpe_profile.json`.
`create_draft` refuses to run unless the recorded decision is `approved`.

## Safety and governance

- No LLM call anywhere in scoring/matching/eligibility — fully deterministic
  and testable (see `src/agents/matching.py`'s docstring).
- Every fact traces to a `Citation` (document + section) or a sourced
  `data/hpe_profile.json` entry — nothing is asserted without one.
- Local-fallback/synthetic-sample data is always labeled as such
  (`source_type`, `notes`) — never presented as live SIMAP data.
- Workflow state (`data/workflow_state/<tender_id>.json`, see
  `src/agents/workflow_state.py`) persists score/recommendation/blockers/
  unknowns/human_review/research_requests/history across turns — a research
  request or human decision is never silently dropped between calls.

## Capability vs. eligibility

A capability match (HPE can technically do X) is **not** proof of
eligibility (HPE is legally/administratively allowed to bid on this specific
tender). Certifications, legal entity/registration, insurance, financial
capacity, and security clearances are eligibility facts, checked separately
in `src/agents/matching.py` (`_certification_match`, `_legal_match`,
`_insurance_match`, `_reference_match`) — never inferred from a capability
match.

## UNKNOWN handling

`UNKNOWN` is the honest default whenever the HPE profile has no sourced data
for a dimension. It:
- never blocks a `GO` recommendation *by itself* on a non-mandatory item,
- **does** cap a recommendation at `MAYBE` when the unresolved item is
  mandatory,
- is always listed in the briefing's `unknowns` (and `workflow_state`'s
  `unknowns` — the full, untruncated list; only the compact
  `executive_summary` view truncates for display),
- is resolved only by adding a real, sourced entry to
  `data/hpe_profile.json` — never by re-running matching with the same data
  and expecting a different answer.
