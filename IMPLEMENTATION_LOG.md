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
