"""
Agent 4 — Adjudication.

Turns evidence into a ruling. This is the line that appears in the delivered
report and the one an E&O carrier's counsel reads, so three properties matter
more than raw accuracy:

1. It rules on the evidence, not on recall. If Parallel found no live mark, the
   ruling says so and cites the absence; it never asserts a fact no source
   supports.
2. It applies the legal theory for the category. A famous brand glimpsed on a
   shelf and the same brand shown causing a death are the same trademark and
   completely different clearance outcomes — the difference is depiction, not
   the mark.
3. It is conservative in one direction only. Over-flagging costs a producer a
   name change; under-flagging costs them the film's insurance.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from pydantic import BaseModel, Field

from clearcut.agents.triage import TriageDecision
from clearcut.core.models import (
    Adjudication,
    AgentEvent,
    Citation,
    ClearableItem,
    ClearanceCategory,
    ResearchEvidence,
    RiskLevel,
    Verdict,
)
from clearcut.services.gemini_client import get_gemini

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

SYSTEM = """You are the adjudicating attorney at a motion picture script clearance house.
You issue the ruling that an Errors & Omissions carrier relies on to bind coverage.

You are given one flagged item, how it is used in the screenplay, and the evidence
retrieved from the live web. You must issue one of five verdicts.

VERDICTS
- clear: no meaningful exposure. Use it as written.
- clear_with_caution: usable, but the production should be told why it carries residual
  risk (e.g. a real but unrelated business shares the name).
- must_change: the item creates real exposure and the script must be revised.
- license_required: the item is usable ONLY with a licence from a rights holder.
- legal_review: the evidence is genuinely ambiguous and a human attorney must decide.

THE GOVERNING PRINCIPLE
Exposure is the product of TWO things: whether a real-world referent exists, AND how the
script treats it. A real company mentioned neutrally is usually fine. The same company
shown committing fraud is defamation and trademark tarnishment. Weigh both. Never rule on
the existence of a match alone.

CATEGORY STANDARDS
- character_name: Common names are not owned. Rule must_change only when a real,
  identifiable person plausibly matches AND the character is negative or shares the
  person's occupation/locale. A surname alone with no negative depiction is clear.
- business_name / organization: A live registered mark or operating business that is
  depicted negatively is must_change. Neutral depiction of a real business is
  clear_with_caution. No real referent found is clear.
- brand_product: Famous marks used incidentally and neutrally are generally clear —
  depicting real products is normal filmmaking and nominative use. A famous mark shown
  as defective, dangerous, or causing harm is must_change (dilution by tarnishment).
- music_cue: Unless the work is in the public domain, a needle-drop is license_required
  and needs BOTH a synchronisation licence (publisher) and a master use licence (label).
  Say which rights holders. Public domain is clear.
- artwork: Public domain is clear. Otherwise license_required, naming the rights holder.
  Do not decide public domain by publication date alone. US works published 1929-1963
  entered the public domain if copyright was never renewed after the initial 28-year
  term, which is common. Follow the evidence on renewal, not the year.
- real_person: A living person depicted negatively is must_change (defamation). Neutral
  or historical reference to a public figure is generally clear. For the deceased,
  defamation does not survive but right of publicity does in several US states — say so.
- address / url_domain / email / license_plate: If it resolves to something real, it is
  must_change. Viewers visit URLs and dial numbers they see on screen. Absence of
  evidence of a real referent is a reasonable basis for clear here.
- print_media / logo_signage: Real masthead or logo shown neutrally is
  clear_with_caution; shown negatively is must_change.

EVIDENCE DISCIPLINE
- Cite the specific sources that drove your ruling. Do not cite sources you did not rely on.
- If the evidence is thin or off-target, say so plainly and prefer legal_review over a
  confident guess.
- The rationale is read by a producer, not a machine. Two or three sentences, concrete,
  naming what was found. No hedging boilerplate.

Set rule_applied to a short uppercase identifier for the standard you applied, e.g.
TRADEMARK_TARNISHMENT, DEFAMATION_LIVING_PERSON, PUBLIC_DOMAIN_ARTWORK,
SYNC_AND_MASTER_REQUIRED, NO_REAL_REFERENT, LIVE_DOMAIN_REGISTERED.
"""


class _Ruling(BaseModel):
    verdict: str = Field(description="clear|clear_with_caution|must_change|license_required|legal_review")
    risk: str = Field(description="none|low|medium|high|critical")
    rationale: str = Field(description="2-3 concrete sentences for a producer")
    rule_applied: str = Field(default="", description="Short uppercase standard id")
    relied_on_urls: list[str] = Field(default_factory=list)
    requires_license_from: str = Field(default="")


class AdjudicationAgent:
    name = "adjudicate"

    def __init__(self, emit: EmitFn | None = None, max_workers: int = 3):
        self._emit = emit or (lambda e: None)
        self._max_workers = max_workers

    def run(
        self,
        decisions: list[TriageDecision],
        evidence: dict[str, ResearchEvidence],
    ) -> dict[str, Adjudication]:
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="start",
                message=f"Adjudicating {len(decisions)} items",
                payload={"items": len(decisions)},
            )
        )

        rulings: dict[str, Adjudication] = {}
        needs_model: list[TriageDecision] = []

        # Rule-settled items already carry their verdict — no model call needed.
        for d in decisions:
            if d.settled_by_rule and d.rule:
                rulings[d.item.id] = Adjudication(
                    item_id=d.item.id,
                    verdict=d.rule.verdict,
                    risk=d.rule.risk,
                    rationale=d.rule.rationale,
                    rule_applied=d.rule.rule_id,
                    requires_license_from=d.rule.requires_license_from,
                )
                self._emit(
                    AgentEvent(
                        agent=self.name,
                        phase="item",
                        message=f"{d.item.value} — {d.rule.verdict.value} (by rule)",
                        payload={
                            "item_id": d.item.id,
                            "value": d.item.value,
                            "verdict": d.rule.verdict.value,
                            "by_rule": True,
                        },
                    )
                )
            else:
                needs_model.append(d)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._rule_on, d.item, evidence.get(d.item.id)): d
                for d in needs_model
            }
            for fut in as_completed(futures):
                d = futures[fut]
                try:
                    adj = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Adjudication failed for %s: %s", d.item.value, exc)
                    adj = self._fallback(d.item, exc)
                rulings[d.item.id] = adj
                self._emit(
                    AgentEvent(
                        agent=self.name,
                        phase="item",
                        message=f"{d.item.value} — {adj.verdict.value} ({adj.risk.value})",
                        payload={
                            "item_id": d.item.id,
                            "value": d.item.value,
                            "verdict": adj.verdict.value,
                            "risk": adj.risk.value,
                        },
                    )
                )

        blocking = sum(
            1 for a in rulings.values()
            if a.verdict in {Verdict.MUST_CHANGE, Verdict.LICENSE_REQUIRED, Verdict.LEGAL_REVIEW}
        )
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=f"{len(rulings)} ruled, {blocking} blocking E&O",
                payload={"ruled": len(rulings), "blocking": blocking},
            )
        )
        return rulings

    # ------------------------------------------------------------------ #
    def _rule_on(
        self, item: ClearableItem, evidence: ResearchEvidence | None
    ) -> Adjudication:
        prompt = self._build_prompt(item, evidence)
        raw = get_gemini().generate_structured(
            prompt=prompt,
            schema=_Ruling,
            system=SYSTEM,
            temperature=0.0,
            thinking_budget=0,
        )
        ruling = _Ruling.model_validate(raw)

        # Attach only the citations the ruling actually leaned on; fall back to
        # the full evidence set if the model named none.
        relied = set(ruling.relied_on_urls)
        pool = evidence.citations if evidence else []
        cited = [c for c in pool if c.url in relied] or pool[:3]

        return Adjudication(
            item_id=item.id,
            verdict=_to_verdict(ruling.verdict),
            risk=_to_risk(ruling.risk),
            rationale=ruling.rationale.strip(),
            rule_applied=ruling.rule_applied.strip() or None,
            citations=cited,
            requires_license_from=ruling.requires_license_from.strip() or None,
        )

    def _build_prompt(
        self, item: ClearableItem, evidence: ResearchEvidence | None
    ) -> str:
        lines = [
            f"ITEM: {item.value}",
            f"CATEGORY: {item.category.value}",
            f"DEPICTED NEGATIVELY: {'YES' if item.is_depicted_negatively else 'no'}",
        ]
        if item.context:
            lines.append(f"HOW IT IS USED: {item.context}")

        lines.append("\nAPPEARS AT:")
        for loc in item.locations[:6]:
            scene = f" sc.{loc.scene_number}" if loc.scene_number else ""
            lines.append(f'  p{loc.page}{scene}: "{loc.quote[:180]}"')

        lines.append("\nEVIDENCE FROM LIVE WEB RESEARCH:")
        if evidence and evidence.citations:
            lines.append(f"(objective: {evidence.objective[:220]})\n")
            for i, c in enumerate(evidence.citations[:8], 1):
                lines.append(f"[{i}] {c.title or '(untitled)'}")
                lines.append(f"    URL: {c.url}")
                if c.excerpt:
                    lines.append(f"    {c.excerpt[:400]}")
        else:
            lines.append(
                "  No sources retrieved. Weigh this as absence of evidence, which for "
                "addresses, domains and plates supports a clear ruling, but for names "
                "and marks may mean the search simply failed — prefer legal_review if "
                "the item is high-stakes."
            )

        lines.append("\nIssue your ruling.")
        return "\n".join(lines)

    def _fallback(self, item: ClearableItem, exc: Exception) -> Adjudication:
        """Never silently drop an item — surface it for human review."""
        return Adjudication(
            item_id=item.id,
            verdict=Verdict.LEGAL_REVIEW,
            risk=RiskLevel.MEDIUM,
            rationale=(
                f"Automated adjudication could not complete for '{item.value}' "
                f"({type(exc).__name__}). This item is unruled and must be reviewed "
                f"by counsel before delivery."
            ),
            rule_applied="ADJUDICATION_UNAVAILABLE",
        )


def _to_verdict(raw: str) -> Verdict:
    try:
        return Verdict(raw.strip().lower())
    except ValueError:
        return Verdict.LEGAL_REVIEW


def _to_risk(raw: str) -> RiskLevel:
    try:
        return RiskLevel(raw.strip().lower())
    except ValueError:
        return RiskLevel.MEDIUM
