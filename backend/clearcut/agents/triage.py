"""
Agent 2 — Triage.

Decides how each flagged item gets settled: by rule, or by evidence — and if by
evidence, exactly what question to put to the web.

The research objective is the highest-leverage text in the whole system. A vague
objective ("search for Zenith Motors") returns a pile of links. A clearance
objective ("is this a LIVE registered mark or an ACTIVE business, and in what
class of goods") returns the thing an adjudicator can actually rule on. So the
objectives are written per category, by hand, in the terms the legal theory for
that category turns on.

Triage is deliberately deterministic. The routing is knowable, and spending a
model call to re-derive it every run would be slower, costlier and less
reproducible than encoding it.
"""

from __future__ import annotations

from typing import Callable

from clearcut.core.models import AgentEvent, ClearableItem, ClearanceCategory
from clearcut.core.rules import RuleOutcome, apply_deterministic_rule

EmitFn = Callable[[AgentEvent], None]


class ResearchPlan:
    """What the Research Agent should ask, and how hard it should look."""

    def __init__(
        self,
        *,
        objective: str,
        queries: list[str],
        escalate: bool = False,
        mode: str = "fast",
    ):
        self.objective = objective
        self.queries = queries
        self.escalate = escalate
        self.mode = mode


# --------------------------------------------------------------------------- #
# Per-category objectives. Each is written around the legal theory that decides
# that category, not around the string itself.
# --------------------------------------------------------------------------- #
def _character_name(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: is '{v}' the name of a real, "
            f"identifiable living person — particularly anyone in the occupation or "
            f"setting described here: {ctx or 'unspecified'}? A name is a problem only "
            f"when a real person could plausibly claim the character is them. Report "
            f"any notable or public individual with this name and their occupation."
            + (
                " This character is shown committing or enabling wrongdoing, so any "
                "real match carries defamation exposure."
                if neg else ""
            )
        ),
        queries=[f'"{v}"', f'"{v}" notable person'],
        escalate=neg,
    )


def _business_name(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: is '{v}' a live registered US "
            f"trademark or an actively operating business? Report any USPTO "
            f"registration and its status, any operating company using this trade "
            f"name, and the industry it operates in. Context of use: {ctx or 'unspecified'}."
            + (
                " The business is depicted committing wrongdoing, so a real match "
                "raises trademark tarnishment and trade libel exposure."
                if neg else ""
            )
        ),
        queries=[f'"{v}" trademark USPTO', f'"{v}" company'],
        escalate=neg,
    )


def _brand_product(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: confirm the trademark owner of "
            f"'{v}' and whether the mark is famous. The product appears as: "
            f"{ctx or 'unspecified'}. Report the owner and whether the brand is known "
            f"to enforce against unlicensed depiction in film."
            + (
                " The brand is shown in a negative or unflattering context, which "
                "raises dilution by tarnishment risk."
                if neg else ""
            )
        ),
        queries=[f'"{v}" trademark owner', f'"{v}" brand film clearance'],
        escalate=neg,
    )


def _address(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: does the address '{v}' resolve to "
            f"a real, occupied premises? Report any business or residence at this "
            f"address. Used in the script as: {ctx or 'unspecified'}."
            + (
                " The location is depicted as a site of criminal activity, so a real "
                "occupant would have a grievance."
                if neg else ""
            )
        ),
        queries=[f'"{v}"', f'"{v}" business address'],
        escalate=neg,
    )


def _url_domain(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: is the domain '{v}' currently "
            f"registered and serving a live site? A domain shown on screen must not "
            f"belong to a real party, since viewers will visit it. Report the "
            f"registrant and what the site hosts."
        ),
        queries=[f'"{v}"', f"{v} website"],
        escalate=neg,
    )


def _email(v: str, ctx: str, neg: bool) -> ResearchPlan:
    domain = v.split("@")[-1] if "@" in v else v
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: is the domain '{domain}' a live "
            f"registered domain belonging to a real organisation? The script shows "
            f"the address '{v}' on screen, so a live domain means a real mailbox may "
            f"receive viewer mail."
        ),
        queries=[f'"{domain}"', f"{domain} company"],
        escalate=neg,
    )


def _music_cue(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture music clearance: identify the songwriter, publisher "
            f"and recording owner of '{v}', and its copyright status. A needle-drop "
            f"needs BOTH a synchronisation licence from the publisher and a master "
            f"use licence from the label, unless the work is in the public domain. "
            f"Report whether it is in the public domain and who controls the rights."
        ),
        queries=[f'"{v}" songwriter publisher', f'"{v}" copyright public domain'],
        escalate=True,  # two separate licences ride on this — worth the deeper look
    )


def _artwork(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture clearance: identify the artist, creation date and "
            f"current copyright status of the artwork '{v}'. Determine whether it has "
            f"entered the public domain, and if not, who controls reproduction rights. "
            f"Visible on camera as: {ctx or 'unspecified'}."
        ),
        queries=[f'"{v}" artist copyright status', f'"{v}" public domain'],
        escalate=True,
    )


def _real_person(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: identify the real person '{v}'. "
            f"Report whether they are living or deceased and, if deceased, the year. "
            f"Right of publicity survives death in several US states, and defamation "
            f"claims do not. Referenced in the script as: {ctx or 'unspecified'}."
            + (" The reference is unflattering, raising defamation exposure." if neg else "")
        ),
        queries=[f'"{v}"', f'"{v}" died biography'],
        escalate=True,
    )


def _organization(v: str, ctx: str, neg: bool) -> ResearchPlan:
    return ResearchPlan(
        objective=(
            f"For motion picture script clearance: is '{v}' a real, currently "
            f"operating institution or company? Report what it is, who owns the name, "
            f"and whether it is known to defend its mark. Depicted in the script as: "
            f"{ctx or 'unspecified'}."
            + (
                " CRITICAL: the organisation is portrayed as complicit in wrongdoing. "
                "A real match creates direct defamation and trade libel exposure."
                if neg else ""
            )
        ),
        queries=[f'"{v}"', f'"{v}" trademark'],
        escalate=neg,
    )


def _generic(label: str):
    def plan(v: str, ctx: str, neg: bool) -> ResearchPlan:
        return ResearchPlan(
            objective=(
                f"For motion picture script clearance, assess {label} '{v}'. Is there "
                f"a real-world referent with rights a production would need to respect? "
                f"Used in the script as: {ctx or 'unspecified'}."
                + (" Depicted negatively, raising defamation exposure." if neg else "")
            ),
            queries=[f'"{v}"', f'"{v}" trademark owner'],
            escalate=neg,
        )
    return plan


_PLANNERS: dict[ClearanceCategory, Callable[[str, str, bool], ResearchPlan]] = {
    ClearanceCategory.CHARACTER_NAME: _character_name,
    ClearanceCategory.BUSINESS_NAME: _business_name,
    ClearanceCategory.BRAND_PRODUCT: _brand_product,
    ClearanceCategory.ADDRESS: _address,
    ClearanceCategory.URL_DOMAIN: _url_domain,
    ClearanceCategory.EMAIL: _email,
    ClearanceCategory.MUSIC_CUE: _music_cue,
    ClearanceCategory.ARTWORK: _artwork,
    ClearanceCategory.REAL_PERSON: _real_person,
    ClearanceCategory.ORGANIZATION: _organization,
    ClearanceCategory.LICENSE_PLATE: _generic("the vehicle registration plate"),
    ClearanceCategory.PRINT_MEDIA: _generic("the publication masthead"),
    ClearanceCategory.LOGO_SIGNAGE: _generic("the logo or signage"),
    ClearanceCategory.LOCATION_NAME: _generic("the named venue"),
    ClearanceCategory.DEPICTION_RISK: _generic("the depicted entity"),
}


class TriageDecision:
    def __init__(
        self,
        item: ClearableItem,
        *,
        rule: RuleOutcome | None = None,
        plan: ResearchPlan | None = None,
    ):
        self.item = item
        self.rule = rule
        self.plan = plan

    @property
    def settled_by_rule(self) -> bool:
        return self.rule is not None


class TriageAgent:
    name = "triage"

    def __init__(self, emit: EmitFn | None = None):
        self._emit = emit or (lambda e: None)

    def run(self, items: list[ClearableItem]) -> list[TriageDecision]:
        decisions: list[TriageDecision] = []
        by_rule = 0

        for item in items:
            rule = apply_deterministic_rule(item.category, item.value)
            if rule is not None:
                by_rule += 1
                decisions.append(TriageDecision(item, rule=rule))
                continue

            planner = _PLANNERS.get(item.category, _generic("the item"))
            plan = planner(item.value, item.context or "", item.is_depicted_negatively)
            item.research_plan = plan.objective
            decisions.append(TriageDecision(item, plan=plan))

        needs_research = len(decisions) - by_rule
        escalated = sum(1 for d in decisions if d.plan and d.plan.escalate)
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=(
                    f"{by_rule} settled by rule, {needs_research} routed to research "
                    f"({escalated} flagged for deep verification)"
                ),
                payload={
                    "by_rule": by_rule,
                    "needs_research": needs_research,
                    "escalated": escalated,
                },
            )
        )
        return decisions
