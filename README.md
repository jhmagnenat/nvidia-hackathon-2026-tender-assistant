# Agentic Tender Assistant

Agentic assistant that searches Swiss public tenders, retrieves and analyzes
their documents, compares the requirements against HPE's capabilities as a
service provider, and produces a structured **qualification briefing** — not
just a summary — answering: *as HPE, is this tender worth pursuing, what are
the mandatory requirements, what are the risks, and what should we do next?*

Built for the HPE & NVIDIA Agentic AI Hackathon for Enterprises (Swiss AI Weeks).

See [CHALLENGE.md](./CHALLENGE.md) for the official brief,
[docs/architecture.md](./docs/architecture.md) for the pipeline design, and
[IMPLEMENTATION_LOG.md](./IMPLEMENTATION_LOG.md) for what was actually built,
what's a fallback vs. a real integration, and why.

## Business workflow

```
User query -> tender search -> tender selection -> document retrieval
  -> requirement extraction -> HPE capability matching -> qualification scoring
  -> structured qualification briefing -> human approval -> feedback recording
```

## Availability of NVIDIA/MCP components in this environment

None of NeMo Agent Toolkit, NemoClaw, Hermes, AIQ Blueprint, a generic MCP
client, or Tavily are reachable from this environment (no CLI, no package, no
API key — see IMPLEMENTATION_LOG.md Phase 0 for the exact checks run). The
SIMAP MCP config under `integrations/simap/` targets a *separate* external
Hermes sandbox, not this one. **The app therefore runs entirely on local
fallback data by design (rule 6), with clean adapter seams
(`src/adapters/`) so a real integration is additive, not a rewrite.**

## Repo structure

```
src/
  schemas/        Pydantic contracts: Tender, TenderDocument, Requirement,
                   ExtractedTenderData, HPEProfile, QualificationBriefing, ...
  adapters/        Search/document-retrieval provider seams (SIMAP/Tavily
                   stubs + the guaranteed local-sample fallback)
  agents/
    ingestion.py         RequirementExtractionAgent — deterministic, cited extraction
    matching.py          Shared MATCH/PARTIAL_MATCH/UNKNOWN/NO_MATCH engine
    eligibility_gate.py  Deterministic mandatory-requirement gate
    fit_scoring.py       Transparent 0-100 ScoreBreakdown
    briefing.py          Assembles the final QualificationBriefing + GO/MAYBE/NO-GO
    qualification.py     HPEQualificationAgent (composes the three above)
    search.py            TenderSearchTool
    retrieval.py         DocumentRetrievalTool
    workflow.py          WorkflowOrchestrator (search -> ... -> qualify)
    feedback.py          Human-approval / feedback recording
  pipeline.py     CLI entry point
app.py            Streamlit UI (port 8507)
data/
  hpe_profile.json          Editable HPE provider profile (capabilities,
                             certifications, references — see below)
  sample_tenders.json       Local search-fallback index (4 synthetic tenders)
  sample_tenders/<id>/*.txt Synthetic tender documents (committed on purpose —
                             see data/sample_tenders/README.md)
  feedback_log.json         Runtime human-review log (gitignored, created on first use)
tests/            Mirrors src/, one test module per agent/adapter + schema tests
IMPLEMENTATION_LOG.md   Phase-by-phase build log — read this for the "why"
```

## HPE profile — transparent and editable

`data/hpe_profile.json` is the single source of truth for HPE-side matching.
It ships with 10 generic, illustrative capabilities (hybrid cloud, managed
cloud infrastructure, data center services, networking, cybersecurity, AI
infrastructure, consulting, technical support, infrastructure modernization,
public-sector technology services) and **empty** `certifications`/`references`
lists. This is intentional, not a bug: rule 8 forbids fabricating a
certification or reference, so until you add a real, sourced entry (with a
`citation`), any tender requiring one will honestly show up as **UNKNOWN**
rather than a false MATCH. Edit the file directly to add real, cited data —
that's the intended way to improve a briefing's recommendation.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # if python3-venv is available
pip install -e ".[dev]"
```

If `python3 -m venv` fails with `ensurepip is not available` (no
`python3-venv` package, no sudo) — as it did in this sandbox — install
without a venv instead:

```bash
python3 -m pip install --user --break-system-packages -e ".[dev]"
```

Both install the same dependencies (`pydantic`, `python-dotenv`, `streamlit`,
plus `pytest`/`ruff` for `[dev]`); no `.env`/API key is required for the demo.

## Run the demo

```bash
# CLI
python -m src.pipeline search "cloud infrastructure managed services cybersecurity"
python -m src.pipeline analyze cloud-infra-2026
python -m src.pipeline run "cloud infrastructure managed services cybersecurity" --out briefing.json
python -m src.pipeline analyze cloud-infra-2026 --approve --reviewer "Jane Doe" --notes "Looks good"

# Streamlit UI (port 8507, set in .streamlit/config.toml)
streamlit run app.py
```

In the UI: enter a query -> **Search** -> pick a tender -> **Analyze** ->
review the briefing (score breakdown, mandatory requirements with citations,
capability matches, gaps, risks, next actions) -> **Approve** / **Reject** /
**Request more research** (recorded to `data/feedback_log.json`) -> download
the briefing JSON.

### Scripted demo scenario

1. Search `"Find Swiss tenders related to cloud infrastructure, managed
   services and cybersecurity"` — 3 relevant sample tenders come back; an
   unrelated office-furniture tender does not (proves search relevance
   filtering).
2. Analyze `cloud-infra-2026` — lands on **MAYBE**: strong technical
   capability matches, but the ISO/IEC 27001 certification and the Swiss
   reference requirement are honestly **UNKNOWN** (the shipped HPE profile
   has no certifications/references yet).
3. Analyze `office-furniture-2026` (unrelated tender) — lands on **NO-GO**: a
   confirmed capability mismatch, not a probabilistic guess.
4. Edit `data/hpe_profile.json`, add a `certifications` entry for
   `ISO/IEC 27001` with a `citation`, and re-analyze `cloud-infra-2026` — watch
   the mandatory-requirement match flip from UNKNOWN to MATCH and the score
   improve. This is the intended "transparent, editable, sourced-only" story.

Run the test suite any time with `pytest` (49+ tests, `ruff check .` clean).

## Status

MVP complete per IMPLEMENTATION_LOG.md phases 0-6: schemas, local-fallback
search/retrieval adapters, deterministic requirement extraction, HPE
capability matching, transparent scoring, qualification briefing, human
review/feedback recording, and a Streamlit UI all implemented and tested.
NeMo Agent Toolkit / AIQ Blueprint / SIMAP / Tavily MCP integrations remain
adapter stubs, documented as unreachable from this environment rather than
faked — see IMPLEMENTATION_LOG.md Phase 0 and 6.
