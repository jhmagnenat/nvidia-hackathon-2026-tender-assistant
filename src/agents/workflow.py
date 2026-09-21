"""WorkflowOrchestrator — search -> select -> retrieve -> extract -> qualify -> briefing.

Track C's orchestration entry point. Plain function/class composition, no
orchestration framework — see docs/architecture.md "Orchestration" and
IMPLEMENTATION_LOG.md Phase 0 for why (no NeMo Agent Toolkit / AIQ Blueprint /
MCP is reachable from this environment). Swapping in a framework later only
touches this file, not the agents it calls.

`run()`'s selection step is automatic (see `src.agents.tender_selection`):
every search result is scored on cloud-infrastructure / managed-services /
cybersecurity / overall-HPE-capability keyword fit, submission-deadline
feasibility, and document availability, and the best-scoring candidate is
analyzed — no more "just take the first search result". A human can still
force a specific candidate via `override_tender_id`, which is recorded on
the resulting briefing (`selection_mode="human_override"`) rather than
silently overwriting the automatic choice.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.agents import tender_selection
from src.agents.ingestion import extract_requirements
from src.agents.qualification import qualify_tender
from src.agents.retrieval import DocumentRetrievalTool
from src.agents.search import TenderSearchTool
from src.schemas.briefing import QualificationBriefing
from src.schemas.common import SelectionMode
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

    def run(
        self,
        query: str,
        filters: dict | None = None,
        as_of: date | None = None,
        override_tender_id: str | None = None,
    ) -> QualificationBriefing:
        """search -> score every candidate's relevance -> auto-select the best
        one (or a human override) -> retrieve -> extract -> qualify.

        Automatic by default: `src.agents.tender_selection.rank_candidates`
        scores every search result and the top-ranked one is analyzed
        (`selection_mode="auto"` on the returned briefing, with a
        `selection_reason` spelling out the winning score and runner-ups).
        Pass `override_tender_id` (must be one of this search's results) to
        force a specific candidate instead — this raises `ValueError` rather
        than silently analyzing a tender outside the current candidate set.
        """
        candidates = self.search(query, filters)
        if not candidates:
            raise ValueError(f"No tenders found for query: {query!r}")

        ranked = tender_selection.rank_candidates(candidates, self.hpe_profile, self.retrieval_tool, as_of=as_of)

        if override_tender_id is not None:
            selected = next((r for r in ranked if r.tender.id == override_tender_id), None)
            if selected is None:
                raise ValueError(
                    f"override_tender_id {override_tender_id!r} is not among this search's "
                    f"candidates: {[r.tender.id for r in ranked]}"
                )
            mode = SelectionMode.HUMAN_OVERRIDE
            reason = tender_selection.override_selection_reason(selected, ranked[0])
        else:
            selected = ranked[0]
            mode = SelectionMode.AUTO
            reason = tender_selection.auto_selection_reason(selected, ranked[1:])

        alternatives = tender_selection.build_alternatives(ranked, exclude_id=selected.tender.id)

        tender_data = extract_requirements(selected.tender, selected.documents)
        return qualify_tender(
            tender_data,
            self.hpe_profile,
            as_of=as_of,
            selection_mode=mode,
            selection_reason=reason,
            alternatives=alternatives,
        )
