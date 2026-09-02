"""
Agent 5 — Substitution. The closed loop.

A clearance house tells a production 'no'. It does not tell them what to use
instead, because proposing a replacement means researching the replacement, and
that is another billable pass. So the producer guesses, and the next draft comes
back with a fresh set of problems.

This agent proposes a replacement and then puts that replacement through the
same research and adjudication the original failed — and keeps going until one
comes back clean. A proposal that has not itself been cleared is worth nothing,
so an unverified candidate is never presented as a fix.

Candidates are generated in a single batched call and verified in order, so the
common case costs one generation plus one verification.
"""

from __future__ import annotations

import logging
from typing import Callable

from pydantic import BaseModel, Field

from clearcut.agents.adjudicate import AdjudicationAgent
from clearcut.agents.triage import TriageAgent
from clearcut.core.models import (
    Adjudication,
    AgentEvent,
    ClearableItem,
    ClearanceCategory,
    Substitution,
    Verdict,
)
from clearcut.services.gemini_client import get_gemini
from clearcut.services.parallel_research import ParallelResearchService

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

# Verdicts that mean the replacement is usable as written.
_ACCEPTABLE = {Verdict.CLEAR, Verdict.CLEAR_WITH_CAUTION}

SYSTEM = """You propose replacement names for a motion picture script that has failed
clearance. Your replacements must be inventable, not merely different.

RULES
- Preserve what the original was doing dramatically: same register, same era, same
  ethnicity or regional flavour, same syllable count where it affects dialogue rhythm.
  A replacement that changes the character is a rewrite, not a clearance fix.
- Avoid anything likely to have a real-world referent. Prefer invented compounds and
  uncommon-but-plausible constructions over common surnames or real place names.
- For businesses, avoid descriptive geographic terms that real companies cluster around.
- For phone numbers, use the 555-0100 to 555-0199 reserved block.
- For domains and emails, prefer clearly invented second-level names.
- Never propose a real, famous, or historically loaded name.

Return exactly 3 candidates, best first. Give a one-line reason for each explaining what
it preserves from the original.
"""


class _Candidate(BaseModel):
    value: str = Field(description="The proposed replacement")
    reason: str = Field(description="What it preserves from the original")


class SubstitutionAgent:
    name = "substitute"

    def __init__(
        self,
        emit: EmitFn | None = None,
        research: ParallelResearchService | None = None,
        adjudicator: AdjudicationAgent | None = None,
        max_candidates: int = 3,
    ):
        self._emit = emit or (lambda e: None)
        self._svc = research or ParallelResearchService()
        self._adj = adjudicator or AdjudicationAgent(emit=lambda e: None)
        self._triage = TriageAgent(emit=lambda e: None)
        self._max = max_candidates

    def run(
        self,
        items: list[ClearableItem],
        rulings: dict[str, Adjudication],
    ) -> dict[str, Substitution]:
        targets = [
            it for it in items
            if rulings.get(it.id) and rulings[it.id].verdict == Verdict.MUST_CHANGE
        ]
        if not targets:
            return {}

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="start",
                message=f"Proposing verified replacements for {len(targets)} blocked items",
                payload={"items": len(targets)},
            )
        )

        out: dict[str, Substitution] = {}
        for item in targets:
            try:
                out[item.id] = self._fix(item, rulings[item.id])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Substitution failed for %s: %s", item.value, exc)
                out[item.id] = Substitution(
                    item_id=item.id,
                    original=item.value,
                    proposed="",
                    verified_clear=False,
                    attempts=0,
                )

        verified = sum(1 for s in out.values() if s.verified_clear)
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=f"{verified}/{len(out)} replacements verified clear",
                payload={"verified": verified, "total": len(out)},
            )
        )
        return out

    # ------------------------------------------------------------------ #
    def _fix(self, item: ClearableItem, ruling: Adjudication) -> Substitution:
        candidates = self._propose(item, ruling)
        rejected: list[str] = []

        for attempt, cand in enumerate(candidates[: self._max], start=1):
            self._emit(
                AgentEvent(
                    agent=self.name,
                    phase="candidate",
                    message=f"{item.value} -> testing '{cand.value}'",
                    payload={"item_id": item.id, "candidate": cand.value, "attempt": attempt},
                )
            )

            # Re-clear the candidate through the same pipeline the original failed.
            probe = item.model_copy(
                update={"id": f"{item.id}_sub{attempt}", "value": cand.value}
            )
            decision = self._triage.run([probe])[0]

            if decision.settled_by_rule and decision.rule:
                verdict = decision.rule.verdict
                evidence = None
            else:
                assert decision.plan is not None
                evidence = self._svc.search(
                    item_id=probe.id,
                    objective=decision.plan.objective,
                    queries=decision.plan.queries,
                )
                verdict = self._adj.run([decision], {probe.id: evidence})[probe.id].verdict

            if verdict in _ACCEPTABLE:
                self._emit(
                    AgentEvent(
                        agent=self.name,
                        phase="verified",
                        message=f"{item.value} -> '{cand.value}' verified {verdict.value}",
                        payload={
                            "item_id": item.id,
                            "original": item.value,
                            "proposed": cand.value,
                            "verdict": verdict.value,
                            "attempts": attempt,
                        },
                    )
                )
                return Substitution(
                    item_id=item.id,
                    original=item.value,
                    proposed=cand.value,
                    verified_clear=True,
                    verification_evidence=evidence,
                    verification_verdict=verdict,
                    attempts=attempt,
                    rejected_candidates=rejected,
                )

            rejected.append(cand.value)
            self._emit(
                AgentEvent(
                    agent=self.name,
                    phase="rejected",
                    message=f"'{cand.value}' rejected ({verdict.value}) — trying next",
                    payload={"item_id": item.id, "candidate": cand.value},
                )
            )

        # Every candidate failed. Say so rather than presenting an unverified fix.
        return Substitution(
            item_id=item.id,
            original=item.value,
            proposed=candidates[0].value if candidates else "",
            verified_clear=False,
            attempts=len(rejected),
            rejected_candidates=rejected,
        )

    def _propose(self, item: ClearableItem, ruling: Adjudication) -> list[_Candidate]:
        quote = item.locations[0].quote if item.locations else ""
        prompt = (
            f"ORIGINAL: {item.value}\n"
            f"CATEGORY: {item.category.value}\n"
            f"WHY IT FAILED CLEARANCE: {ruling.rationale}\n"
            f"HOW IT IS USED: {item.context or 'unspecified'}\n"
            f'AS WRITTEN ON THE PAGE: "{quote[:200]}"\n\n'
            f"Propose 3 replacements."
        )
        raw = get_gemini().generate_structured(
            prompt=prompt,
            schema=list[_Candidate],
            system=SYSTEM,
            temperature=0.6,  # some spread, so candidates differ meaningfully
            thinking_budget=0,
        )
        out: list[_Candidate] = []
        for row in raw or []:
            try:
                out.append(_Candidate.model_validate(row))
            except Exception:  # noqa: BLE001, S112
                continue
        return out
