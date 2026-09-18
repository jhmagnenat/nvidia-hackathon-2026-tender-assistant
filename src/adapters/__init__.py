"""Adapters isolate the business logic (src/agents/) from any specific search or
document-retrieval provider (SIMAP MCP, Tavily MCP, or the local sample fallback).

Every adapter exposes the same shape: a `name`, an `available` check, and the
actual operation. Callers should never assume a specific provider is present —
always go through `get_search_adapter()` / `get_document_adapter()`, which pick
the best available one and guarantee a working local fallback.
"""


class AdapterUnavailableError(RuntimeError):
    """Raised when an adapter is selected/called but its backing service isn't reachable."""
