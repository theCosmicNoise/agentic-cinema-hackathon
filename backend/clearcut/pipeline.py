"""
The clearance run.

Six agents in sequence, each narrowing what the next has to do:

    Breakdown   screenplay      -> flagged items
    Triage      items           -> rules settled + research plans
    Research    plans           -> cited evidence          (Parallel)
    Adjudicate  evidence        -> verdicts
    Substitute  blocked items   -> verified replacements   (closed loop)
    Report      everything      -> E&O-ready PDF

Every stage emits events as it goes, so the UI can show the network working
rather than a spinner. Failures degrade: a stage that cannot complete an item
leaves it unruled and visible, never silently dropped.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Callable

from clearcut.agents.adjudicate import AdjudicationAgent
from clearcut.agents.breakdown import BreakdownAgent
from clearcut.agents.report import ReportAgent
from clearcut.agents.research import ResearchAgent
from clearcut.agents.substitute import SubstitutionAgent
from clearcut.agents.triage import TriageAgent
from clearcut.core.config import get_settings
from clearcut.core.consistency import reconcile
from clearcut.core.ledger import ClearanceLedger
from clearcut.core.models import (
    Adjudication,
    AgentEvent,
    ClearanceFinding,
    ClearanceReport,
)
from clearcut.core.screenplay import ParsedScreenplay, load_screenplay, parse_screenplay
from clearcut.services.gemini_client import get_gemini
from clearcut.services.parallel_research import ParallelResearchService

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]


def run_clearance(
    source: str | Path | ParsedScreenplay,
    *,
    project_id: str = "default",
    emit: EmitFn | None = None,
    deep_verify: bool = True,
    substitute: bool = True,
    pdf_path: str | Path | None = None,
    use_ledger: bool = True,
) -> ClearanceReport:
    """Run a clearance pass and return the report.

    With `use_ledger`, only items that are new or whose depiction changed since
    the last draft are re-cleared; everything else carries its prior verdict
    forward. This is what makes a revision cost minutes instead of a re-buy.
    """
    emit = emit or (lambda e: None)
    started = time.time()

    script = (
        source
        if isinstance(source, ParsedScreenplay)
        else parse_screenplay(load_screenplay(source))
    )

    emit(
        AgentEvent(
            agent="pipeline",
            phase="start",
            message=f"Clearing {script.meta.title} — {script.total_pages} pages",
            payload={
                "title": script.meta.title,
                "pages": script.total_pages,
                "draft": script.meta.draft_label,
            },
        )
    )

    research_svc = ParallelResearchService()

    items = BreakdownAgent(emit=emit).run(script)

    draft_label = script.meta.draft_label or "Untitled draft"
    ledger = ClearanceLedger(project_id, get_settings().data_dir) if use_ledger else None
    carried: dict[str, Adjudication] = {}

    if ledger is not None:
        to_clear, reusable, diff = ledger.plan_revision(items, draft_label)
        if ledger.history:  # a prior draft exists — this is a revision
            s = ledger.savings(diff)
            emit(
                AgentEvent(
                    agent="ledger",
                    phase="diff",
                    message=(
                        f"Revision against {diff.from_draft}: "
                        f"{len(diff.unchanged)} items carry forward, "
                        f"{len(diff.added)} need re-clearing, "
                        f"{len(diff.removed)} removed"
                    ),
                    payload={
                        "from_draft": diff.from_draft,
                        "to_draft": diff.to_draft,
                        "added": diff.added,
                        "removed": diff.removed,
                        "unchanged_count": len(diff.unchanged),
                        **s,
                    },
                )
            )
            # Carry prior verdicts forward for everything unchanged.
            for item_id, entry in reusable.items():
                carried[item_id] = Adjudication(
                    item_id=item_id,
                    verdict=entry.verdict,
                    risk=entry.risk,
                    rationale=entry.rationale,
                    rule_applied="CARRIED_FORWARD",
                    citations=entry.citations,
                )
            items_to_process = to_clear
        else:
            items_to_process = items
    else:
        items_to_process = items

    decisions = TriageAgent(emit=emit).run(items_to_process)
    evidence = ResearchAgent(
        service=research_svc, emit=emit, deep_verify=deep_verify
    ).run(decisions)
    rulings = AdjudicationAgent(emit=emit).run(decisions, evidence)
    rulings.update(carried)

    for change in reconcile(items, rulings):
        emit(
            AgentEvent(
                agent="adjudicate",
                phase="reconciled",
                message=(
                    f"{change.value}: raised from {change.was.value} to "
                    f"{change.now.value} to match a related subject"
                ),
                payload={"item_id": change.item_id},
            )
        )

    subs = {}
    if substitute:
        # Only propose fixes for items actually processed this pass — a carried
        # verdict was already fixed or accepted in an earlier draft.
        subs = SubstitutionAgent(emit=emit, research=research_svc).run(
            items_to_process, rulings
        )

    if ledger is not None:
        ledger.record(items, rulings, draft_label)
        ledger.save()

    findings = [
        ClearanceFinding(
            item=it,
            evidence=evidence.get(it.id),
            adjudication=rulings.get(it.id),
            substitution=subs.get(it.id),
        )
        for it in items
    ]

    report = ClearanceReport(
        report_id=f"CC-{uuid.uuid4().hex[:8].upper()}",
        project_id=project_id,
        script=script.meta,
        findings=findings,
        elapsed_seconds=time.time() - started,
        parallel_calls=research_svc.total_calls,
        gemini_calls=get_gemini().total_calls,
    )

    if pdf_path:
        ReportAgent(emit=emit).render_pdf(report, pdf_path)

    blocking = len(report.blocking_items())
    emit(
        AgentEvent(
            agent="pipeline",
            phase="done",
            message=(
                f"{len(findings)} items cleared in {report.elapsed_seconds:.0f}s — "
                f"{blocking} blocking E&O"
            ),
            payload={
                "findings": len(findings),
                "blocking": blocking,
                "elapsed": report.elapsed_seconds,
                "counts": report.counts_by_verdict(),
            },
        )
    )
    return report
