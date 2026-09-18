"""CLI entry point — Track C owns this.

Wires: search -> select -> retrieve -> extract -> qualify -> briefing (+
optional human-review recording), via src.agents.workflow.WorkflowOrchestrator.
Plain composition, no orchestration framework — see docs/architecture.md
"Orchestration" and IMPLEMENTATION_LOG.md Phase 0 for why.

Examples:
    python -m src.pipeline search "cloud infrastructure managed services cybersecurity"
    python -m src.pipeline run "cloud infrastructure managed services cybersecurity"
    python -m src.pipeline analyze cloud-infra-2026 --out briefing.json
    python -m src.pipeline analyze cloud-infra-2026 --approve --reviewer "J. Doe" --notes "Looks good"
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.agents.feedback import record_feedback
from src.agents.workflow import DEFAULT_HPE_PROFILE_PATH, WorkflowOrchestrator, load_hpe_profile
from src.schemas.briefing import HumanDecision
from src.schemas.tender import Tender

_DECISION_FLAGS = {
    "approve": HumanDecision.APPROVED,
    "reject": HumanDecision.REJECTED,
    "more_research": HumanDecision.MORE_RESEARCH,
}


def _print_tenders(tenders: list[Tender]) -> None:
    if not tenders:
        print("No tenders found.")
        return
    for tender in tenders:
        deadline = tender.submission_deadline.isoformat() if tender.submission_deadline else "UNKNOWN"
        print(f"{tender.id}\t{tender.title}\t{tender.buyer or 'UNKNOWN'}\tdeadline={deadline}")


def _emit(briefing, out: Path | None) -> None:
    output = briefing.model_dump_json(indent=2)
    if out:
        out.write_text(output, encoding="utf-8")
        print(f"Wrote briefing to {out}")
    else:
        print(output)


def _maybe_record_review(briefing, args) -> None:
    for flag, decision in _DECISION_FLAGS.items():
        if getattr(args, flag, False):
            record_feedback(briefing, decision, reviewer=args.reviewer, notes=args.notes)
            print(f"Recorded human review: {decision.value}")
            return


def _add_review_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--approve", action="store_true", help="Record an 'approved' human review")
    group.add_argument("--reject", action="store_true", help="Record a 'rejected' human review")
    group.add_argument("--more-research", dest="more_research", action="store_true", help="Record a 'more_research' human review")
    parser.add_argument("--reviewer", default=None, help="Reviewer name for the recorded human review")
    parser.add_argument("--notes", default=None, help="Notes for the recorded human review")


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", type=Path, default=DEFAULT_HPE_PROFILE_PATH, help="Path to the HPE profile JSON")
    common.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="Override 'today' for deadline scoring (YYYY-MM-DD)"
    )

    parser = argparse.ArgumentParser(description="Agentic Tender Assistant — HPE qualification pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser(
        "search", parents=[common], help="Search tenders (SIMAP/Tavily if available, else local sample)"
    )
    search_parser.add_argument("query")

    analyze_parser = subparsers.add_parser("analyze", parents=[common], help="Analyze one tender by id and produce a briefing")
    analyze_parser.add_argument("tender_id")
    analyze_parser.add_argument("--out", type=Path, default=None)
    _add_review_flags(analyze_parser)

    run_parser = subparsers.add_parser("run", parents=[common], help="Search, auto-select the top result, and produce a briefing")
    run_parser.add_argument("query")
    run_parser.add_argument("--out", type=Path, default=None)
    _add_review_flags(run_parser)

    args = parser.parse_args()
    orchestrator = WorkflowOrchestrator(hpe_profile=load_hpe_profile(args.profile))

    if args.command == "search":
        _print_tenders(orchestrator.search(args.query))
        return

    if args.command == "analyze":
        tender = next((t for t in orchestrator.search("") if t.id == args.tender_id), None)
        if tender is None:
            raise SystemExit(f"Unknown tender id: {args.tender_id!r}")
        briefing = orchestrator.analyze_tender(tender, as_of=args.as_of)
        _maybe_record_review(briefing, args)
        _emit(briefing, args.out)
        return

    if args.command == "run":
        briefing = orchestrator.run(args.query, as_of=args.as_of)
        _maybe_record_review(briefing, args)
        _emit(briefing, args.out)
        return


if __name__ == "__main__":
    main()
