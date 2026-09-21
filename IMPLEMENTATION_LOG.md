# Implementation Log — Agentic Tender Assistant (HPE qualification MVP)

One-day hackathon build. This log is updated at the end of every phase.
Workspace: `~/projects/jean test` (isolated personal workspace). No files
outside this repository were touched. No destructive git/kubectl/helm/docker
commands were run.

## Phase 0 — Read-only audit

**Repository (before this session's changes):**
- `src/schemas/{common,tender,company,briefing}.py` — Pydantic contracts, fully defined.
- `src/agents/{ingestion,eligibility_gate,fit_scoring,briefing}.py` — all four stubs, `raise NotImplementedError`.
- `src/pipeline.py` — orchestration wiring (`run_pipeline`), takes a local PDF folder + company profile path. No search/selection step existed.
- `tests/` — one module per agent, each only asserting `NotImplementedError`; `tests/test_schemas.py`, `tests/conftest.py` fixtures.
- `data/company_profile.example.json` — generic bidder profile, no HPE-specific data.
- `data/sample_tenders/` — empty (gitignored), README describing expected PDF folder layout only.
- `integrations/simap/` — SIMAP MCP server config for the NemoClaw/Hermes **sandbox environment** (not this environment): `hermes-config.example.yaml`, `policy.yaml`, `package.json` pinning `@digilac/simap-mcp@1.4.0`. Per `docs/NEMOHERMES_SETUP.md`, this was verified working in a *different*, separate Hermes sandbox (14 tools, live cantons + tender search), not in this repo/environment.
- `deploy/hermes-ingress/` — optional nginx ingress for that same external Hermes dashboard. Irrelevant to this MVP's runtime.
- No Streamlit, no HPE capability model, no qualification scoring, no GO/MAYBE/NO-GO logic, no human-approval step, no Tavily reference anywhere in the repo.

**Availability check, run in this actual environment:**

| Component | Found in repo? | Available in this environment? | Decision |
|---|---|---|---|
| NeMo Agent Toolkit | mentioned only in comments/docs, never adopted | not installed (`pip show nvidia-nat`/`aiqtoolkit` → not found; no `aiq`/`nvidia-nat` command) | **fallback**: plain Python orchestration (as `docs/architecture.md` already chose) |
| NemoClaw | referenced in `docs/NEMOHERMES_SETUP.md` for an external sandbox | no `nemoclaw`/`nemohermes`/`hermes` command in this shell | **fallback**: not used; documented as external/optional infra only |
| Hermes | same as above | same as above | **fallback**: not used |
| AIQ Blueprint | not found anywhere (`grep` across repo: no hits) | no `aiq` command, no package | **fallback**: not used; no blueprint format to target |
| MCP (generic) | only the SIMAP MCP server config for the external Hermes sandbox | no `mcp` Python package installed, no MCP client wired into `src/` | **adapter**: clean `TenderSearchTool` interface with a `SimapAdapter` stub that reports itself unavailable in this environment; real backend would be the MCP server if a Hermes sandbox were reachable from here (it is not) |
| Tavily MCP | not found anywhere in repo | no `tavily` package/command | **adapter**: `TavilyAdapter` stub, reports unavailable, never fabricates search results |
| SIMAP MCP | config present for external sandbox use only | not reachable from this shell (no MCP client, no network policy applied here) | **adapter**: `SimapAdapter` stub, same pattern |

**Local environment (this shell):** Python 3.12.3, Node v22.23.2. No system Python venv module (`python3-venv` not installed, and `apt install` requires sudo/system changes out of scope for a repo-local task) — instead used `pip install --user --break-system-packages` to install `pydantic`, `python-dotenv`, `pytest`, `ruff`, `streamlit` into the user's local site-packages (`~/.local`), no sudo, no system package changes, fully reversible with `pip uninstall`. Network access to PyPI confirmed available. Ports 8507/8017/8501/8000 all free at audit time.

**Conclusion:** every "advanced" NVIDIA/MCP/Tavily component named in the brief is either absent from this environment or only ever configured for a separate external sandbox that this shell cannot reach. Per rule 5/6, the MVP is built entirely on deterministic local fallbacks, with clean adapter seams so a real SIMAP/Tavily/NeMo integration could be dropped in later without touching business logic.

## Phase 1 — Foundation

- Redesigned `src/schemas/`: `common.py` gained `MatchStatus`, `Recommendation`,
  `Confidence`. `tender.py` now models the full search→extraction pipeline:
  `Tender` (search-result level), `TenderDocument`, `Deadline`, `Requirement`
  (+ `RequirementCategory`), `ExtractedTenderData`. `company.py` was replaced by
  `hpe_profile.py` (`Capability`, `Certification`, `Reference`, `HPEProfile`) —
  the generic bidder-profile concept no longer fits an HPE-specific assistant.
  `briefing.py` now matches the brief's JSON structure: `CapabilityMatch`,
  `ScoreBreakdown` (transparent 30/25/15/10/10/10 point dimensions),
  `HumanReview`/`HumanDecision`, `QualificationBriefing`.
  This is a deliberate break from "preserve structure unless there's a strong
  reason" — the business object model itself changed (search/selection didn't
  exist before; scoring is now HPE-specific with GO/MAYBE/NO-GO).
- `data/hpe_profile.json`: the editable HPE profile. Ships with 10 generic,
  illustrative capabilities (no citation needed — they're not certifications or
  claims of a specific engagement) and **empty** `certifications`/`references`
  lists — per rule 8, nothing is fabricated; add real entries with a `citation`
  to unlock stronger matches.
- `data/sample_tenders.json` + `data/sample_tenders/<id>/{notice,cahier_des_charges}.txt`:
  4 synthetic Swiss tenders (cloud infra, managed cybersecurity SOC, data-center
  modernization, plus one deliberately irrelevant office-furniture tender to
  prove search relevance filtering). Clearly labeled as synthetic demo data in
  both the files themselves and `data/sample_tenders/README.md`. Deadlines are
  set at varying distances from today (2026-09-18) to exercise the delivery-
  feasibility scoring dimension. `.gitignore` updated: these `.txt` fixtures are
  committed on purpose (only real PDFs/docx stay ignored).
- Tests: `tests/conftest.py` and `tests/test_schemas.py` rewritten against the
  new models (round-trip serialization, `ScoreBreakdown.total`, briefing JSON
  shape). **5/5 passing.**

## Phase 2 — Search and document adapters

- `src/adapters/tender_search.py`: `TenderSearchAdapter` base +
  `SimapAdapter`/`TavilyAdapter` (both correctly report `available = False` in
  this environment — no MCP client, no Tavily key/package — and raise
  `AdapterUnavailableError` rather than fabricate results) +
  `LocalSampleSearchAdapter` (keyword search over `data/sample_tenders.json`,
  optional location filter) + `get_search_adapter()` picking the first
  available in preference order, local sample always guaranteed.
- `src/adapters/document_retrieval.py`: same pattern — `URLDocumentAdapter`
  (disabled by design, no network dependency) + `LocalDocumentAdapter` (reads
  `data/sample_tenders/<id>/*.txt`) + `get_document_adapter()`.
- Verified manually: searching "cloud infrastructure managed services
  cybersecurity" correctly returns the 3 relevant sample tenders and excludes
  the office-furniture one.
- Tests: `tests/adapters/test_tender_search.py`,
  `tests/adapters/test_document_retrieval.py`. **10/10 passing** (15/15 total
  with Phase 1).

## Phase 3 — Extraction and qualification

- `src/agents/ingestion.py` (`RequirementExtractionAgent`): deterministic
  section-header/bullet parser for the synthetic `.txt` fixtures. Handles
  multi-line wrapped bullets (joins continuation lines onto the bullet without
  ever merging into a header — this needed two iterations to get right, see
  test `test_extract_requirements_joins_wrapped_bullet_lines`), parses
  evaluation-criteria weights (`Prix: 40%` -> `weight_percent=40.0`),
  `[section X.Y]` citation tags, and marks `souhaitée`/optional certifications
  as non-mandatory. No LLM call — none of the required LLM/NeMo infra is
  reachable here (Phase 0).
- `src/agents/matching.py`: the shared deterministic MATCH/PARTIAL_MATCH/
  UNKNOWN/NO_MATCH engine (keyword overlap, French+English capability
  synonyms in `data/hpe_profile.json`). Key rule, directly from the brief:
  certifications/references absent from the HPE profile resolve to **UNKNOWN**,
  never NO_MATCH — profile incompleteness isn't a confirmed gap. NO_MATCH is
  reserved for cases with real profile data that clearly doesn't cover the
  requirement (e.g. office furniture vs. an IT capability list), plus a
  numeric insurance-coverage comparison when the profile does carry a figure.
  Legal/registration criteria (Swiss commercial register, etc.) always resolve
  UNKNOWN — not modeled in the HPE profile at all, never assumed.
- `src/agents/eligibility_gate.py`: deterministic mandatory-requirement gate
  (`gate_has_hard_failure` / `gate_has_unknown`) over every requirement flagged
  `mandatory=True` across all extracted categories.
- `src/agents/fit_scoring.py`: the transparent `ScoreBreakdown`
  (capability_fit 30 / mandatory_requirement_fit 25 / eligibility_fit 15 /
  delivery_feasibility 10 / strategic_relevance 10 / information_confidence
  10). Commercial terms and evaluation-weight criteria (contract duration,
  price weighting, ...) are deliberately excluded from capability matching —
  an early test run showed these being scored as false "capability gaps",
  which is wrong: a price-weighting criterion isn't a thing HPE has or lacks.
  Delivery feasibility is computed from days-to-deadline; strategic relevance
  from keyword overlap between the tender and HPE's capability list;
  information confidence from the share of matches that aren't UNKNOWN.
- `src/agents/briefing.py`: assembles the final `QualificationBriefing`.
  Recommendation logic: any confirmed NO_MATCH mandatory requirement -> NO-GO
  regardless of score; any UNKNOWN mandatory requirement caps the
  recommendation at MAYBE even with a high score (never say GO on an
  unresolved mandatory item); otherwise score >= 70 -> GO, >= 45 -> MAYBE, else
  NO-GO. Confirmed NO_MATCH items and a sub-14-day deadline are surfaced as
  `RiskFlag`s.
- `src/agents/qualification.py` (`HPEQualificationAgent`): composes the three
  above into the single named interface the brief asks for.
- Verified manually across all 4 sample tenders: 3 realistic tenders all land
  on **MAYBE** (honestly capped — the default HPE profile ships with zero
  certifications/references, so cert/reference mandatory items are always
  UNKNOWN until someone adds sourced entries to `data/hpe_profile.json`); the
  office-furniture tender correctly lands on **NO-GO** (a confirmed capability
  mismatch). This is the intended behavior, not a limitation to fix — it's the
  anti-hallucination rule (8) working as designed, and it's a good live demo
  moment: edit `data/hpe_profile.json` to add a sourced certification/reference
  and re-run to watch the recommendation improve.
- Tests: `tests/agents/test_matching.py`, `test_ingestion.py`,
  `test_eligibility_gate.py`, `test_fit_scoring.py`, `test_briefing.py`,
  `test_qualification.py`. `ruff check src tests` clean. **49/49 tests
  passing** (full suite, all phases).

## Phase 4 — Agentic workflow

- `src/agents/search.py` (`TenderSearchTool`) and `src/agents/retrieval.py`
  (`DocumentRetrievalTool`): thin named wrappers over the Phase 2 adapters.
- `src/agents/workflow.py` (`WorkflowOrchestrator`): `search -> select ->
  retrieve -> extract -> qualify`, as plain class/function composition — no
  orchestration framework, since none (NeMo Agent Toolkit / AIQ Blueprint /
  NemoClaw/Hermes / MCP) is reachable from this environment (Phase 0).
  Adopting one later only means changing this one file — `qualify_tender`,
  `extract_requirements`, and the tool interfaces are already framework-
  agnostic. `run(query)` auto-selects the top search result;
  `analyze_tender(tender)` lets a caller (the UI) analyze a specific
  already-selected tender, which is what "tender selection" as a distinct
  workflow step needs.
- `src/agents/feedback.py` (`record_feedback`): the human-approval / feedback-
  recording step — attaches a `HumanReview` to the briefing and appends it to
  `data/feedback_log.json` (gitignored runtime state).
- Tests: `tests/agents/test_workflow.py`, `test_feedback.py`. **All passing.**

## Phase 5 — User interface

- `app.py` (Streamlit, root-level): query input -> search results table -> per-
  tender "Analyze" button -> full briefing view (recommendation badge, 6-
  dimension score breakdown with its explanation, mandatory requirements with
  citations, capability matches with MATCH/PARTIAL_MATCH/UNKNOWN/NO_MATCH
  icons, gaps, unknowns, risks, next actions, citations list) -> human review
  (Approve / Reject / Request more research, with reviewer/notes) ->
  `record_feedback` -> downloadable briefing JSON. The header shows which
  search/document adapter is actually active, so it's never ambiguous that
  this is the local fallback.
- `.streamlit/config.toml`: pins `server.port = 8507` so `streamlit run app.py`
  alone uses the required port without needing to remember a flag; also turns
  off Streamlit's usage-stats phone-home.
- `pyproject.toml`: added `streamlit>=1.60` as a runtime dependency.
- Verified: `streamlit run app.py` starts, listens on `:8507` (confirmed via
  `ss -ltn`), and `curl localhost:8507` returns HTTP 200 with no exceptions in
  the server log. **Browser-level interactive testing (clicking Search/
  Analyze/Approve) was not possible in this session** — the Claude in Chrome
  extension isn't connected here, and no other browser-automation tool was
  available. Everything the UI calls (`WorkflowOrchestrator.search`,
  `.analyze_tender`, `record_feedback`) is the same code exercised by the CLI
  smoke tests and the 49-test suite, so the business logic behind each button
  is verified even though the click-through itself isn't. Recommend a manual
  click-through pass (see README "Run the demo") before presenting.

## Phase 6 — Demo hardening

- Full suite re-run after all phases: **`pytest` — 49/49 passing**;
  **`ruff check src tests` — clean**.
- Scenarios explicitly covered by tests (not just the happy path):
  - **Missing/no documents**: `test_ingestion.py::test_extract_requirements_no_documents_reports_unknowns`,
    `test_document_retrieval.py::test_local_document_adapter_missing_tender_raises`.
  - **Unknown requirements** (profile has no data for a dimension):
    `test_matching.py` — certifications/references/insurance/legal-registration
    all resolve UNKNOWN, never NO_MATCH, when the profile lacks the data.
  - **Failed mandatory requirement -> forced NO-GO**:
    `test_briefing.py::test_recommendation_no_go_on_confirmed_hard_failure_regardless_of_score`,
    `test_workflow.py::test_workflow_analyze_specific_tender_is_no_go` (the
    office-furniture sample tender, end-to-end).
  - **Local fallback with zero external API keys/network**: this is simply
    every test in the suite — `SimapAdapter`/`TavilyAdapter` are proven
    unavailable in this environment (`test_tender_search.py`), and
    `WorkflowOrchestrator()` with no special configuration already resolves to
    the local sample adapters (`get_search_adapter().name == "local_sample"`).
    No `.env`, no API key, no network call is required to run the full demo.
  - **Tight deadline -> feasibility penalty + risk flag**: `test_fit_scoring.py`
    delivery-feasibility tests; `cybersec-managed-2026`'s 11-day window
    surfaces a high-severity risk in the generated briefing (verified
    manually).
- README rewritten with exact run instructions (venv-or-user-install per
  Phase 0's environment constraint, CLI usage, `streamlit run app.py`) and a
  scripted demo scenario.
- Manual end-to-end check across all 4 sample tenders (`python -m src.pipeline
  analyze <id> --as-of 2026-09-18`): 3 relevant tenders -> MAYBE (correctly
  capped by UNKNOWN certifications/references — the default HPE profile is
  intentionally empty on those, per rule 8); the irrelevant office-furniture
  tender -> NO-GO (confirmed capability mismatch). This spread demonstrates
  the anti-hallucination design working as intended, not a gap to fix before
  presenting.

### Known limitations to disclose in the demo

- Matching is deterministic keyword-overlap, not an LLM — it will miss
  paraphrases a human (or an LLM-based matcher) would catch. The seam
  (`match_requirement` in `src/agents/matching.py`) is where an LLM matcher
  would slot in once NeMo Agent Toolkit / an LLM API key is actually available
  in this environment.
- No mandatory-requirements-only tender in the sample set reaches GO by
  default, because the shipped HPE profile has zero sourced
  certifications/references (by design — never fabricate). Adding one real,
  cited certification or reference to `data/hpe_profile.json` and re-running
  is the intended "unlock a stronger recommendation" demo moment.
- SIMAP/Tavily/NeMo Agent Toolkit/AIQ Blueprint/NemoClaw/Hermes are all
  unreachable from this environment (Phase 0) — every "live" data path in this
  MVP is the local sample fallback. The adapter seams exist so a real
  integration is a contained, additive change, not a rewrite.
- Browser-level UI click-through wasn't performed this session (no
  Chrome-extension connection available) — see Phase 5.

## Phase 7 — UI redesign & English localization

Scope: `app.py` only — no agent, schema, adapter, or test changes (per this
phase's explicit constraints). `python -m pytest -q` **50/50 passing**,
unchanged before/after, confirming no business logic was touched.

- **Language decision.** The local sample fixtures
  (`data/sample_tenders.json`, `data/sample_tenders/*/*.txt`) are genuine
  French-language procurement text — SIMAP is a French/German/Italian Swiss
  platform — and `src/agents/ingestion.py`'s deterministic parser reads French
  section headers (`EXIGENCES OBLIGATOIRES:`, `CRITERES ELIGIBILITE:`, ...)
  while `src/agents/matching.py` keys off French legal/insurance/reference
  hint words. `tests/agents/test_workflow.py::test_workflow_analyze_specific_tender_is_no_go`
  also searches on the French query `"mobilier de bureau"`. Translating the
  fixture files themselves would silently change parsing/matching behavior and
  break that test — out of scope for a UI-only pass. Instead, **all data stays
  in French** (accurate source citations) and `app.py` presents an English
  translation alongside every piece of source-derived text via a static
  `FR_EN_GLOSS` lookup table covering all 4 tender titles/scopes and all ~35
  distinct requirement/risk strings across the 4 sample tenders (verified
  exhaustive by a coverage script during this session — the only unglossed
  strings are language-neutral certification codes like `ISO/IEC 27001` and
  `SOC 2 Type II`, correctly left as-is). Every translated item still shows
  its original French text in a caption/expander directly underneath, so the
  citation trail stays accurate per rule 8. All app-generated scaffolding text
  (labels, buttons, status messages, next actions) was already in English in
  the agent layer and needed no changes.
- **Single-page dashboard redesign.** Rebuilt `app.py` around: a wide-layout
  header (title + subtitle) and compact search bar always visible in the
  first viewport; a tender-card list with an inline "Analyze" action per
  card; a persistent "selected tender" panel once a briefing exists (falls
  back to the most-recently-analyzed tender if none is explicitly re-picked)
  showing a large colored GO/MAYBE/NO-GO badge, a large 0-100 score with a
  progress bar, a colored confidence chip, deadline, buyer/location, a KPI
  row (mandatory reqs / confirmed gaps / unknowns / days-to-deadline), and a
  synthesized short executive summary built from structured fields (not the
  raw agent `executive_summary` string, which can embed French text when it
  quotes a confirmed gap/unknown — that raw string is still shown verbatim,
  clearly labeled, in an "agent-generated rationale" expander for full
  traceability). The detailed briefing is organized into 4 tabs — Overview,
  Requirements & Matches, Risks & Next Actions, Sources & Human Review — each
  using two-column layouts, colored risk/action cards, and MATCH/PARTIAL/
  UNKNOWN/GAP icons instead of long paragraphs. Custom CSS
  (`CUSTOM_CSS` in `app.py`) styles badges, KPI cards, and risk/action cards.
  Technical adapter status (which search/document adapter is live) moved out
  of the top banner into a collapsed footer expander, per this phase's
  instruction to keep it from dominating the interface while still disclosing
  it.
- **Actions preserved:** Search, Analyze, Approve, Reject, Request more
  research, Download briefing JSON — all still call the exact same
  `WorkflowOrchestrator`/`record_feedback` functions as before; only their
  layout/placement changed (the four review actions moved into the "Sources &
  Human Review" tab).
- **Verification this session:**
  - `python -m pytest -q` → 50/50 passing (baseline was 50/50 before any
    change — confirms zero business-logic regressions).
  - `python -m streamlit run app.py --server.port 8507 --server.address
    0.0.0.0` → boots cleanly, `curl localhost:8507` → HTTP 200, no exceptions
    in the server log.
  - Unlike Phase 5, this session **did** exercise the UI click-through, using
    Streamlit's own `streamlit.testing.v1.AppTest` harness (no browser
    needed): scripted runs of Search → Analyze → each tab rendering → Approve
    → Reject → Request more research → Download-button presence, across both
    a MAYBE tender (cloud-infra) and the NO-GO tender (office-furniture, via
    the French query `"mobilier de bureau"`), asserting `at.exception is
    None` at every step and spot-checking rendered markdown/caption text for
    the expected English translations. All flows passed with no exceptions.

## Phase 8 — HPE enterprise visual re-skin

Scope: `app.py` and `.streamlit/config.toml` only — no agent, schema,
adapter, pipeline, or test changes. `python -m pytest -q` **50/50 passing**,
unchanged before/after.

- **Palette & theme.** Added a `[theme]` block to `.streamlit/config.toml`
  (light background `#F5F7F9`, navy text `#1D2739`, HPE green `#01A982` as
  the primary/button color) and replaced the previous ad-hoc CSS colors in
  `app.py` with a fixed enterprise palette: HPE green (GO / primary
  actions), navy (body text), blue `#0070AD` (informational accents), amber
  `#F5A623` (MAYBE / warnings / unknowns), red `#D64545` (NO-GO / confirmed
  gaps only), border `#D9E1E8`. Border-radius capped at 8px everywhere
  (badges, cards, score bar) — no pill-shaped controls.
- **Header.** Replaced the large `st.title` + clipboard emoji with a compact
  inline header: small square "HPE" green logo mark + "HPE Tender
  Intelligence" (normal-weight heading, not a huge title) + "Public tender
  qualification workspace" subtitle. All decorative emoji removed from the
  main UI (search icon, star, checkmark/warning emoji, flag emoji, etc.);
  status indicators now use plain symbols (✓ / ~ / ? / ✕) inside colored
  badges instead of colorful emoji.
- **System status.** Renamed the adapter-status footer expander to "System
  status" and moved it to a collapsed expander directly under the header
  (was a footer expander before) so fallback/adapter details never appear
  prominently in the hero area, per this phase's instruction.
- **Tender grid.** Replaced the single-column bordered-row list with a true
  3-column card grid (`st.columns(3)`, wrapping every 3 tenders). Each
  compact card shows title, buyer/location, deadline, source, and an
  Analyze/Analyzed button; the selected tender's card gets a green 2px
  border + light green tint instead of a star glyph.
- **Selected tender dashboard.** Kept title/buyer/location/deadline,
  recommendation badge, score, confidence, and KPI row (mandatory reqs,
  confirmed gaps, unknowns, days-to-deadline) all above the tabs so they're
  visible without scrolling. The recommendation badge and score bar now use
  solid GO=green / MAYBE=amber / NO-GO=red coloring (previously a fixed
  green-ish progress bar regardless of recommendation). KPI values recolor
  contextually (gaps red if >0, unknowns amber if >0, days-to-deadline
  red/amber as the deadline approaches).
- **Tabs.** Same 4 tabs (Overview, Requirements & Matches, Risks & Next
  Actions, Sources & Human Review) with tighter row-based layouts replacing
  the previous bordered-container-per-item style; original French source
  text for individual requirements/matches moved into small expanders
  ("Original source text (FR)") rather than always-visible captions, to cut
  vertical whitespace per this phase's "avoid long paragraphs, use
  expanders" instruction.
- **Human review** panel (reviewer name, notes, Approve/Reject/Request more
  research/Download JSON) unchanged in position (Sources & Human Review tab)
  and function — still calls the same `record_feedback` / `download_button`
  code exactly as before.
- **Actions preserved:** Search, Analyze, Approve, Reject, Request more
  research, Download briefing JSON all call the identical
  `WorkflowOrchestrator` / `record_feedback` functions; only presentation
  changed.
- **Verification this session:**
  - `python -m pytest -q` → 50/50 passing.
  - `python -m streamlit run app.py --server.port 8507 --server.address
    0.0.0.0` → boots cleanly, HTTP 200, no errors in the server log.
  - `streamlit.testing.v1.AppTest` scripted run: Search → Analyze → tab
    rendering → Approve, asserting `at.exception is None` at every step;
    confirmed GO/MAYBE/NO-GO badge text renders, all 4 tabs present, and all
    human-review buttons plus the JSON download button are present and
    functional.

## Phase 9 — Header fix, dialog-based human review, feedback animations

Scope: `app.py` only — no agent, schema, adapter, pipeline, or test changes.
`python -m pytest -q` **50/50 passing**, unchanged before/after.

- **Header clipping fix.** `.block-container` `padding-top` was `1.1rem`,
  less than Streamlit's own fixed top header bar height, so the custom "HPE
  Tender Intelligence" header rendered partly underneath it. Raised to
  `3rem` so the full brand header clears Streamlit's chrome. Header markup
  changed to the requested `HPE | Tender Intelligence` mark (green "HPE"
  tag + thin divider + "Tender Intelligence" title) with the "Public tender
  qualification workspace" subtitle unchanged underneath; still no remote
  logo image and no emoji.
- **Human review moved out of the Sources tab** into a directly accessible
  **Review decision** button placed next to the selected tender's score/
  confidence/deadline (right column of the two-column header — see below),
  so it's visible without opening any tab. Clicking it opens `st.dialog`
  (Streamlit 1.64, confirmed available) containing reviewer name, notes,
  Approve / Reject / Request more research, and Download briefing JSON —
  exactly the same `record_feedback(...)` / `download_button(...)` calls as
  before, now shared via `render_review_form()`. If `st.dialog` were
  unavailable (`HAS_DIALOG = hasattr(st, "dialog")`), the code falls back to
  an always-visible `st.expander("Review decision", expanded=True)` calling
  the same form function — this fallback path is what was actually
  exercised end-to-end in `AppTest` (see Verification below), since
  `AppTest` does not support asserting session-state mutations made inside
  an `st.dialog` fragment (confirmed by reproducing the same failure against
  Streamlit's own canonical `st.dialog` example app, unrelated to this
  code).
- **Review state persisted in `st.session_state.reviews[tender.id]`**
  (`status`, `reviewer`, `notes`, `timestamp`), scoped per tender so
  multiple analyzed tenders keep independent review state across reruns. A
  colored status chip ("Pending review" / "Approved" / "Rejected" / "More
  research requested") renders next to the Review decision button at all
  times, independent of the transient confirmation banner.
- **Professional feedback banners.** A one-shot colored banner (green
  check ✓ / red cross ✕ / amber refresh ↻, left-accent-bordered, navy text)
  renders directly under the selected-tender header immediately after
  Approve/Reject/Request-more-research, using a lightweight CSS
  `@keyframes` fade+slide-in (`hpeFadeSlideIn`, 0.35s) — no JS, no
  balloons/confetti. It's stored once in `st.session_state.pending_banner`
  and popped (deleted) the first time it's rendered, so it behaves like a
  toast without needing a JS timer.
- **Two-column selected-tender header**, per this phase's spec: left =
  tender identity + recommendation badge (title, buyer/location, GO/MAYBE/
  NO-GO badge); right = score, confidence, deadline, and the Review
  decision action + status chip. KPI row and the 4 tabs (Overview,
  Requirements & Matches, Risks & Next Actions, **Sources** — renamed from
  "Sources & Human Review" now that review lives in the dialog) are
  unchanged below.
- **Compact score breakdown.** Replaced the 6× `st.columns` + `st.write` +
  `st.caption` + `st.progress` block (each row costing Streamlit's default
  paragraph margins) with a single `st.markdown` call rendering all 6
  dimensions as tight flex rows (`dim_row()` helper) — same values, same
  6-dimension breakdown, visibly less vertical whitespace.
- **Remaining French-label cleanup.** All "(FR)" abbreviations became
  "(French)" and were reworded to "Original source title (French)" /
  "Original source text (French)" per this phase's instruction; original
  French tender/requirement text itself is untouched (still the accurate
  citation).
- **Verification this session:**
  - `python -m pytest -q` → 50/50 passing.
  - `python -m streamlit run app.py --server.port 8507 --server.address
    0.0.0.0` → boots cleanly, HTTP 200, no errors in the server log.
  - `streamlit.testing.v1.AppTest` against the real `app.py`: Search →
    Analyze → click **Review decision** → dialog opens showing Approve /
    Reject / Request more research / Download briefing JSON with zero
    exceptions (confirms the dialog wiring and button layout are correct).
  - Because `AppTest` can't observe session-state changes made inside an
    `st.dialog` fragment (reproduced with Streamlit's own documented
    `st.dialog` vote-app example — identical limitation), the
    state-mutation logic (`_submit_review` / `render_review_form`, shared
    verbatim by both the dialog and the fallback path) was additionally
    verified end-to-end against a scratch copy of `app.py` with
    `HAS_DIALOG` forced to `False`: Approve → status chip "Approved" +
    green banner "Qualification briefing approved" + `reviews` state
    updated + download button present; Reject → red banner "Qualification
    briefing rejected" + chip "Rejected"; Request more research → amber
    banner "Additional research requested" + chip "More research
    requested"; banner confirmed transient (gone after the next rerun)
    while the status chip persists. The scratch copy was deleted after the
    check; `app.py` itself was not modified for this test.

## Phase 10 — Prominent, sticky human-review call-to-action

Scope: `app.py` only — no agent, schema, adapter, pipeline, or test changes.
`python -m pytest -q` **50/50 passing**, unchanged before/after. Targeted fix
only: no broader redesign.

- **Renamed the trigger** from "Review decision" to the exact requested
  label **"Review & decide"** everywhere (header button, dialog title,
  fallback expander title, Sources-tab pointer text). Dialog width bumped
  to `"medium"` and the three decision buttons in `render_review_form`
  changed from a cramped 3-column row to full-width stacked buttons, so
  "Request more research" is never truncated or squeezed.
- **New full-width review status bar** (`render_review_status_bar`),
  placed directly below the tender identity/recommendation/score header and
  above the KPI row and tabs — i.e. before any tab content, so it's part of
  the first visible selected-tender area together with title, buyer +
  deadline (now on one line), recommendation, score, and confidence:
  - **No decision yet:** an amber-accented card — "Human review required" /
    "The AI recommendation is ready for approval." (amber left-border, navy
    text; explicitly not a red alert style, per this phase's instruction).
  - **Decision recorded:** the same card switches to a persistent
    green/red/amber status — "Approved" / "Rejected" / "More research
    requested" — with a one-line confirmation message ("This qualification
    briefing has been approved.", etc.), plus reviewer name and decision
    timestamp when available, e.g. `(by Jane Doe · 2026-09-18 17:27 UTC)`.
    This persists across reruns (backed by the existing
    `st.session_state.reviews[tender.id]` dict) and is separate from the
    short-lived fade-in confirmation banner from Phase 9, which still fires
    once immediately after each action.
  - **Prominent "Review & decide" button** (`type="primary"`) sits next to
    the status text in the same bar and opens the same `st.dialog` (or the
    same expander fallback) as before.
  - **Sticky positioning:** the bar is wrapped in `st.container(key=
    "review_action_bar")`, which Streamlit renders as a real DOM node with
    class `st-key-review_action_bar` — targeted with `position: sticky; top:
    0.4rem;` CSS so it stays visible near the top while scrolling through
    the Overview / Requirements / Risks / Sources tab content below it. This
    is a best-effort, framework-supported CSS technique (not JS); if a given
    browser/theme doesn't honor the sticky behavior perfectly, the bar still
    satisfies the instruction's fallback — it's placed directly below the
    selected-tender header, before the tabs, at all times.
- **Removed the now-superseded small `review-chip`/`review-meta` styling**
  and the `review_status_chip()` helper (folded into the new status bar,
  which shows strictly more information — status, message, reviewer,
  timestamp — in one place instead of two).
- **Verification this session:**
  - `python -m pytest -q` → 50/50 passing.
  - `python -m streamlit run app.py --server.port 8507 --server.address
    0.0.0.0` → boots cleanly, HTTP 200, no errors in the server log.
  - `streamlit.testing.v1.AppTest` against the real `app.py`: confirmed the
    "Human review required" / "The AI recommendation is ready for approval."
    card renders before any decision, and clicking **Review & decide**
    opens the dialog with Approve / Reject / Request more research, all
    with zero exceptions.
  - As in Phase 9, `AppTest` cannot observe session-state mutations made
    *inside* an `st.dialog` fragment, so the full decision flow (shared
    `_submit_review` / `render_review_form` / `render_review_status_bar`
    logic, identical for the dialog and fallback paths) was additionally
    verified against a temporary scratch copy of `app.py` with `HAS_DIALOG`
    forced to `False`: Approve/Reject/Request-more-research each correctly
    switch the status bar to the matching persistent green/red/amber card
    with confirmation message + timestamp, fire the matching one-shot fade
    banner, leave the banner cleared but the status card intact after the
    next interaction, and keep the JSON download button working throughout.
    The scratch copy was deleted after the check; `app.py` itself was not
    modified for this test.

## Phase 11 — MCP stdio server for Hermes/NemoClaw

Scope: new `src/mcp_server.py` + `tests/test_mcp_server.py` only. No changes
to `app.py` (frontend), or to any scoring/matching/extraction/briefing logic
in `src/agents/*` — this phase is a thin adapter layer that calls straight
into the existing, already-tested pipeline.

- **Why:** the brief's workflow (search → extract → match → qualify →
  briefing) was only reachable via the CLI (`src/pipeline.py`) or the
  Streamlit UI (`app.py`). Hermes/NemoClaw drives work through MCP tools, so
  the same pipeline needed an MCP stdio interface — the same integration
  pattern already documented for the SIMAP MCP server in
  `integrations/simap/README.md` ("Native Hermes stdio MCP"), but a local
  Python command instead of the Node one.
- **Dependency:** added `mcp>=1.9,<2` to `pyproject.toml`. Network access to
  PyPI was available this session (unlike SIMAP/Tavily, which are unreachable
  per Phase 0). Pinned below 2.0 deliberately: `mcp` 2.x renamed the
  `FastMCP` class to `MCPServer` and changed several other APIs; `1.30.0`
  (the latest 1.x, installed and tested here) keeps the well-documented
  `FastMCP` decorator API most third-party MCP hosts are built against.
- **Six tools, one thin wrapper each, over the existing modules:**
  - `search_tenders(query)` → `WorkflowOrchestrator.search` →
    `TenderSearchTool` (`src/agents/search.py` /
    `src/adapters/tender_search.py`), which already resolves to
    `data/sample_tenders.json` since SIMAP/Tavily remain unreachable
    (Phase 0). Every result keeps its real `Tender.source`
    (`"local_sample"`) — never rewritten to imply a live SIMAP fetch.
  - `get_tender(tender_id)` → looks up the id in the same search index.
  - `extract_requirements(tender_id)` → `DocumentRetrievalTool` (local
    `data/sample_tenders/<id>/*.txt`) + `src.agents.ingestion.
    extract_requirements`, unmodified.
  - `match_hpe_capabilities(tender_id)` → `src.agents.matching.match_all`
    against `data/hpe_profile.json`, unmodified — deterministic
    keyword-overlap matcher, not reimplemented here.
  - `qualify_tender(tender_id)` → `WorkflowOrchestrator.analyze_tender`,
    which composes `src.agents.qualification.qualify_tender`
    (eligibility_gate + fit_scoring + briefing), all unmodified — **no
    scoring rule was rewritten for this phase**.
  - `create_briefing(tender_id)` → runs the same pipeline as
    `qualify_tender` and additionally persists the result to
    `data/briefings/<tender_id>.json` (mirrors `python -m src.pipeline
    analyze <id> --out ...`), so a caller gets a durable artifact back, not
    only an in-memory result. `data/briefings/` is git-ignored (runtime
    output, not a fixture), matching the existing `data/feedback_log.json`
    pattern.
  - Every tool returns one structured JSON envelope: `status` (`"ok"` /
    `"error"`), tool-specific payload, `sources`, `citations`, `notes`
    (explicit provenance, e.g. *"Sourced from local sample fixtures under
    data/ ... — NOT a live SIMAP connection."*), and `unknowns`. An unknown
    `tender_id` returns `status: "error"` with the relevant field set to
    `null`/empty rather than a guess; certifications/references the HPE
    profile doesn't carry surface as `"unknown"` matches (never fabricated
    as `"match"`), per the existing `matching.py` contract.
- **Tests (`tests/test_mcp_server.py`, 13 new, all passing):** direct calls
  to each of the six tool functions (still plain, directly callable
  functions under `@mcp.tool()`), checking the sources/citations/unknowns
  contract, the local-sample provenance note, UNKNOWN-not-fabricated
  certification matching, unknown-tender-id error handling, and
  `create_briefing`'s file persistence — plus one protocol-level test that
  drives the real `FastMCP` server over an in-memory MCP `ClientSession`
  (`mcp.shared.memory.create_connected_server_and_client_session`),
  confirming `list_tools` reports all six tools and `call_tool` returns
  valid MCP responses, not just that the Python functions work.
- **Verification this session:**
  - `python -m pytest -q` → **63/63 passing** (50 existing + 13 new).
  - `ruff check src/mcp_server.py tests/test_mcp_server.py` → clean.
  - Spawned the server as a real subprocess over stdio (`mcp.client.stdio.
    stdio_client` + `StdioServerParameters(command="python3", args=["-m",
    "src.mcp_server"], cwd=".")`), completed the MCP `initialize` handshake,
    called `list_tools` (all six returned), `search_tenders` (`"cloud
    infrastructure"` → 3 local-sample matches), and `qualify_tender`
    (`cloud-infra-2026` → `MAYBE`, score 61.1) — end-to-end, real subprocess,
    real JSON-RPC-over-stdio, not an in-process shortcut.

### Running the server

From the repo root, with the project's venv active (`mcp>=1.9,<2` is now a
declared dependency — `pip install -e .` or `pip install -e ".[dev]"` pulls
it in):

```bash
python -m src.mcp_server
```

This starts the MCP stdio server and blocks, speaking JSON-RPC over
stdin/stdout — it's meant to be launched by an MCP client (Hermes/NemoClaw),
not run interactively. `python -c "import src.mcp_server"` or the pytest
suite above are the way to sanity-check it without a client.

**Registering with Hermes** (native stdio MCP registration, the same pattern
already used for the SIMAP MCP server — see
`integrations/simap/README.md` and `hermes mcp add --help` — but a local
Python command instead of the Node one):

```yaml
mcp_servers:
  hpe-tender-qualification:
    command: python3
    args: ["-m", "src.mcp_server"]
    cwd: /path/to/this/repo    # so the `src` package and data/ paths resolve
    connect_timeout: 10
```

Merge this into the target Hermes profile (e.g.
`/sandbox/.hermes/config.yaml`) without replacing unrelated settings, the
same way `integrations/simap/hermes-config.example.yaml` is merged. Unlike
the SIMAP server, this one needs no proxy/CA settings and no `npm ci` install
step — it's a pure-Python stdio server reading only local repo files
(`data/sample_tenders.json`, `data/sample_tenders/*/*.txt`,
`data/hpe_profile.json`); it makes no network calls itself. Once registered,
ask Hermes to discover tools on the `hpe-tender-qualification` server; it
should report the six tools listed above.

## Phase 12 — Root-caused the SIMAP MCP "Network or timeout error"

Scope: `integrations/simap/README.md` and `integrations/simap/hermes-config.example.yaml`
only (docs + example config). No `src/`, `app.py`, or test changes — this
was a diagnosis of the third-party `@digilac/simap-mcp` npm server and the
Hermes sandbox environment around it, not a bug in this repo's Python code.
`python -m pytest -q` → 63/63 passing, unchanged.

- **Method:** `npm pack @digilac/simap-mcp@1.4.0` into `/tmp` only (never
  installed into this repo), inspected the compiled `dist/` output, and
  reproduced the failure signature locally with real `fetch()` calls (no
  fabricated endpoints, no local-data substitution for SIMAP).
- **Finding:** `list_cantons` calls the real, live `GET
  https://www.simap.ch/api/cantons/v1` (confirmed HTTP 200 with the
  26-canton body) — not an endpoint/policy bug. "Network or timeout error"
  is a generic catch-all in the package's own `dist/utils/errors.js`: it
  only fires when `fetch()` itself throws (DNS/connection/TLS/timeout)
  *before* any HTTP response is received; a real 403/404/405 response takes
  a different code path and produces a visibly different message. Confirmed
  by reproduction: pointing `HTTP_PROXY`/`HTTPS_PROXY` at an unreachable
  proxy produces the exact same `TypeError: fetch failed` → "Network or
  timeout error" signature observed in Hermes. Conclusion: the failure is in
  the Hermes-sandbox proxy/TLS/policy environment around the subprocess, not
  in this repo, in `@digilac/simap-mcp`, or in the SIMAP API — see the new
  "Troubleshooting" section in `integrations/simap/README.md` for the full
  evidence chain and the ranked list of candidate causes (proxy
  address/reachability, missing/wrong CA bundle, the `policy add` step never
  having been run, or a reachability test done outside the subprocess's
  actual network namespace — the last one has a documented precedent in this
  repo, the 14 September incident in `docs/NEMOHERMES_SETUP.md`).
- **Repo fix applied:** added `SIMAP_MCP_DEBUG: "1"` to the example Hermes
  env block. It doesn't change connectivity, but the real underlying Node
  error (already logged unconditionally to this MCP server's stderr on every
  failure, independent of this flag) is otherwise the only way to
  distinguish those candidate causes — no further fix could be applied
  in-repo without sandbox-side evidence (this repo cannot reach
  `/sandbox/.hermes/`, and guessing proxy/CA values instead of reading the
  actual stderr would risk masking the real cause).

## Phase 13 — SIMAP MCP preflight diagnostic + confirmed active-path fix

Scope: new `integrations/simap/preflight.mjs`, plus
`integrations/simap/hermes-config.example.yaml` and
`integrations/simap/README.md` updates. No `src/`, `app.py`, or test
changes — still purely the `@digilac/simap-mcp` Node MCP server and its
Hermes launch config, unreachable-sandbox-proxy problem, not a bug in this
repo's Python code. `python -m pytest -q` → 63/63 passing, unchanged.

- **Confirmed-path fix:** the actual active Hermes command for `simap`
  (given directly in this task, not guessed) targets
  `/sandbox/.hermes/mcp/simap/simap-mcp/node_modules/@digilac/simap-mcp/dist/index.js`
  — one `simap-mcp/` segment deeper than `hermes-config.example.yaml`
  previously documented. Updated the example config to match the confirmed
  real path.
- **`preflight.mjs`:** a small, dependency-free Node wrapper Hermes now
  launches instead of `dist/index.js` directly (inserted as an extra `args`
  entry in `hermes-config.example.yaml`, ahead of the real entrypoint path,
  which becomes its `argv[2]`). It prints hostname, Node version, whether
  `--use-env-proxy`/`HTTP_PROXY`/`HTTPS_PROXY`/`NODE_USE_ENV_PROXY` reached
  the process (presence only — a proxy URL can carry embedded credentials),
  and whether `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE` are set and their target
  file exists/is readable (path shown, certificate content never is) — then
  hands off to the real server via a same-process dynamic `import()`, so MCP
  stdio behavior is byte-identical to invoking `dist/index.js` directly.
  Verified locally (`npm pack` into `/tmp`, not installed in this repo):
  diagnostics print correctly with no secret values, and control transfers
  cleanly into the real package's `server.js`.
- **Why this and not a direct fix:** the actual `HTTP_PROXY`/`HTTPS_PROXY`/
  `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE` values needed to fix connectivity
  can only be confirmed by reading this new stderr block from *inside* the
  real Hermes/OpenShell sandbox (`/sandbox/.hermes/`), which this repo's
  environment cannot reach. No value was invented or replaced — this phase
  makes the next diagnostic step immediate instead of guessed, per Phase 12.
- **Manual steps documented** in `integrations/simap/README.md` under
  "Applying the active configuration from the BREV-NVIDIA / NemoClaw
  dashboard (no CLI)", since `nemohermes`/`hermes` are not available in this
  project's VM terminal: upload `preflight.mjs`, edit the `simap` MCP
  server's Args in the Hermes MCP screen to insert it, leave `env` and
  `policy.yaml` untouched (same `/usr/local/bin/node` binary, same allowed
  path/method — no policy change needed), restart just that server, re-test.

## Phase 14 — Real SIMAP MCP adapter (`SimapAdapter`) + `research_mode`

Scope: `src/adapters/tender_search.py` (rewritten `SimapAdapter`),
`src/schemas/common.py` (`ResearchMode`), `src/schemas/tender.py`
(`Tender.research_mode`), new `tests/fixtures/fake_simap_mcp_server.py`, and
`tests/adapters/test_tender_search.py`. No `app.py`/frontend changes, no
`src/agents/workflow.py` or `src/pipeline.py` changes — neither construct
`Tender` directly or reference `SimapAdapter` by name, so nothing there
needed to change for the new field/adapter to take effect.
`python -m pytest -q` → **71/71 passing** (63 existing + 8 net new),
`ruff check` clean.

- **`SimapAdapter` is now a real MCP client**, not a hardcoded
  `return False` stub. It spawns
  `<node_command> --use-env-proxy <entrypoint>` — the exact command shape
  `integrations/simap/hermes-config.example.yaml` documents — and speaks
  real MCP stdio to it via the `mcp` package (already pinned since Phase
  11). `entrypoint`/`node_command` come from `SIMAP_MCP_ENTRYPOINT`/
  `SIMAP_MCP_NODE_COMMAND` env vars and are **unset by default**, so
  `available` stays honestly `False` in this dev/CI environment — same
  externally-visible behavior as before (`WorkflowOrchestrator` still
  resolves to `LocalSampleSearchAdapter` here), but the code path is now
  real, not a placeholder.
- **No Hermes endpoint invented.** Per the SIMAP/NemoHermes procedure
  analysis earlier this session, no programmatic Hermes endpoint is
  documented anywhere in this repo. `SimapAdapter` therefore targets the
  underlying `@digilac/simap-mcp` stdio server directly — the same package
  Hermes launches, launched as this app's *own*, independent subprocess —
  never Hermes itself. Documented explicitly in the module docstring and
  `README.md`: Hermes's chat UI and this app are two separate consumers of
  that package, not one calling the other.
- **Response parsing, not invented:** `search_tenders` returns Markdown
  (confirmed by reading `dist/tools/search-tenders.js` — it returns
  `formatProject()`'s formatted string directly, no structured JSON
  content). `_parse_search_tenders_markdown()` parses the exact
  `- **Label:** value` template from `dist/utils/formatting.js` (inspected
  via `npm pack` into `/tmp`, never installed here). Fields the search
  results don't carry (submission deadline, scope) are left `None` — never
  guessed; a block missing a `Project ID` line is skipped rather than
  fabricating one.
- **A real, non-obvious bug caught before it shipped:** the `mcp` SDK's
  stdio client only forwards a minimal safe env subset
  (`HOME`/`LOGNAME`/`PATH`/`SHELL`/`TERM`/`USER`) to the spawned process
  when `env=None` (`mcp.client.stdio.get_default_environment()`) —
  `HTTP_PROXY`/`HTTPS_PROXY`/`NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE` would
  silently **not** reach the subprocess otherwise, even with everything else
  configured correctly. `SimapAdapter` now explicitly forwards the full
  parent process env by default.
- **`ResearchMode` (`simap_mcp` / `local_fallback`)** added to
  `src/schemas/common.py` and as `Tender.research_mode` (default
  `local_fallback`, so every existing fixture/JSON file needed zero
  changes). Set to `simap_mcp` only by `_parse_search_tenders_markdown()`
  on a real, successful call; `LocalSampleSearchAdapter` results keep the
  default.
- **Tests exercise the real MCP protocol, not a mock of `SimapAdapter`
  itself:** `tests/fixtures/fake_simap_mcp_server.py` is a real (Python)
  stdio MCP server exposing `search_tenders`, returning canned text built
  from the literal upstream template. `SimapAdapter`'s `node_command`/`args`
  constructor overrides (test-only — production never sets them) point it
  at `<python> -m tests.fixtures.fake_simap_mcp_server` instead of the real
  Node package, so tests genuinely spawn a subprocess, complete the MCP
  `initialize` handshake, call `search_tenders`, and parse a real tool
  response — no Node/npm/network dependency, fully deterministic.
  Separately verified once by hand this session against the *actual*
  `@digilac/simap-mcp@1.4.0` package unpacked via `npm pack` into `/tmp`
  (dependency install kept failing on a pre-existing, unrelated npm cache
  bug in this VM — `Cannot read properties of null (reading 'edgesOut')` —
  so the live network round-trip against `www.simap.ch` itself was not
  re-confirmed this session; the fake-server tests above are the ones that
  actually run in CI).
- **`README.md`** "Availability" section corrected: it previously said "no
  MCP client is wired in" for the search adapters, which stopped being true
  as of Phase 11 (`src/mcp_server.py`) and is now doubly stale — updated to
  describe the real adapter and restate, explicitly, that this still doesn't
  mean Streamlit/CLI call Hermes.

## Phase 15 — Automatic tender selection (`TenderSelectionAgent`)

Scope: new `src/agents/tender_selection.py`; additive changes to
`src/schemas/common.py` (`SelectionMode`), `src/schemas/briefing.py`
(`AlternativeTender`, 3 new `QualificationBriefing` fields + a
`selected_tender_id` computed field), `src/agents/qualification.py` and
`src/agents/briefing.py` (optional pass-through kwargs, `None` by default),
`src/agents/workflow.py` (`WorkflowOrchestrator.run` now auto-selects
instead of taking `results[0]`), `src/pipeline.py` (`run` subcommand prints
the selection + a new `--override` flag), and `app.py` (frontend — displays
the selection reason/alternatives and offers per-card override). No scoring
logic already covered elsewhere (HPE qualification `ScoreBreakdown`,
matching) was rewritten. `python -m pytest -q` → **87/87 passing** (71
existing + 16 new), `ruff check` clean (one pre-existing, untouched
`app.py` warning aside).

- **The transform requested:** `WorkflowOrchestrator.run()` used to just
  analyze `results[0]` — whatever the search adapter's own ranking put
  first. It now calls `tender_selection.rank_candidates()`, which scores
  every candidate on six transparent dimensions (20/20/20/20/10/10 = 100,
  mirroring `ScoreBreakdown`'s style): cloud-infrastructure / managed-
  services / cybersecurity keyword fit against the matching subset of
  `data/hpe_profile.json` capabilities (grouped by capability *name*, e.g.
  "hybrid cloud" → cloud infrastructure — never a separately invented
  keyword list), an overall HPE-capability-fit dimension (all capabilities),
  submission-deadline feasibility, and real document availability (an
  actual `DocumentRetrievalTool.retrieve_documents` call, whose result is
  kept and reused for the winner's extraction step — no re-fetch). No LLM
  call; reuses `src.agents.matching.significant_tokens`, the same tokenizer
  `eligibility_gate.py`/`fit_scoring.py` already use, so this is one more
  consumer of that shared primitive, not a second scoring implementation.
- **Honest neutrality, not fabrication:** an empty themed-capability subset
  (e.g. no "cybersecurity"-named capability in the profile) scores that
  dimension at a neutral half, mirroring `fit_scoring._dimension_score`'s
  existing convention — never a punitive 0 for something the profile simply
  doesn't say. A missing `submission_deadline` (always true for `SimapAdapter`
  search results, per Phase 14 — `search_tenders` never returns one) is
  neutral too, never guessed. Every dimension's contribution is recorded as
  a plain-English note, joined into `selection_reason`.
- **`selection_mode`** (`auto` / `human_override` / `direct`) — `direct` is
  the schema default, so `WorkflowOrchestrator.analyze_tender` (used by the
  CLI `analyze` command, and — until now — every `app.py` "Analyze" click)
  keeps behaving exactly as before, with zero code changes to that method.
  `selected_tender_id` is a Pydantic `computed_field` (`= tender.id`), not a
  stored field — impossible for it to drift from the tender it's actually
  describing.
- **Human override preserved and traceable:** `WorkflowOrchestrator.run`
  takes an optional `override_tender_id` — must be one of the same search's
  candidates (`ValueError` otherwise, never a silent fabricated match); the
  resulting briefing's `selection_reason` names *both* the overridden pick
  and what automatic selection would have chosen, with both relevance
  scores, so an override never erases the automatic recommendation from the
  record.
- **`app.py` changes (frontend, as this task explicitly asked for, unlike
  prior phases):** a Search click now also runs the automatic
  selection+analysis immediately (no extra click) and a new "Why this
  tender?" panel — expanded by default whenever `selection_mode != "direct"`
  — shows `selection_reason` and the 2-3 `alternatives` with their scores.
  Clicking "Analyze" on any other card now goes through the same
  `override_tender_id` path (`selection_mode="human_override"`) instead of
  the old direct `analyze_tender` call, so a manual pick is recorded as an
  explicit override rather than looking identical to an automatic one.
  Verified with `streamlit.testing.v1.AppTest` against the real `app.py`:
  Search → auto-selects and renders the panel with zero exceptions;
  clicking a different card's "Analyze" → re-renders as
  `selection_mode="human_override"` with a reason naming both candidates,
  zero exceptions.

## Phase 16 — Runtime fallback for TenderSearchTool + `source_type` display

Scope: `src/agents/search.py` (rewritten), `src/adapters/tender_search.py`
(`get_search_adapters()` added, `get_search_adapter()` kept), `src/schemas/tender.py`
(`Tender.source_type` computed field), `app.py` (source label only — "SIMAP"
instead of a mis-cased "Simap"/"Local Sample" string), plus new
`tests/agents/test_search.py`, `tests/test_app.py`,
`tests/fixtures/fake_simap_mcp_error_server.py`. `python -m pytest -q` →
**96/96 passing** (87 existing + 9 new), `ruff check` clean (same
pre-existing, untouched `app.py` warning as before).

- **The gap this closes:** `SimapAdapter` (a real MCP client — Phase 14) was
  already tried first by `get_search_adapter()`, but only as a *pre-flight*
  `.available` check at construction time — if it were configured and
  available yet failed *during* a specific call (network blip, proxy
  hiccup), the error propagated all the way up with no fallback, taking the
  whole search down even though the guaranteed local index was right there.
  `TenderSearchTool` now tries every candidate in priority order
  (`get_search_adapters()`) and falls back to the next one on
  `AdapterUnavailableError`, not only on `.available is False`. Verified
  against a fake MCP server that raises on every `search_tenders` call
  (`tests/fixtures/fake_simap_mcp_error_server.py`) — a real MCP `isError`
  result, not a fabricated timeout.
- **`Tender.source_type`** (`"simap"` / `"local_fallback"`) is a
  `computed_field` derived from the existing `research_mode` — deliberately
  not a third, separately-stored provenance field alongside `source` and
  `research_mode`; it's the exact two-value label `app.py` needed, computed
  from the signal that was already there.
- **`app.py`:** only `tender.source.value.replace("_", " ").title()`
  (→ "Simap"/"Local Sample") became `source_label(tender)`
  (→ "SIMAP"/"Local Sample", driven by `source_type`) — no other design
  change, per this task's constraint. In this environment,
  `SIMAP_MCP_ENTRYPOINT` is still unset (Phase 14), so `SimapAdapter` stays
  unavailable and the app correctly keeps showing "Local Sample" — verified
  with a real `AppTest` run asserting "SIMAP" never renders here, so the UI
  never claims a live SIMAP connection it doesn't have.
- **Endpoint re-verified, not assumed:** re-ran `npm pack
  @digilac/simap-mcp@1.4.0` into `/tmp` (sha256-matched against the files
  Phase 14's `SimapAdapter`/parser were already built from) before writing
  any code this phase — `GET https://www.simap.ch/api/publications/v2/project/project-search`,
  reformatted to Markdown by the MCP tool before it ever reaches Python (see
  Phase 14 for the full template). No endpoint, response shape, or tender
  was invented.

## Phase 17 — SIMAP MCP HTTP bridge (`src/simap_bridge.py` + `SimapBridgeAdapter`)

Scope: new `src/simap_bridge.py`, `src/adapters/simap_bridge_client.py`,
`deploy/simap-bridge/README.md`; `src/adapters/tender_search.py` (refactored
`SimapAdapter` to expose reusable async building blocks + registered the
bridge in `get_search_adapters()`); `src/schemas/tender.py` (`source_type`
now mirrors `research_mode`'s exact values, `simap_mcp`/`local_fallback`,
per this task's spec — simpler than Phase 16's separate `"simap"` mapping,
same underlying signal); `app.py` (label map key only); new
`tests/fixtures/fake_simap_mcp_server.py` additions (`list_cantons`,
`get_tender_details`), `tests/fixtures/fake_simap_mcp_error_server.py` reuse,
`tests/fixtures/run_bridge_server.py`, `tests/test_simap_bridge.py`,
`tests/adapters/test_simap_bridge_client.py`, `tests/agents/test_search.py`
additions. `python -m pytest -q` → **114/114 passing** (96 existing + 18
new), `ruff check` clean (same pre-existing `app.py` warning as always).

- **No pre-existing HTTP/MCP endpoint found.** Re-inspected
  `docs/NEMOHERMES_SETUP.md`, `integrations/simap/*`, `deploy/hermes-ingress/*`,
  `NVIDIA_AUDIT.md` before writing any code — the only documented HTTP
  surface is the Hermes **dashboard** ingress (chat UI, Basic Auth,
  WebSocket), never a tool-call API. Nothing was invented in its place —
  Phase 4 of this task's own instructions applied: build a minimal bridge.
- **The bridge is a thin relay, not a new SIMAP client.** It reuses
  `SimapAdapter.call_tool`/`asearch_raw` (refactored from private `_call_tool`
  to public, reusable methods) for 100% of the actual MCP transport — its
  three routes (`GET /health`, `POST /search_tenders`, `POST /get_tender`)
  just translate HTTP <-> those calls. `/get_tender` requires both
  `project_id` and `publication_id` (real UUIDs) because
  `get_tender_details`'s real Zod schema
  (`dist/tools/get-tender-details.js`) requires both — no simplified
  single-id shortcut was invented.
- **`SimapBridgeAdapter`** (`src/adapters/`) is the new primary candidate in
  `get_search_adapters()` (`simap_bridge -> simap -> tavily -> local_sample`)
  — the realistic path when Streamlit and the NemoClaw sandbox are separate
  environments (the direct-stdio `simap` only works co-located with the
  sandbox). Stdlib `urllib` only, no new dependency on the Streamlit side.
  Unconfigured by default (`SIMAP_BRIDGE_URL` unset here) — `available`
  performs a real `GET /health` call, never assumes.
- **Tests never claim to reach NemoClaw.** Every test runs the real bridge
  code (Starlette routing, or a real local HTTP socket via `uvicorn` in a
  background thread) against `tests/fixtures/fake_simap_mcp_server.py`
  (extended this phase with `list_cantons`/`get_tender_details`, built from
  the same real upstream templates as `search_tenders` already was) or its
  always-erroring sibling — every test file's docstring says explicitly
  that this proves the code, not a live deployment. New end-to-end test:
  `WorkflowOrchestrator.search()` through a real running bridge (fake-backed)
  down to `source_type` on the returned `Tender`s — objective 8's wiring,
  verified, not asserted.
- **`deploy/simap-bridge/README.md`** documents the transport (HTTP,
  wrapping the same real MCP stdio SimapAdapter already speaks), the
  (nonexistent-until-deployed) endpoint/port, the required environment
  (inside the NemoClaw sandbox, colocated with `simap-fixed`), and the
  deployment method (manual upload via the NemoClaw dashboard, no
  `nemohermes` CLI here) — and closes with an explicit "what this document
  does NOT claim" section: no step was run against the real sandbox this
  session, and this integration is not "live" until an operator with real
  sandbox access confirms `/health` returns `ok` from outside it.

## Phase 18 — Deployment bundle for the combined NemoClaw sandbox target

Scope: new `deploy/build_bundle.sh`; rewritten `deploy/simap-bridge/README.md`
for the new confirmed topology (`simap-fixed` + the bridge + Streamlit all
in the *same* sandbox, not separate environments as Phase 17 assumed). No
`src/`/`app.py`/schema changes this phase — `python -m pytest -q` →
**114/114 passing**, unchanged.

- **`deploy/build_bundle.sh`** produces a local tarball (`dist/tender-
  assistant-bundle.tar.gz`, gitignored) containing exactly: `app.py`,
  all of `src/` (bridge code included — it's not a separate tree),
  `data/hpe_profile.json` + `data/sample_tenders*` (explicitly *not*
  `data/feedback_log.json`/`data/briefings/` — gitignored runtime state from
  this machine, must not ship to a fresh deployment), `pyproject.toml`, and
  `deploy/simap-bridge/README.md`. No tests, no `.git`, no other docs.
  Verified this session: ran the script, extracted the resulting tarball
  into a clean temp directory, imported `app.py` and ran a real
  `WorkflowOrchestrator().search()` from there — worked, correctly fell
  back to `local_fallback` (no bridge running in that throwaway check).
- **README rewritten for one sandbox, not two environments.** Since
  Streamlit now runs *inside* the same NemoClaw sandbox as `simap-fixed`
  and the bridge (per this task's confirmed target topology), the old
  Phase-17 "Exposure to Streamlit's environment" section (which assumed a
  cross-environment forwarding decision) is gone — replaced with the exact
  fixed topology: bridge on `127.0.0.1:8135` (loopback only, never
  exposed), Streamlit on `0.0.0.0:8507` (the only port meant to be exposed
  externally). No port forwarding between this dev VM and the sandbox is
  proposed anywhere in it, per this task's explicit constraint.
  `SIMAP_BRIDGE_URL=http://127.0.0.1:8135` now genuinely resolves, since
  both processes are co-located.
  Startup commands, `/health` curl test, and a Streamlit-liveness curl test
  are all spelled out exactly, plus a step 6 "confirm the whole chain"
  check on a real search's `source_type` (`simap_mcp` vs `local_fallback`)
  — the only condition under which the deployment may be called "live."
- **Still not deployed.** No access to the real NemoClaw sandbox from this
  session — the README's closing section says so explicitly and states the
  exact condition (both processes started together + a search actually
  showing `simap_mcp`) that must hold before this integration is reported
  as done.

## Phase 19 — `submit_human_decision` MCP tool (closes the human-approval gap for Hermes)

Scope: `src/mcp_server.py` (one new tool, added imports only) and
`tests/test_mcp_server.py` (3 new tests + the protocol test's expected tool
set updated from six to seven names). No changes to `app.py`, `src/agents/
feedback.py`, or any scoring/matching/extraction/briefing logic — this phase
wraps an existing, already-tested function exactly the way Phase 11 wrapped
the rest of the pipeline. `python -m pytest -q` → **117/117 passing** (114
existing + 3 new), `ruff check src/mcp_server.py tests/test_mcp_server.py` →
clean.

- **Why:** `src/mcp_server.py` (Phase 11) gave Hermes/NemoClaw six tools
  covering search → extract → match → qualify → create_briefing, but stopped
  short of the workflow's actual last step. `qualify_tender`/`create_briefing`
  return a GO/MAYBE/NO-GO **recommendation** — in `app.py` this was always
  presented as a proposal pending an explicit Approve/Reject/Request-more-
  research click (`_submit_review` → `src.agents.feedback.record_feedback`),
  never as a closed decision. A Hermes-only conversation had no equivalent
  tool to record that same human decision, so a chat-driven demo could show a
  recommendation but had no way to durably capture that a human actually
  reviewed it — the exact "validation humaine" requirement this task
  (Agentic Tender Assistant demo, LaunchPad/BREV environment) calls out as
  mandatory for both the Streamlit and the Hermes/NemoClaw interface.
- **No new server, no reimplemented logic.** `submit_human_decision(tender_id,
  decision, reviewer=None, notes=None)` re-runs the same qualification
  (`_run_qualification`, already shared with `qualify_tender`/
  `create_briefing`) to get a fresh `QualificationBriefing`, then calls
  `src.agents.feedback.record_feedback` **unmodified** — the identical
  function `app.py`'s three review buttons already call. It writes to the
  same two places `app.py` does: `data/feedback_log.json` (append-only
  decision log) and, mirroring `create_briefing`, persists the *reviewed*
  briefing (now carrying `human_review`) to `data/briefings/<tender_id>.json`
  — so a Hermes-only session produces the same durable artifacts a Streamlit
  session would.
- **`decision` is validated, never guessed.** Must be exactly one of
  `src.schemas.briefing.HumanDecision`'s three values (`"approved"` /
  `"rejected"` / `"more_research"`); anything else returns `status: "error"`
  with the invalid value quoted back, and writes nothing — same fail-closed
  contract as `get_tender`/`create_briefing` on an unknown `tender_id`.
- **`FEEDBACK_LOG_PATH`** added as a module-level constant (mirroring
  `BRIEFINGS_DIR`'s existing pattern) so tests can `monkeypatch` it to a
  `tmp_path`, exactly like the existing `create_briefing` tests do for
  `BRIEFINGS_DIR` — no test writes to the repo's real
  `data/feedback_log.json`.
- **`mcp`'s `instructions` string updated** to name the new tool as the
  pipeline's actual last step and to state explicitly that a recommendation
  is never final on its own — read once by any MCP client (Hermes/NemoClaw)
  that surfaces server instructions to its model, so a chat-driven session is
  told, not left to infer, that approval requires this call.
- **Verified this session** (ad hoc, outside pytest, in a scratch temp
  directory so the repo's real `data/` was never touched): ran
  `search_tenders("cloud infrastructure")` → 3 local-sample results,
  `source_type: "local_fallback"` (honest — `SIMAP_MCP_ENTRYPOINT` is unset
  in this dev VM, per Phase 14/16, so this is not and does not claim to be a
  live SIMAP result); then `submit_human_decision("cloud-infra-2026",
  "approved", reviewer="demo-reviewer", notes="Validated for LaunchPad
  demo")` → `status: "ok"`, the persisted briefing JSON and
  `feedback_log.json` both carry the `approved` decision with that reviewer/
  notes and a real UTC timestamp. This is the same
  search → qualify → GO/MAYBE/NO-GO → human-review chain `app.py` already
  demonstrates, now also reachable through the MCP tool surface alone (i.e.
  usable from a Hermes chat with no Streamlit involved).
- **Still not registered with Hermes.** Adding the tool to this repo's
  `src/mcp_server.py` does not, by itself, make it available in any Hermes
  chat — that requires the same manual registration step already documented
  for the whole server in this file's Phase 11 section ("Registering with
  Hermes"), performed by whoever has access to
  `/sandbox/.hermes/config.yaml` from inside the actual NemoClaw/OpenShell
  sandbox. This repo's environment has no path to that file (confirmed
  throughout this log and `NVIDIA_AUDIT.md`) — this phase makes the
  capability real and tested, not deployed.

## Phase 20 — Finalization pass: dedup MCP calls, `publication_id`, `create_draft`

Preceded by a read-only inspection (git state, agent/schema/scoring
locations, confirmed bridge priority order `simap_bridge -> simap -> tavily
-> local_sample` live, confirmed `src/mcp_server.py` is the single Tender
Assistant agent's own tool surface — not a second SIMAP MCP server, never
talks to simap.ch directly) reported to the user before any change, per this
task's explicit "report before modifying" requirement. Full gap list found:
(A) SELECT phase not exposed as an MCP tool, (B) `publication_id` parsed
then discarded — blocks `get_tender_details`/real deadlines, (C) no
already-awarded detection, (D) no DRAFT phase, (E) `_find_tender` repeats
`orchestrator.search("")` on every single tool call. User scoped this
session to **B + E + D** (readiness-memo variant); **A and C deferred**
(not attempted — no code speculatively added for either).

Scope: `src/schemas/tender.py` (`Tender.publication_id`), `src/adapters/
tender_search.py` (`_parse_search_tenders_markdown` captures it),
`src/mcp_server.py` (`_tender_cache` + `create_draft`/`_render_readiness_
memo`), `.gitignore` (`data/drafts/`). No changes to scoring
(`fit_scoring.py`, `tender_selection.py`, `matching.py`), to `app.py`, or to
any already-passing test's assertions beyond updating the tool-count/name
set the new tool changed. `python -m pytest -q` → **124/124 passing** (117
existing + 7 new), `ruff check` clean (same one pre-existing, untouched
`app.py` warning as every prior phase).

- **(E) No more redundant MCP calls.** `_tender_cache` (module-level dict,
  keyed by `Tender.id`) is populated by every `search_tenders()` call and by
  `_find_tender`'s own fallback search; `_find_tender` now checks it first
  and only calls `orchestrator.search("")` on an actual cache miss — at most
  once per unseen id per process lifetime. Verified by monkeypatching
  `orchestrator.search` with a call-counter and running
  `get_tender -> extract_requirements -> match_hpe_capabilities ->
  qualify_tender` for the same id: **1** real search call, not 4 (previously
  would have been 4; a full search→...→submit_human_decision→create_draft
  pass would previously have been 6).
- **(B) `publication_id` retained, not derived.** `Tender` gained
  `publication_id: str | None = None` (default `None` — every existing
  local-sample fixture and test needed zero changes).
  `_parse_search_tenders_markdown` now reads the real `- **Publication
  ID:**` line already present in `@digilac/simap-mcp`'s search-result
  Markdown (Phase 14's own template, re-verified, not re-guessed) into it.
  Nothing calls `get_tender_details` with it yet — that's (A)/(C)'s job,
  deferred — this phase only stops throwing the real value away.
- **(D) `create_draft` — the mandatory-after-approval last step.** Reads the
  **already-persisted** `data/briefings/<id>.json` (written by
  `submit_human_decision`) rather than recomputing qualification fresh, so
  the draft can never disagree with what a human actually approved. Refuses
  with `status: "error"` (writes nothing) unless that file's
  `human_review.decision == "approved"` — verified for: no briefing yet,
  briefing present but not approved, and the success path. The draft itself
  (`_render_readiness_memo`) is a **bid-readiness memo**, not a proposal
  letter — deliberately, since this repo has no real HPE proposal content
  to draw from and inventing any (a certification, reference, legal
  presence, or deadline) is exactly what the reliability constraints
  forbid. Every line is copied from a field already on the approved
  briefing (score, recommendation, confirmed matches, gaps, unknowns,
  risks, next actions, citations); an empty `deadlines` list renders the
  literal string "UNKNOWN — no deadline could be confirmed...", never a
  date — verified with a dedicated test asserting no `\d{4}-\d{2}-\d{2}`
  pattern appears anywhere in that section when `deadlines` is empty.
  Persisted to `data/drafts/<id>.md` (new gitignored runtime dir, same
  pattern as `data/briefings/`).
- **Manually verified the full phase chain end-to-end** (real module calls,
  not mocked): `search_tenders` (RESEARCH) → `get_tender`/
  `extract_requirements`/`match_hpe_capabilities` (INSPECT/EXTRACT) →
  `qualify_tender` (QUALIFY/SCORE) → `create_draft` correctly refused
  (no review yet) → `submit_human_decision("approved")` (HUMAN REVIEW) →
  `create_draft` succeeded (DRAFT), producing a real memo with the actual
  recommendation/score/reviewer — all against `local_fallback` data in this
  environment (honestly labeled as such throughout), no SIMAP call
  fabricated as real.
