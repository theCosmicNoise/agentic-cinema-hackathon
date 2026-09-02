"""
Agent 3 — Research. The evidence engine.

Every item that triage could not settle by rule arrives here, and leaves with
citations retrieved from the live web through Parallel's Search API. Items
triage flagged as high-stakes additionally escalate to Parallel's Task API for
multi-hop verification.

This is the agent that makes the report defensible. A model can guess whether
'Zenith Motors' is a live mark; only a lookup can show it, with sources an
insurer's counsel can follow.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from clearcut.agents.triage import TriageDecision
from clearcut.core.models import AgentEvent, ResearchEvidence
from clearcut.services.parallel_research import ParallelResearchService

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]


class ResearchAgent:
    name = "research"

    def __init__(
        self,
        service: ParallelResearchService | None = None,
        emit: EmitFn | None = None,
        max_workers: int = 6,
        deep_verify: bool = True,
    ):
        self._svc = service or ParallelResearchService()
        self._emit = emit or (lambda e: None)
        self._max_workers = max_workers
        self._deep_verify = deep_verify

    def run(self, decisions: list[TriageDecision]) -> dict[str, ResearchEvidence]:
        pending = [d for d in decisions if not d.settled_by_rule and d.plan]
        if not pending:
            return {}

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="start",
                message=f"Verifying {len(pending)} items against the live web via Parallel",
                payload={"items": len(pending)},
            )
        )

        evidence: dict[str, ResearchEvidence] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {pool.submit(self._one, d): d for d in pending}
            for fut in as_completed(futures):
                d = futures[fut]
                try:
                    ev = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Research failed for %s: %s", d.item.value, exc)
                    continue
                evidence[d.item.id] = ev

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=(
                    f"Gathered evidence on {len(evidence)} items "
                    f"({self._svc.search_calls} Search calls, "
                    f"{self._svc.task_calls} deep-research runs)"
                ),
                payload={
                    "searched": self._svc.search_calls,
                    "deep": self._svc.task_calls,
                },
            )
        )
        return evidence

    # ------------------------------------------------------------------ #
    def _one(self, decision: TriageDecision) -> ResearchEvidence:
        item, plan = decision.item, decision.plan
        assert plan is not None

        evidence = self._svc.search(
            item_id=item.id,
            objective=plan.objective,
            queries=plan.queries,
            mode=plan.mode,  # type: ignore[arg-type]
        )

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="item",
                message=f"{item.value} — {len(evidence.citations)} source(s)",
                payload={
                    "item_id": item.id,
                    "value": item.value,
                    "category": item.category.value,
                    "citations": len(evidence.citations),
                },
            )
        )

        # High-stakes items get a second, deeper pass. A wrong CLEAR on a real
        # person or a tarnished mark is the expensive kind of mistake.
        if self._deep_verify and plan.escalate:
            deep = self._svc.deep_research(item_id=item.id, objective=plan.objective)
            if deep.citations or not deep.findings.startswith("DEEP_RESEARCH_UNAVAILABLE"):
                seen = {c.url for c in evidence.citations}
                evidence.citations.extend(c for c in deep.citations if c.url not in seen)
                evidence.findings += f"\n\nDEEP VERIFICATION:\n{deep.findings}"
                evidence.escalated = True
                evidence.processor = f"{evidence.processor}+{deep.processor}"
                self._emit(
                    AgentEvent(
                        agent=self.name,
                        phase="escalated",
                        message=f"{item.value} — deep verification complete",
                        payload={"item_id": item.id, "value": item.value},
                    )
                )

        return evidence
