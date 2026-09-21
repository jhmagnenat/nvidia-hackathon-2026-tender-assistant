"""SimapBridgeAdapter — HTTP client for src/simap_bridge.py.

The realistic way for *this* Streamlit/CLI environment to reach real SIMAP
data: Streamlit and the NemoClaw sandbox (where `@digilac/simap-mcp`'s
stdio process actually runs) are two separate environments — MCP stdio
cannot cross that boundary (see `src/adapters/tender_search.py::SimapAdapter`,
which *can* speak MCP stdio directly, but only when co-located with the
sandbox). This adapter instead calls the HTTP bridge
(`src/simap_bridge.py`) that must be deployed *inside* that sandbox — see
`deploy/simap-bridge/README.md`.

Unconfigured by default: `SIMAP_BRIDGE_URL` is unset in this environment, so
`available` is honestly `False` and `search()` raises `AdapterUnavailableError`
rather than silently falling back to local data itself (that fallback
decision belongs one layer up, in `TenderSearchTool` — see
`src/agents/search.py`). No URL, port, or response is invented: `available`
performs a real `GET <base>/health` call and only returns `True` when the
bridge itself reports `status: "ok"` (which it only does after actually
calling the real `list_cantons` MCP tool — see `src/simap_bridge.py`).

Uses only the stdlib `urllib` — no new dependency for the Streamlit/CLI side
(the bridge *server* is the only place `starlette`/`uvicorn` are needed —
see the `bridge` extra in pyproject.toml).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from src.adapters import AdapterUnavailableError
from src.adapters.tender_search import (
    TenderSearchAdapter,
    _parse_search_tenders_markdown,
    _parse_tender_details_markdown,
)
from src.schemas.tender import Tender

_ENV_BASE_URL = "SIMAP_BRIDGE_URL"
_ENV_TIMEOUT = "SIMAP_BRIDGE_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class SimapBridgeAdapter(TenderSearchAdapter):
    name = "simap_bridge"

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        raw = base_url if base_url is not None else os.environ.get(_ENV_BASE_URL)
        self.base_url = raw.rstrip("/") if raw else None
        self.timeout = timeout if timeout is not None else float(os.environ.get(_ENV_TIMEOUT, _DEFAULT_TIMEOUT_SECONDS))

    def _get(self, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{self.base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    @property
    def available(self) -> bool:
        if not self.base_url:
            return False
        try:
            status, body = self._get("/health")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False
        return status == 200 and body.get("status") == "ok"

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        if not self.base_url:
            raise AdapterUnavailableError(
                f"SIMAP bridge is not configured — set {_ENV_BASE_URL} to a reachable bridge URL "
                "(deployed inside the NemoClaw sandbox, see deploy/simap-bridge/README.md). "
                "No local data substituted."
            )

        try:
            status, body = self._post("/search_tenders", {"query": query, "filters": filters or {}})
        except urllib.error.HTTPError as exc:
            raise AdapterUnavailableError(f"SIMAP bridge returned HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AdapterUnavailableError(f"SIMAP bridge call failed: {exc}") from exc

        if status != 200 or body.get("status") != "ok":
            raise AdapterUnavailableError(f"SIMAP bridge reported an error: {body.get('detail', body)!r}")

        markdown = body.get("markdown")
        if not isinstance(markdown, str):
            raise AdapterUnavailableError(f"SIMAP bridge returned an unexpected response shape: {body!r}")
        return _parse_search_tenders_markdown(markdown)

    def get_tender_details(self, project_id: str, publication_id: str, lang: str = "en") -> dict:
        """Relays to the bridge's `/get_tender` route (src/simap_bridge.py),
        which itself calls the real `get_tender_details` MCP tool via
        `SimapAdapter` — same transport reuse rationale as `search()`.
        Requires both real ids (see `Tender.publication_id`'s docstring);
        never raises on a normal "not found" response — that comes back as
        `{"available": False, "reason": ...}` from `_parse_tender_details_markdown`,
        same as the direct-stdio path. Only a genuine bridge/transport
        failure raises `AdapterUnavailableError`.
        """
        if not self.base_url:
            raise AdapterUnavailableError(
                f"SIMAP bridge is not configured — set {_ENV_BASE_URL} to a reachable bridge URL "
                "(deployed inside the NemoClaw sandbox, see deploy/simap-bridge/README.md). "
                "No local data substituted."
            )

        try:
            status, body = self._post(
                "/get_tender", {"project_id": project_id, "publication_id": publication_id, "lang": lang}
            )
        except urllib.error.HTTPError as exc:
            raise AdapterUnavailableError(f"SIMAP bridge returned HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AdapterUnavailableError(f"SIMAP bridge call failed: {exc}") from exc

        if status != 200 or body.get("status") != "ok":
            raise AdapterUnavailableError(f"SIMAP bridge reported an error: {body.get('detail', body)!r}")

        markdown = body.get("markdown")
        if not isinstance(markdown, str):
            raise AdapterUnavailableError(f"SIMAP bridge returned an unexpected response shape: {body!r}")
        return _parse_tender_details_markdown(markdown)
