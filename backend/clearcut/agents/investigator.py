"""
The Investigator — a real ADK agent, not a fixed pipeline stage.

Every earlier version of this step ran the same lookup for every item: one
Parallel search, plus a deep pass when a hardcoded flag was set. That is a
script, and it wastes effort in both directions. Clearing a common surname does
not need multi-hop research. Clearing a hospital shown falsifying records needs
considerably more than six search results.

So the decision moves into the agent. It is given Parallel's capabilities as
tools and the clearance standard for each category, and it chooses: how many
searches, whether to escalate to deep research, whether to go looking for
same-named entities. The reasoning is visible in the transcript, which matters
because the reviewer downstream has to trust the evidence.

Tools are plain callables; ADK derives their schemas from the signatures and
docstrings, so the docstrings here are the tool contract and are written for the
model to read.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from clearcut.core.models import Citation, ResearchEvidence
from clearcut.services.parallel_research import ParallelResearchService

logger = logging.getLogger(__name__)

# The tools are module-level callables so ADK can introspect them, but each run
# needs its own service and collector. A context local keeps them apart.
_local = threading.local()


def _svc() -> ParallelResearchService:
    return _local.service


def _collect(evidence: ResearchEvidence) -> None:
    _local.collected.append(evidence)


def bind_context(service: ParallelResearchService) -> list[ResearchEvidence]:
    """Attach a service to this thread and return the list tools will fill."""
    _local.service = service
    _local.collected = []
    return _local.collected


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def web_search(objective: str, queries: list[str]) -> dict[str, Any]:
    """Search the live web and return sources with excerpts.

    Use this first for almost every item. It is fast and cheap. Good for
    establishing whether a real-world referent exists at all: a registered
    trademark, an operating business, a live domain, an occupied address, a
    notable person of that name.

    Args:
        objective: What you need to establish, written as a question a
            researcher could answer. Frame it around the legal theory, not the
            string. Good: "Is 'Halloran Freight' a live registered US trademark
            or an actively operating business, and in what industry?"
        queries: Two or three search queries likely to surface the answer.
            Quote exact names.
    """
    ev = _svc().search(item_id="adk", objective=objective, queries=queries)
    _collect(ev)
    return {
        "sources_found": len(ev.citations),
        "findings": ev.findings[:2500],
        "urls": [c.url for c in ev.citations[:8]],
    }


def deep_research(objective: str) -> dict[str, Any]:
    """Run multi-hop research when a single search cannot settle the question.

    Slower and more expensive than web_search, so use it only when the stakes
    or the ambiguity justify it: a real person or organisation the script shows
    committing wrongdoing, a music cue whose rights chain must be traced to
    publisher and label, an artwork whose copyright renewal decides whether it
    is public domain, or a case where web_search returned contradictory or
    off-target sources.

    Args:
        objective: The full question, including what you already learned from
            web_search and what specifically remains unresolved.
    """
    ev = _svc().deep_research(item_id="adk", objective=objective)
    _collect(ev)
    return {
        "sources_found": len(ev.citations),
        "findings": ev.findings[:4000],
        "urls": [c.url for c in ev.citations[:8]],
    }


def find_same_named_entities(objective: str, entity_type: str) -> dict[str, Any]:
    """Enumerate real entities sharing a name, when 'does one exist' is not enough.

    Use when the clearance question is about how many real referents there are
    and what they do, rather than whether any exists. A surname shared by
    thousands of private individuals is clearable; the same surname belonging to
    one prominent person in the character's own profession is not.

    Args:
        objective: What to enumerate, e.g. "operating US businesses trading as
            'Coastal Dental Group'".
        entity_type: Either "companies" or "people".
    """
    ev = _svc().search(
        item_id="adk",
        objective=f"Enumerate {entity_type} matching: {objective}",
        queries=[objective, f"{objective} list"],
        mode="advanced",
    )
    _collect(ev)
    return {
        "sources_found": len(ev.citations),
        "findings": ev.findings[:2500],
        "urls": [c.url for c in ev.citations[:8]],
    }


INSTRUCTION = """You are a clearance researcher at a motion picture clearance house.
You are given one item flagged in a screenplay. Your job is to gather the evidence an
adjudicator needs, then stop.

DECIDE HOW HARD TO LOOK. This is the judgement you are here for.

Always start with web_search.

Then you MUST call deep_research when any of these hold, because a single search
cannot resolve them and a wrong CLEAR here is the expensive mistake:
- music_cue: the sync and master rights sit with different parties and both must be
  named, so one search is never enough.
- artwork: whether copyright was RENEWED decides public domain. A search that only
  establishes the creation date has not answered the question.
- real_person, organization, business_name or brand_product WHERE THE ITEM IS
  DEPICTED NEGATIVELY: you must establish not just that the entity is real, but
  enough about it to support a defamation or tarnishment assessment.
- web_search came back thin, off-target, or contradictory.

Call find_same_named_entities when the question is "how many real referents exist and
what do they do" rather than "does one exist" — typically a surname or a descriptive
business name where the count is what decides clearability.

Otherwise stop after web_search. A common surname with a neutral depiction does not
need three tools, and over-researching a clear item wastes the budget that the hard
items need.

WRITE GOOD OBJECTIVES. The objective you pass is the whole quality of the result.
Frame it around the legal theory for the category:
- business or brand: is the mark live and registered, who owns it, what industry
- character name: is there a real identifiable person, especially in the same
  occupation or locale as the character
- address, domain, email, plate: does it resolve to something real and occupied
- music: songwriter, publisher, recording owner, and public domain status
- artwork: artist, date, and whether copyright was renewed
- real person: living or deceased, and if deceased, the year
- organisation: is it real, currently operating, and does it defend its mark

WHEN THE SCRIPT DEPICTS THE SUBJECT NEGATIVELY, say so in your objective. A real
company named in passing and the same company shown committing fraud are the same
name and completely different clearance outcomes, and the adjudicator needs evidence
addressed to that.

FINISH by summarising what you established in three or four sentences: whether a real
referent exists, what it is, and anything that bears on how the script treats it. State
plainly if the evidence is thin or contradictory. Never assert a fact no source
supports."""


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
import asyncio  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from typing import Callable  # noqa: E402

from google.adk import Agent, Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types as gtypes  # noqa: E402

from clearcut.agents.triage import TriageDecision  # noqa: E402
from clearcut.core.config import get_settings  # noqa: E402
from clearcut.core.models import AgentEvent  # noqa: E402

EmitFn = Callable[[AgentEvent], None]


def build_agent(model: str | None = None) -> Agent:
    return Agent(
        name="clearance_investigator",
        model=model or get_settings().gemini_model,
        description="Gathers cited evidence on one flagged clearance item.",
        instruction=INSTRUCTION,
        tools=[web_search, deep_research, find_same_named_entities],
    )


class InvestigatorAgent:
    """Drop-in replacement for ResearchAgent, with the routing decided by the agent."""

    name = "investigator"

    def __init__(
        self,
        service: ParallelResearchService | None = None,
        emit: EmitFn | None = None,
        max_workers: int = 3,
    ):
        self._svc = service or ParallelResearchService()
        self._emit = emit or (lambda e: None)
        self._max_workers = max_workers
        self._agent = build_agent()

    def run(self, decisions: list[TriageDecision]) -> dict[str, ResearchEvidence]:
        pending = [d for d in decisions if not d.settled_by_rule and d.plan]
        if not pending:
            return {}

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="start",
                message=f"Investigating {len(pending)} subjects — the agent chooses its own tools",
                payload={"items": len(pending)},
            )
        )

        out: dict[str, ResearchEvidence] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for item_id, ev in pool.map(self._one, pending):
                if ev is not None:
                    out[item_id] = ev

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=(
                    f"Evidence on {len(out)} subjects "
                    f"({self._svc.search_calls} searches, {self._svc.task_calls} deep passes)"
                ),
                payload={"searched": self._svc.search_calls, "deep": self._svc.task_calls},
            )
        )
        return out

    # ------------------------------------------------------------------ #
    def _one(self, d: TriageDecision) -> tuple[str, ResearchEvidence | None]:
        item = d.item
        brief = (
            f"ITEM: {item.value}\n"
            f"CATEGORY: {item.category.value}\n"
            f"DEPICTED NEGATIVELY: {'YES' if item.is_depicted_negatively else 'no'}\n"
            f"HOW IT IS USED: {item.context or 'unspecified'}\n"
            f'AS WRITTEN: "{item.locations[0].quote[:200] if item.locations else ""}"\n\n'
            f"Gather the evidence an adjudicator needs."
        )
        try:
            summary, collected, tools_used = asyncio.run(self._investigate(brief))
        except Exception as exc:  # noqa: BLE001 — one bad item must not sink the run
            logger.warning("Investigation failed for %s: %s", item.value, exc)
            self._emit(
                AgentEvent(
                    agent=self.name, phase="error",
                    message=f"{item.value}: {str(exc)[:160]}",
                )
            )
            return item.id, None

        # Fold every tool result into one evidence record for this item.
        cites: list[Citation] = []
        seen: set[str] = set()
        for ev in collected:
            for c in ev.citations:
                if c.url not in seen:
                    seen.add(c.url)
                    cites.append(c)

        evidence = ResearchEvidence(
            item_id=item.id,
            objective=d.plan.objective if d.plan else "",
            queries=[],
            citations=cites,
            findings=summary,
            processor="adk:" + "+".join(tools_used) if tools_used else "adk:none",
            escalated="deep_research" in tools_used,
        )

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="item",
                message=(
                    f"{item.value} — {len(cites)} source(s) via "
                    f"{', '.join(tools_used) or 'no tools'}"
                ),
                payload={
                    "item_id": item.id,
                    "value": item.value,
                    "citations": len(cites),
                    "tools": tools_used,
                },
            )
        )
        return item.id, evidence

    async def _investigate(self, brief: str) -> tuple[str, list[ResearchEvidence], list[str]]:
        collected = bind_context(self._svc)
        tools_used: list[str] = []

        runner = Runner(
            agent=self._agent,
            app_name="clearcut",
            session_service=InMemorySessionService(),
            auto_create_session=True,
        )
        msg = gtypes.Content(role="user", parts=[gtypes.Part(text=brief)])
        final = ""
        try:
            async for event in runner.run_async(
                user_id="clearcut", session_id=None, new_message=msg
            ):
                if not (event.content and event.content.parts):
                    continue
                for part in event.content.parts:
                    if getattr(part, "function_call", None):
                        tools_used.append(part.function_call.name)
                    if part.text:
                        final = part.text
        finally:
            await runner.close()

        return final.strip(), list(collected), tools_used
