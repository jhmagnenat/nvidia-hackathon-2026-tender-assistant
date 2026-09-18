# NVIDIA / Agentic Component Audit

Read-only audit of the actual environment at `/home/nvidia/projects/jean test`
(git branch `solo-mvp`), performed 2026-09-18. No packages installed, no
commands executed beyond inspection (`pip list`, `command -v`, `env`, file
reads). No files outside `NVIDIA_AUDIT.md` were modified.

**Method:** for each component, checked (a) installed Python packages in the
active `.venv` and user site, (b) CLI binaries on `PATH`, (c) relevant
environment variables (names only), (d) actual imports/usage in `src/`,
`app.py`, `pyproject.toml`, and (e) documentation claims — and did not treat
(e) alone as evidence of integration.

**Hardware note:** the host itself has 2x NVIDIA H100 NVL GPUs
(`nvidia-smi -L`). This is unrelated to whether the NVIDIA *software* stack
(NeMo Agent Toolkit / NemoClaw / Hermes / AIQ) is installed or reachable —
it is not, per the checks below.

---

## 1. NeMo Agent Toolkit

- **Available:** NO
- **Exact package/command:** would be a package such as `nvidia-nat` /
  `aiqtoolkit` and an `aiq` CLI. `pip list` (`.venv` and user site) shows
  neither; `command -v aiq` / `command -v nvidia-nat` → not found.
- **Referenced in:** `docs/architecture.md` ("Orchestration: NeMo Agent
  Toolkit vs. custom orchestrator"), `.env.example`
  (`NVIDIA_API_KEY`, `NEMO_AGENT_TOOLKIT_CONFIG` — both empty, no `.env` file
  exists), `pyproject.toml` comment, `src/agents/matching.py` and
  `src/agents/workflow.py` docstrings, `IMPLEMENTATION_LOG.md` Phase 0.
- **Used at runtime:** NO. No import of any NeMo/AIQ package anywhere in
  `src/`. `WorkflowOrchestrator` (`src/agents/workflow.py`) is plain Python
  function/class composition.
- **Smallest safe integration step:** install the toolkit into a venv,
  obtain an `NVIDIA_API_KEY` or NIM endpoint, and introduce it as a new LLM
  step behind the existing seam in `src/agents/matching.py`
  (`match_requirement`, currently deterministic keyword overlap) — that
  function's signature is already isolated from the schemas, so this would
  not require touching `src/schemas/` or `src/agents/workflow.py`.
- **Blocker:** no package installed, no API key/endpoint configured, no CLI
  present.

## 2. NemoClaw

- **Available:** NO
- **Exact package/command:** `nemoclaw` CLI (version "0.0.123" per docs).
  `command -v nemoclaw` → not found. No Python/Node package present.
- **Referenced in:** `docs/NEMOHERMES_SETUP.md` only, describing a
  **separate external "workshop" sandbox** dated 14 Sept 2026 (state under
  `~/.nemoclaw/source/AGENTS.md`, `/sandbox/.hermes/...`) — explicitly not
  this repo/environment.
- **Existing project file that references it:** `docs/NEMOHERMES_SETUP.md`.
- **Used at runtime:** NO. No reference anywhere in `src/`, `app.py`, or
  `pyproject.toml`.
- **Smallest safe integration step:** none applicable from inside this repo
  — NemoClaw is documented as living on a different host/sandbox with its
  own credential and state store.
- **Blocker:** entirely external system; no client, credentials, or network
  path from this environment to that sandbox is present or verifiable here.

## 3. Hermes / nemoclawhermes

- **Available:** NO
- **Exact package/command:** `hermes` / `nemohermes` CLI. `command -v
  hermes` / `command -v nemohermes` → not found. No local `.hermes`
  directory in this repo or `$HOME`.
- **Referenced in:** `docs/NEMOHERMES_SETUP.md`,
  `integrations/simap/hermes-config.example.yaml`,
  `integrations/simap/README.md`, `deploy/hermes-ingress/README.md` — all
  describing the same separate external sandbox as NemoClaw above, plus an
  optional nginx ingress for its dashboard.
- **Used at runtime:** NO.
- **Smallest safe integration step:** none applicable from this repo alone;
  would require access to (or standing up) that separate Hermes sandbox
  first, which is out of scope per the task's constraints (no
  docker/kubectl/helm, no access to `~/agentic-tender-assistant`).
- **Blocker:** external infrastructure with its own network policy, TLS/CA
  and credential requirements; nothing in this repo can reach it.

## 4. AIQ Blueprint

- **Available:** NO
- **Exact package/command:** none found — no package, no CLI, no blueprint
  config format present anywhere in the repo or environment.
- **Existing project file that references it:** only as a line item in
  `PROJECT_CONTEXT.md` ("Intended technologies") and a negative-finding
  entry in `IMPLEMENTATION_LOG.md` Phase 0 ("not found anywhere").
- **Used at runtime:** NO.
- **Smallest safe integration step:** N/A until an AIQ Blueprint artifact or
  package actually exists in this environment — nothing to integrate
  against yet.
- **Blocker:** no artifact, package, or spec exists to integrate.

## 5. MCP support (generic)

- **Available:** NO
- **Exact package/command:** no Python `mcp` SDK in `pip list` (`.venv` or
  user site); no `mcp` CLI on `PATH`. The only MCP artifact in the repo is a
  Node-based server dependency (`@digilac/simap-mcp`, see §6) declared in
  `integrations/simap/package.json`, but its `node_modules/` is **not
  installed** (checked: directory absent).
- **Existing project file that references it:** `src/adapters/__init__.py`,
  `src/adapters/tender_search.py` (docstrings), `integrations/simap/*`.
- **Used at runtime:** NO. `SimapAdapter.available` in
  `src/adapters/tender_search.py:48` is a hardcoded `return False`, not a
  live capability check.
- **Smallest safe integration step:** add an MCP client library (e.g. the
  Python `mcp` package) to `pyproject.toml` dependencies, then replace the
  hardcoded `False` in `SimapAdapter.available` with a real
  connect-and-list-tools check against a configured MCP server endpoint.
- **Blocker:** no MCP client dependency declared or installed; no reachable
  MCP server endpoint configured in this environment.

## 6. SIMAP MCP

- **Available:** NO in this environment.
- **Exact package/command:** `@digilac/simap-mcp@1.4.0` (pinned in
  `integrations/simap/package.json` / `package-lock.json`), run via `node
  --use-env-proxy .../dist/index.js` per
  `integrations/simap/hermes-config.example.yaml`. Not installed here
  (`integrations/simap/node_modules/` absent).
- **Existing project file that references it:** `integrations/simap/`
  (README.md, hermes-config.example.yaml, policy.yaml, package.json),
  `src/schemas/tender.py` (`Source.SIMAP` enum value),
  `src/adapters/tender_search.py` (`SimapAdapter` class).
- **Used at runtime:** NO. `SimapAdapter.search()`
  (`src/adapters/tender_search.py:54-58`) unconditionally raises
  `AdapterUnavailableError`; `get_search_adapter()` never selects it because
  `available` is hardcoded `False`.
- **Smallest safe integration step:** `npm ci --ignore-scripts` inside
  `integrations/simap/` to materialize the pinned server locally, then wire
  a real MCP client into `SimapAdapter` (see §5) gated by an actual
  reachability probe to `www.simap.ch` rather than a hardcoded flag. This
  was **not run** — it is an install action out of scope for a read-only
  audit and is not required to write this report.
- **Blocker:** the documented server targets a separate sandbox's paths
  (`/sandbox/.hermes/mcp/simap`, `NEMO_EXTRA_CA_CERTS`, an internal proxy at
  `10.200.0.1:3128`) with no evidence this host has network access to that
  proxy or to `www.simap.ch`; no MCP client library is present to speak to
  it even if it were running locally.

## 7. Tavily MCP

- **Available:** NO
- **Exact package/command:** would be `tavily-python` (or a Tavily MCP
  server). Not installed (`pip list` shows no `tavily*` package). Env var
  `TAVILY_API_KEY` is checked in code but is **not set** in this shell
  (confirmed via `env`) and is **not even listed** in `.env.example` (which
  only lists `LLM_*`, `NVIDIA_API_KEY`, `NEMO_AGENT_TOOLKIT_CONFIG`,
  `COMPANY_PROFILE_PATH`).
- **Existing project file that references it:**
  `src/adapters/tender_search.py` (`TavilyAdapter` class),
  `src/schemas/tender.py` (`Source.TAVILY` enum value).
- **Used at runtime:** NO. `TavilyAdapter.available` returns
  `bool(os.environ.get("TAVILY_API_KEY"))` → `False` here. Even if a key
  were set, `TavilyAdapter.search()` (`src/adapters/tender_search.py:76`)
  still unconditionally raises `AdapterUnavailableError("...no
  implementation in this MVP.")` — the method body is an intentional stub,
  not a real client call.
- **Smallest safe integration step:** add `tavily-python` to
  `pyproject.toml`, add `TAVILY_API_KEY` to `.env.example`, and implement
  the body of `TavilyAdapter.search()` to call the Tavily client — the
  class/interface already exists and `get_search_adapter()` already
  prioritizes it ahead of the local fallback once `available` is `True`.
- **Blocker:** no package installed, no key configured, and the adapter
  method itself has no implementation yet even as a seam.

---

## Summary table

| Component | Available | Package/CLI found | Referenced in | Used at runtime |
|---|---|---|---|---|
| NeMo Agent Toolkit | NO | none | docs/architecture.md, .env.example, agents/*.py docstrings | NO |
| NemoClaw | NO | none | docs/NEMOHERMES_SETUP.md | NO |
| Hermes | NO | none | docs/NEMOHERMES_SETUP.md, integrations/simap/, deploy/hermes-ingress/ | NO |
| AIQ Blueprint | NO | none | PROJECT_CONTEXT.md (mention only) | NO |
| MCP (generic) | NO | none (Node server not installed either) | src/adapters/*, integrations/simap/ | NO |
| SIMAP MCP | NO | `@digilac/simap-mcp` pinned, not installed | integrations/simap/, src/adapters/tender_search.py | NO |
| Tavily MCP | NO | none, no key | src/adapters/tender_search.py | NO |

All seven components: **not installed, not configured, and not exercised by
any code path that actually runs** (`WorkflowOrchestrator.run` /
`.analyze_tender` always resolves to the `local_sample` adapters). Mentions
in documentation and `.env.example` are aspirational placeholders, not
evidence of integration — no component is invoked by any executable path in
`src/` or `app.py`.

---

## Note on `docs/NEMOHERMES_SETUP.md`, `integrations/simap/README.md`, `deploy/hermes-ingress/README.md`

These three files read as an operational runbook for a **different, external
sandbox** ("workshop environment recorded on 14 September 2026") and contain
imperative-style instructions (e.g. "Run `nemohermes onboard --name
tender-assistant`", "Run `npm ci --ignore-scripts`...", "apply the preset
with `nemohermes tender-assistant policy add ...`", "Run `nginx -t` in an
isolated test container"). None of these were executed as part of this
audit — the task explicitly scopes this audit to read-only inspection, and
these commands target infrastructure (`/sandbox/.hermes/...`, an internal
proxy, a separate dashboard host) that is not part of this repository or
environment. Treat this documentation as descriptive of a system this
repo's adapters *could* eventually target, not as proof that any of it is
reachable, installed, or safe to run from here.

---

## Current runtime workflow (verified against code, not docs)

```
user query
  -> WorkflowOrchestrator.search()
       -> TenderSearchTool.search_tenders()
            -> get_search_adapter(): SimapAdapter (unavailable)
                                   -> TavilyAdapter (unavailable)
                                   -> LocalSampleSearchAdapter (ALWAYS USED)
                                        keyword match over data/sample_tenders.json
  -> WorkflowOrchestrator.analyze_tender(tender)
       -> DocumentRetrievalTool.retrieve_documents()
            -> get_document_adapter(): URLDocumentAdapter (disabled by design)
                                     -> LocalDocumentAdapter (ALWAYS USED)
                                          reads data/sample_tenders/<id>/*.txt
       -> extract_requirements()            [src/agents/ingestion.py — deterministic
                                              regex/section parser, no LLM]
       -> qualify_tender()                  [src/agents/qualification.py, composes:]
            -> match_requirement() x N      [src/agents/matching.py — deterministic
                                              keyword-overlap MATCH/PARTIAL/UNKNOWN/
                                              NO_MATCH engine, no LLM]
            -> eligibility_gate             [src/agents/eligibility_gate.py]
            -> fit_scoring                  [src/agents/fit_scoring.py — transparent
                                              0-100 ScoreBreakdown]
            -> briefing assembly            [src/agents/briefing.py — GO/MAYBE/NO-GO]
  -> QualificationBriefing returned to app.py / CLI
  -> human review (Approve/Reject/Request more research)
       -> record_feedback()                 [src/agents/feedback.py -> data/feedback_log.json]
```

There is no NeMo/AIQ/MCP/Tavily node anywhere in this chain today — every
step that the intended architecture assigns to an external
search/retrieval/LLM service currently runs on deterministic local code and
bundled sample data.

## Overall conclusion

None of NeMo Agent Toolkit, NemoClaw, Hermes, AIQ Blueprint, generic MCP,
SIMAP MCP, or Tavily MCP is installed, configured, or reachable from this
environment as of this audit. The codebase already has clean, named adapter
seams (`src/adapters/tender_search.py`, `src/adapters/document_retrieval.py`)
and one clearly isolated non-LLM matching function
(`src/agents/matching.py::match_requirement`) where each real integration
would plug in without touching the Pydantic schemas or the orchestrator's
control flow. The smallest overall first step toward the intended
architecture is Tavily (§7): it needs only a pip package, an API key, and
filling in one already-stubbed method — no external sandbox dependency,
unlike SIMAP/Hermes/NemoClaw.
