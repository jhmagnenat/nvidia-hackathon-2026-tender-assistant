"""WorkflowOrchestrator — search -> select -> retrieve -> extract -> qualify -> briefing.

Track C's orchestration entry point. Plain function/class composition, no
orchestration framework — see docs/architecture.md "Orchestration" and
IMPLEMENTATION_LOG.md Phase 0 for why (no NeMo Agent Toolkit / AIQ Blueprint /
MCP is reachable from this environment). Swapping in a framework later only
touches this file, not the agents it calls.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.agents.ingestion import extract_requirements
from src.agents.qualification import qualify_tender
from src.agents.retrieval import DocumentRetrievalTool
from src.agents.search import TenderSearchTool
from src.schemas.briefing import QualificationBriefing
from src.schemas.hpe_profile import HPEProfile
from src.schemas.tender import Tender

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HPE_PROFILE_PATH = REPO_ROOT / "data" / "hpe_profile.json"


def load_hpe_profile(path: Path = DEFAULT_HPE_PROFILE_PATH) -> HPEProfile:
    return HPEProfile.model_validate_json(path.read_text(encoding="utf-8"))


class WorkflowOrchestrator:
    def __init__(
        self,
        search_tool: TenderSearchTool | None = None,
        retrieval_tool: DocumentRetrievalTool | None = None,
        hpe_profile: HPEProfile | None = None,
    ):
        self.search_tool = search_tool or TenderSearchTool()
        self.retrieval_tool = retrieval_tool or DocumentRetrievalTool()
        self.hpe_profile = hpe_profile or load_hpe_profile()

    def search(self, query: str, filters: dict | None = None) -> list[Tender]:
        return self.search_tool.search_tenders(query, filters)

    def analyze_tender(self, tender: Tender, as_of: date | None = None) -> QualificationBriefing:
        documents = self.retrieval_tool.retrieve_documents(tender)
        tender_data = extract_requirements(tender, documents)
        return qualify_tender(tender_data, self.hpe_profile, as_of=as_of)

    def run(self, query: str, filters: dict | None = None, as_of: date | None = None) -> QualificationBriefing:
        """search -> select the top-ranked result -> retrieve -> extract -> qualify."""
        results = self.search(query, filters)
        if not results:
            raise ValueError(f"No tenders found for query: {query!r}")
        return self.analyze_tender(results[0], as_of=as_of)
