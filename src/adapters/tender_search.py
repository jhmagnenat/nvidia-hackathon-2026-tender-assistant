"""Tender search adapters.

`SimapAdapter` is a **real** MCP client for the `@digilac/simap-mcp` stdio
server documented in `integrations/simap/` — it spawns the exact
`node --use-env-proxy <entrypoint>` process
`integrations/simap/hermes-config.example.yaml` describes and speaks the real
MCP stdio protocol to it via the `mcp` package (already a pinned dependency —
see `src/mcp_server.py`). It is not a hardcoded stub anymore.

**This is not "Streamlit/CLI calls Hermes."** No programmatic Hermes endpoint
is documented anywhere in this repo (see the SIMAP MCP procedure analysis in
IMPLEMENTATION_LOG.md) and none is invented here. `SimapAdapter` launches its
*own*, independent instance of the same SIMAP MCP server package Hermes also
launches — Hermes's chat UI and this application remain two separate
consumers of that same underlying package, not one calling the other.
Nothing in `app.py` invokes this adapter's live path today (see
`available`, below) — do not present Streamlit as "using SIMAP MCP" unless a
`SimapAdapter.search()` call has actually succeeded.

`SimapAdapter.available` is a real, dynamic check (entrypoint file present,
node binary resolvable) — **unconfigured by default**, so it stays `False`
in this dev/CI environment exactly as before (no `SIMAP_MCP_ENTRYPOINT` env
var is set here, and this environment cannot reach the sandbox's proxy/CA
even if it were — see `integrations/simap/README.md` "Troubleshooting").
Activating it for real requires setting `SIMAP_MCP_ENTRYPOINT` (and, only if
`node` isn't the right binary on that host, `SIMAP_MCP_NODE_COMMAND`) in
whatever environment actually has the package installed and network access —
this dev/CI environment is not that environment.

`TavilyAdapter` remains an honest stub — no Tavily package/key present.

`LocalSampleSearchAdapter` is the guaranteed fallback: it reads
`data/sample_tenders.json` and keyword-matches the query against title/scope.
Kept unchanged and still tried last.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from src.adapters import AdapterUnavailableError
from src.schemas.common import ResearchMode
from src.schemas.tender import Tender, TenderSource

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_INDEX = REPO_ROOT / "data" / "sample_tenders.json"

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ]{3,}")


class TenderSearchAdapter:
    name: str = "base"

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        raise NotImplementedError


_ENV_ENTRYPOINT = "SIMAP_MCP_ENTRYPOINT"
_ENV_NODE_COMMAND = "SIMAP_MCP_NODE_COMMAND"
_ENV_TIMEOUT = "SIMAP_MCP_TIMEOUT_SECONDS"
_DEFAULT_NODE_COMMAND = "node"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_NO_RESULTS_TEXT = "No tenders found matching these criteria."

# One `- **Label:** value` line, exactly as @digilac/simap-mcp@1.4.0's
# dist/utils/formatting.js `formatProject()` emits it (inspected via
# `npm pack` into /tmp, never installed here — see
# integrations/simap/README.md). Not a guess at the format: copied from the
# compiled package's literal template strings.
_FIELD_RE = re.compile(r"^-\s\*\*(?P<label>[^:*]+):\*\*\s(?P<value>.+)$")


def _parse_search_tenders_markdown(text: str) -> list[Tender]:
    """Parse @digilac/simap-mcp's `search_tenders` tool output into Tenders.

    That tool returns Markdown, not structured JSON (confirmed by reading
    `dist/tools/search-tenders.js` — it hands `formatProject()`'s per-result
    string straight back as the tool's only text content). Every field
    pulled out below corresponds to a literal line that function emits; a
    submission deadline is deliberately left `None` here — it's only
    present via the separate `get_tender_details` tool, never guessed.
    """
    if text.strip() == _NO_RESULTS_TEXT:
        return []

    tenders: list[Tender] = []
    # formatHeader() emits a single "# ..." line before any "## title"
    # project block; splitting on "## " at line start and dropping the first
    # chunk removes that header without needing to parse it.
    for block in re.split(r"(?m)^## ", text)[1:]:
        lines = block.splitlines()
        title = lines[0].strip() if lines else ""
        fields: dict[str, str] = {}
        for line in lines[1:]:
            match = _FIELD_RE.match(line)
            if match:
                fields[match.group("label").strip()] = match.group("value").strip()

        project_id = fields.get("Project ID")
        if not title or not project_id:
            continue  # not a parseable project block — skip rather than fabricate one

        publication_date = None
        if raw_date := fields.get("Publication Date"):
            try:
                publication_date = date.fromisoformat(raw_date[:10])
            except ValueError:
                publication_date = None  # unparseable — stays UNKNOWN, not guessed

        tenders.append(
            Tender(
                id=project_id,
                title=title,
                buyer=fields.get("Office") or None,
                location=fields.get("Location") or None,
                publication_date=publication_date,
                submission_deadline=None,  # not in search results — see get_tender_details
                url=fields.get("simap Link") or None,
                source=TenderSource.SIMAP,
                scope=None,  # not in search results
                research_mode=ResearchMode.SIMAP_MCP,
                publication_id=fields.get("Publication ID") or None,
            )
        )
    return tenders


_NOT_FOUND_MARKER = "was not found on simap"


def _empty_tender_details(available: bool, reason: str | None) -> dict:
    return {
        "available": available,
        "reason": reason,
        "title": None,
        "url": None,
        "publication_date": None,
        "submission_deadline": None,
        "has_project_documents": None,
        "pub_type": None,
        "process_type": None,
    }


# Matches a real Markdown section heading ("## General Information",
# "### Latest Publication", "### Deadlines", ...) — h2/h3 only. The
# template's "#### Lot N: ..." (h4) lot headings deliberately don't match,
# so lines under a lot simply stay attributed to whatever h2/h3 section
# contains them; no field this parser extracts ever appears there.
_SECTION_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")


def _parse_tender_details_markdown(text: str) -> dict:
    """Parse @digilac/simap-mcp's `get_tender_details` tool output.

    Real template (`dist/tools/get-tender-details.js` +
    `dist/utils/formatting.js` `formatProjectHeader`/`formatPublicationDetails`,
    re-verified via `npm pack` before writing this — never assumed from
    memory): `## General Information` (always, if the header 404'd it's
    omitted), optionally its `### Latest Publication` sub-section, then
    `## Publication Details` (if that 404'd it's omitted too; its
    `### Deadlines` sub-section only appears when at least one date field is
    actually present upstream).

    Section-scoped on purpose: the label `Type` is reused for three
    different things in that template (project type under "General
    Information", the real publication status under "Latest Publication",
    and a composite processType/orderType-joined line under "Publication
    Details") — a flat label->value scan would silently pick the wrong one.
    `pub_type` is read *only* from "Latest Publication" (`pub.pubType` —
    the one unambiguous, single-value status field in the whole response);
    `process_type` from "General Information" (`header.processType` — the
    same "open"/"selective"/"invitation"/"direct"/"no_process" vocabulary
    `search_tenders`' own `processTypes` filter uses). The project-type and
    composite lines are deliberately never extracted — nothing downstream
    should key an already-awarded/status decision off them.

    Both header and details 404 independently server-side; if *neither* is
    present, `get_tender_details` itself returns the literal not-found
    message below instead of any `##` section — that case, and a genuinely
    empty response, are both reported as `available: False` with the exact
    upstream text as `reason`, never silently treated as "no data".
    """
    stripped = text.strip()
    if not stripped or _NOT_FOUND_MARKER in stripped.lower():
        return _empty_tender_details(False, stripped or "empty response from get_tender_details")

    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header = _SECTION_RE.match(line)
        if header:
            current = sections.setdefault(header.group(2), {})
            continue
        if current is None:
            continue  # content before any section heading (the "# Tender Details" title line) — nothing to capture
        match = _FIELD_RE.match(line)
        if match:
            current[match.group("label").strip()] = match.group("value").strip()

    general = sections.get("General Information", {})
    latest_pub = sections.get("Latest Publication", {})
    pub_details = sections.get("Publication Details", {})
    deadlines = sections.get("Deadlines", {})

    # Stored as ISO strings, not `date` objects: this dict (unlike `Tender`)
    # is plain JSON returned straight through an MCP tool result, with no
    # pydantic model_dump_json step to convert a `date` for us.
    publication_date = None
    if raw := pub_details.get("Publication Date"):
        try:
            publication_date = date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            publication_date = None  # unparseable — stays UNKNOWN, not guessed

    submission_deadline = None
    if raw := deadlines.get("Submission Deadline"):
        try:
            submission_deadline = date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            submission_deadline = None

    has_docs_raw = (pub_details.get("Has Project Documents") or "").strip().lower()
    has_project_documents = {"yes": True, "no": False}.get(has_docs_raw)

    # "N/A" is that literal template's own placeholder for a missing value
    # (`header.projectSubType || "N/A"`, etc.) — treated the same as absent.
    def _or_none(value: str | None) -> str | None:
        return value if value and value != "N/A" else None

    result = _empty_tender_details(True, None)
    result.update(
        title=_or_none(pub_details.get("Title")) or _or_none(general.get("Title")),
        url=_or_none(general.get("simap Link")),
        publication_date=publication_date,
        submission_deadline=submission_deadline,
        has_project_documents=has_project_documents,
        pub_type=_or_none(latest_pub.get("Type")),
        process_type=_or_none(general.get("Process")),
    )
    return result


def fetch_tender_details(tender: Tender, adapters: list[TenderSearchAdapter]) -> dict:
    """Shared "get real tender details for this tender" helper — the one
    place this lookup is implemented, reused by both `src/mcp_server.py`'s
    `get_tender` tool and `src.agents.tender_selection`'s SELECT phase
    (status/non-actionable detection), so neither reimplements it.

    `adapters` is supplied by the caller (typically `get_search_adapters()`)
    rather than fetched internally — keeps this function free of hidden
    global state and easy to test with a fixed, known adapter list.

    Never fabricates anything: a tender with no `publication_id` (see
    `Tender.publication_id`'s docstring), or a candidate list with no
    adapter that both supports `get_tender_details` and is currently
    available, comes back as `{"available": False, "reason": ...}` — never
    a silently-empty "success".
    """
    if not tender.publication_id:
        return _empty_tender_details(
            False,
            f"No publication_id was captured for tender {tender.id!r} from its search result — "
            "get_tender_details cannot be called without it.",
        )

    errors: list[str] = []
    for adapter in adapters:
        get_details = getattr(adapter, "get_tender_details", None)
        if get_details is None or not adapter.available:
            continue
        try:
            return get_details(tender.id, tender.publication_id)
        except AdapterUnavailableError as exc:
            errors.append(f"{adapter.name}: {exc}")
            continue

    reason = "; ".join(errors) if errors else "no SIMAP adapter (simap_bridge/simap) is currently available"
    return _empty_tender_details(False, f"get_tender_details could not be called: {reason}")


class SimapAdapter(TenderSearchAdapter):
    """Real MCP client for the `@digilac/simap-mcp` stdio server.

    Spawns `<node_command> --use-env-proxy <entrypoint>` (the exact command
    shape `integrations/simap/hermes-config.example.yaml` documents) and
    speaks MCP over stdio via the `mcp` package. `entrypoint`/`node_command`
    default from the `SIMAP_MCP_ENTRYPOINT`/`SIMAP_MCP_NODE_COMMAND` env
    vars and are unset by default — `available` is honestly `False` until an
    operator points them at a real, locally-installed
    `@digilac/simap-mcp` in an environment that can actually reach
    `www.simap.ch` (proxy/CA permitting — see
    `integrations/simap/README.md`).

    `args`/`cwd` are constructor-only overrides for tests, so the real MCP
    stdio transport/protocol code can be exercised against a lightweight
    Python stand-in server (`tests/fixtures/fake_simap_mcp_server.py`)
    instead of the real Node package — production code never sets them.
    """

    name = "simap"

    def __init__(
        self,
        *,
        entrypoint: str | os.PathLike[str] | None = None,
        node_command: str | None = None,
        args: list[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ):
        raw_entrypoint = entrypoint if entrypoint is not None else os.environ.get(_ENV_ENTRYPOINT)
        self.entrypoint = Path(raw_entrypoint) if raw_entrypoint else None
        self.node_command = node_command or os.environ.get(_ENV_NODE_COMMAND) or _DEFAULT_NODE_COMMAND
        self._args_override = args
        self.cwd = cwd
        self.timeout = timeout if timeout is not None else float(os.environ.get(_ENV_TIMEOUT, _DEFAULT_TIMEOUT_SECONDS))
        # Full parent-process env by default. The mcp SDK's stdio client only
        # forwards a minimal safe subset (HOME/LOGNAME/PATH/SHELL/TERM/USER)
        # when env=None (see mcp.client.stdio.get_default_environment()) —
        # HTTP_PROXY/HTTPS_PROXY/NODE_EXTRA_CA_CERTS/SSL_CERT_FILE would
        # silently NOT reach the subprocess otherwise, even if this app's own
        # process has them set correctly.
        self._env = env if env is not None else dict(os.environ)

    def _resolved_args(self) -> list[str] | None:
        if self._args_override is not None:
            return list(self._args_override)
        if self.entrypoint is None:
            return None
        return ["--use-env-proxy", str(self.entrypoint)]

    @property
    def available(self) -> bool:
        args = self._resolved_args()
        if args is None:
            return False
        if self._args_override is None and not self.entrypoint.exists():
            return False
        return shutil.which(self.node_command) is not None or Path(self.node_command).is_file()

    def _server_params(self):
        from mcp import StdioServerParameters

        return StdioServerParameters(
            command=self.node_command,
            args=self._resolved_args() or [],
            env=self._env,
            cwd=self.cwd,
        )

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Spawn the real MCP subprocess, call one tool, return its raw text
        content. Public (not `_call_tool`) and async on purpose: this is the
        exact building block `src/simap_bridge.py` reuses to relay
        `search_tenders`/`get_tender_details`/`list_cantons` over HTTP,
        instead of re-implementing MCP transport a second time there."""
        if not self.available:
            raise AdapterUnavailableError(
                "SIMAP MCP is not configured/reachable from this process "
                f"(entrypoint={self.entrypoint!r}, node_command={self.node_command!r}). "
                f"Set {_ENV_ENTRYPOINT} to activate it in an environment that actually "
                "has @digilac/simap-mcp installed and network access — "
                "see integrations/simap/README.md."
            )

        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        try:
            async with (
                stdio_client(self._server_params()) as (read, write),
                ClientSession(read, write) as session,
            ):
                await asyncio.wait_for(session.initialize(), timeout=self.timeout)
                result = await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=self.timeout)
        except AdapterUnavailableError:
            raise
        except Exception as exc:  # subprocess/transport/timeout failures
            raise AdapterUnavailableError(f"SIMAP MCP call failed: {exc}") from exc

        if result.isError:
            detail = result.content[0].text if result.content else "unknown error"
            raise AdapterUnavailableError(f"simap-mcp tool '{tool_name}' returned an error: {detail}")
        return "".join(getattr(block, "text", "") for block in result.content)

    @staticmethod
    def build_search_tenders_arguments(query: str, filters: dict | None = None) -> dict:
        """search_tenders' own `search` param requires >=3 chars if given at
        all (it's optional) — an empty/short query omits it rather than
        sending an invalid value; simap.ch then returns its own default
        result set, which is a real (if different) behavior, not this
        adapter approximating LocalSampleSearchAdapter's "no query = every
        tender" convention. Only the real simap_mcp filter vocabulary
        (`cantons`) is passed through — no free-text "location" -> canton-code
        translation is invented here. Static/pure so `src/simap_bridge.py`
        builds arguments identically without needing a `SimapAdapter` instance.
        """
        arguments: dict = {"lang": "en"}
        stripped = query.strip()
        if len(stripped) >= 3:
            arguments["search"] = stripped
        if cantons := (filters or {}).get("cantons"):
            arguments["cantons"] = list(cantons)
        return arguments

    async def asearch_raw(self, query: str, filters: dict | None = None) -> str:
        """Async, unparsed counterpart to `search()` — returns the tool's raw
        Markdown text. Used by `src/simap_bridge.py` (which is already
        inside an event loop and needs the text, not parsed `Tender`s)."""
        arguments = self.build_search_tenders_arguments(query, filters)
        return await self.call_tool("search_tenders", arguments)

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        text = asyncio.run(self.asearch_raw(query, filters))
        return _parse_search_tenders_markdown(text)

    async def aget_tender_details_raw(self, project_id: str, publication_id: str, lang: str = "en") -> str:
        """Async, unparsed counterpart to `get_tender_details()` — same
        reuse rationale as `asearch_raw`: src/simap_bridge.py calls this
        directly since it's already inside an event loop."""
        return await self.call_tool(
            "get_tender_details",
            {"projectId": project_id, "publicationId": publication_id, "lang": lang},
        )

    def get_tender_details(self, project_id: str, publication_id: str, lang: str = "en") -> dict:
        """Real get_tender_details call — needs *both* ids (see
        `Tender.publication_id`'s docstring for why `id`/project_id alone is
        never enough). Never raises on a normal "not found"/empty response —
        `_parse_tender_details_markdown` reports that as
        `{"available": False, "reason": ...}` instead; only a genuine
        transport/subprocess failure raises `AdapterUnavailableError`
        (via `call_tool`, unchanged)."""
        text = asyncio.run(self.aget_tender_details_raw(project_id, publication_id, lang))
        return _parse_tender_details_markdown(text)


class TavilyAdapter(TenderSearchAdapter):
    """Seam for Tavily search. Not configured/available in this environment."""

    name = "tavily"

    @property
    def available(self) -> bool:
        return bool(os.environ.get("TAVILY_API_KEY"))

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        if not self.available:
            raise AdapterUnavailableError(
                "Tavily is not configured (no TAVILY_API_KEY) — no tavily-python "
                "package is installed either. Falling back to local sample search."
            )
        raise AdapterUnavailableError("Tavily adapter has no implementation in this MVP.")


class LocalSampleSearchAdapter(TenderSearchAdapter):
    """Guaranteed-available fallback: keyword search over data/sample_tenders.json."""

    name = "local_sample"

    def __init__(self, index_path: Path = DEFAULT_SAMPLE_INDEX):
        self.index_path = index_path

    @property
    def available(self) -> bool:
        return self.index_path.exists()

    def _load(self) -> list[Tender]:
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [Tender.model_validate(entry) for entry in raw]

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        if not self.available:
            raise AdapterUnavailableError(f"Local sample index not found at {self.index_path}")

        tenders = self._load()
        filters = filters or {}

        if location := filters.get("location"):
            tenders = [t for t in tenders if t.location and location.lower() in t.location.lower()]

        query_terms = {w.lower() for w in _WORD_RE.findall(query)}
        if not query_terms:
            return tenders

        scored: list[tuple[int, Tender]] = []
        for tender in tenders:
            haystack = f"{tender.title} {tender.scope or ''}".lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score > 0:
                scored.append((score, tender))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [tender for _, tender in scored]


def _ordered_candidates(prefer: list[str] | None = None) -> list[TenderSearchAdapter]:
    # Deferred import: src.adapters.simap_bridge_client imports back from this
    # module (_parse_search_tenders_markdown, TenderSearchAdapter) — importing
    # it at module load time would be circular.
    from src.adapters.simap_bridge_client import SimapBridgeAdapter

    candidates: dict[str, TenderSearchAdapter] = {
        # simap_bridge first: it's the realistic real-SIMAP path when this
        # process runs outside the NemoClaw sandbox (the common case — see
        # that module's docstring); direct stdio `simap` only works when
        # co-located with the sandbox.
        "simap_bridge": SimapBridgeAdapter(),
        "simap": SimapAdapter(),
        "tavily": TavilyAdapter(),
        "local_sample": LocalSampleSearchAdapter(),
    }
    order = (prefer or []) + [name for name in candidates if name not in (prefer or [])]
    return [candidates[name] for name in order]


def get_search_adapters(prefer: list[str] | None = None) -> list[TenderSearchAdapter]:
    """Every candidate adapter, in priority order (simap_bridge -> simap ->
    tavily -> local_sample by default), regardless of `.available`.

    Unlike `get_search_adapter()` (a single pre-flight pick, kept for backward
    compatibility), this is meant for *runtime* fallback: a caller can try each
    in turn and move on when one raises `AdapterUnavailableError` mid-call, not
    just when `.available` was already `False` — see `TenderSearchTool`.
    """
    return _ordered_candidates(prefer)


def get_search_adapter(prefer: list[str] | None = None) -> TenderSearchAdapter:
    """Return the best available search adapter (pre-flight `.available` check only).

    `prefer` sets provider preference order (e.g. ["simap", "tavily"]); the
    local sample adapter is always appended last as the guaranteed fallback.
    """
    for adapter in _ordered_candidates(prefer):
        if adapter.available:
            return adapter
    # Unreachable in practice: local_sample.available is True whenever the repo's
    # data/sample_tenders.json exists, which it does.
    raise AdapterUnavailableError("No search adapter is available, including the local fallback.")
