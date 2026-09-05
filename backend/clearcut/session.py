"""
Stage-gated clearance sessions.

The one-shot pipeline is the right shape for a batch job and the wrong shape
for the actual workflow. A clearance report is a legal instrument: an attorney
signs it. So the run stops at each stage and waits.

Six stages, each advancing only when a human says go:

    breakdown   -> reviewer dismisses false positives, confirms the flag list
    triage      -> reviewer sees what will be researched and what is rule-settled
    research    -> reviewer inspects the evidence behind each item
    adjudicate  -> reviewer accepts or overrules each verdict
    substitute  -> reviewer accepts or rejects each proposed replacement
    report      -> the signed artifact

Human decisions are first-class state, not annotations: a dismissed item never
reaches research, an overruled verdict is what the report prints, and a rejected
substitution is not offered as a fix. The session records who decided what, so
the report can distinguish a machine ruling from an attorney's.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from clearcut.agents.adjudicate import AdjudicationAgent
from clearcut.agents.breakdown import BreakdownAgent
from clearcut.agents.investigator import InvestigatorAgent
from clearcut.agents.research import ResearchAgent
from clearcut.agents.substitute import SubstitutionAgent
from clearcut.agents.triage import TriageAgent, TriageDecision
from clearcut.core.config import get_settings
from clearcut.core.consistency import reconcile
from clearcut.core.ledger import ClearanceLedger
from clearcut.core.models import (
    Adjudication,
    AgentEvent,
    ClearableItem,
    ClearanceFinding,
    ClearanceReport,
    ResearchEvidence,
    RiskLevel,
    ScriptMeta,
    Substitution,
    Verdict,
)
from clearcut.core.screenplay import load_screenplay, parse_screenplay
from clearcut.services.parallel_research import ParallelResearchService

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]


class Stage(str, Enum):
    BREAKDOWN = "breakdown"
    TRIAGE = "triage"
    RESEARCH = "research"
    ADJUDICATE = "adjudicate"
    SUBSTITUTE = "substitute"
    REPORT = "report"


STAGE_ORDER = [
    Stage.BREAKDOWN,
    Stage.TRIAGE,
    Stage.RESEARCH,
    Stage.ADJUDICATE,
    Stage.SUBSTITUTE,
    Stage.REPORT,
]

STAGE_BLURB = {
    Stage.BREAKDOWN: "Read the script and flag everything that carries legal exposure.",
    Stage.TRIAGE: "Settle what a rule already answers, and write a question for the rest.",
    Stage.RESEARCH: "Check each subject against live sources and collect the citations.",
    Stage.ADJUDICATE: "Rule on the evidence, using the test that governs each kind of item.",
    Stage.SUBSTITUTE: "Propose replacements for what is blocked, then check the replacements too.",
    Stage.REPORT: "Build the report your carrier asks for before binding E&O.",
}

STAGE_GATE = {
    Stage.BREAKDOWN: "Knock out anything that isn't a clearance subject, then approve the list.",
    Stage.TRIAGE: "Check what's queued before we spend live lookups on it.",
    Stage.RESEARCH: "Open a few sources and see whether they are on point.",
    Stage.ADJUDICATE: "Take each ruling or overrule it. What you decide is what gets printed.",
    Stage.SUBSTITUTE: "Take or leave each replacement we suggest.",
    Stage.REPORT: "Sign off, and we will write these rulings into your ledger.",
}


class ItemDecision(BaseModel):
    """What the human decided about one item. Overrides the machine."""

    dismissed: bool = False
    verdict_override: Verdict | None = None
    note: str | None = None
    substitution_accepted: bool | None = None
    decided_at: datetime | None = None


class StageState(BaseModel):
    status: str = "pending"  # pending | running | awaiting_review | approved | error
    started_at: datetime | None = None
    finished_at: datetime | None = None
    approved_at: datetime | None = None
    error: str | None = None
    summary: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Session(BaseModel):
    id: str
    project_id: str
    screenplay_id: str
    script: ScriptMeta
    created_at: datetime = Field(default_factory=_utcnow)

    stages: dict[str, StageState] = Field(default_factory=dict)
    items: list[ClearableItem] = Field(default_factory=list)
    evidence: dict[str, ResearchEvidence] = Field(default_factory=dict)
    rulings: dict[str, Adjudication] = Field(default_factory=dict)
    substitutions: dict[str, Substitution] = Field(default_factory=dict)
    decisions: dict[str, ItemDecision] = Field(default_factory=dict)
    carried: list[str] = Field(default_factory=list)  # item ids from the ledger
    events: list[AgentEvent] = Field(default_factory=list)
    triage_notes: dict[str, str] = Field(default_factory=dict)
    report_id: str | None = None
    pdf_path: str | None = None

    # ------------------------------------------------------------------ #
    def active_items(self) -> list[ClearableItem]:
        """Items the reviewer has not dismissed."""
        return [i for i in self.items if not self.decisions.get(i.id, ItemDecision()).dismissed]

    def effective_verdict(self, item_id: str) -> Verdict | None:
        """The human's ruling if they made one, else the machine's."""
        d = self.decisions.get(item_id)
        if d and d.verdict_override:
            return d.verdict_override
        adj = self.rulings.get(item_id)
        return adj.verdict if adj else None

    def stage(self, s: Stage) -> StageState:
        return self.stages.setdefault(s.value, StageState())

    def can_run(self, s: Stage) -> bool:
        """A stage unlocks only when the one before it has been approved."""
        idx = STAGE_ORDER.index(s)
        if idx == 0:
            return self.stage(s).status in ("pending", "error")
        prev = self.stages.get(STAGE_ORDER[idx - 1].value)
        return bool(prev and prev.status == "approved") and self.stage(s).status in (
            "pending",
            "error",
        )


class SessionStore:
    """Sessions on disk, one JSON file each."""

    def __init__(self, root: Path):
        self.dir = Path(root) / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def get(self, sid: str) -> Session | None:
        p = self._path(sid)
        if not p.exists():
            return None
        try:
            return Session.model_validate_json(p.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("session %s unreadable: %s", sid, exc)
            return None

    def put(self, s: Session) -> None:
        with self._lock:
            tmp = self._path(s.id).with_suffix(".tmp")
            tmp.write_text(s.model_dump_json(indent=2))
            tmp.rename(self._path(s.id))

    def list(self) -> list[dict[str, Any]]:
        """Every past run, newest first, with enough detail to choose one.

        A production comes back to this list to answer "what did we decide about
        the blue pages", so it carries where the run stopped, what it concluded,
        and how much of it was the reviewer's own judgement rather than the
        machine's.
        """
        out = []
        for p in sorted(self.dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            s = self.get(p.stem)
            if not s:
                continue

            done = [st for st in STAGE_ORDER if s.stages.get(st.value, StageState()).status == "approved"]
            current = next(
                (st for st in STAGE_ORDER if s.stages.get(st.value, StageState()).status != "approved"),
                None,
            )
            live = s.active_items()
            blocking = sum(
                1
                for i in live
                if s.effective_verdict(i.id)
                in {Verdict.MUST_CHANGE, Verdict.LICENSE_REQUIRED, Verdict.LEGAL_REVIEW}
            )
            decisions = s.decisions.values()
            out.append(
                {
                    "id": s.id,
                    "project_id": s.project_id,
                    "screenplay_id": s.screenplay_id,
                    "title": s.script.title,
                    "draft": s.script.draft_label,
                    "pages": s.script.page_count,
                    "created_at": s.created_at,
                    "updated_at": datetime.fromtimestamp(
                        p.stat().st_mtime, tz=timezone.utc
                    ),
                    "items": len(s.items),
                    "stages_done": len(done),
                    "stages_total": len(STAGE_ORDER),
                    "current_stage": current.value if current else None,
                    "complete": current is None,
                    "blocking": blocking,
                    "dismissed": sum(1 for d in decisions if d.dismissed),
                    "overrides": sum(1 for d in decisions if d.verdict_override),
                    "report_id": s.report_id,
                }
            )
        return out

    def delete(self, sid: str) -> bool:
        p = self._path(sid)
        if not p.exists():
            return False
        p.unlink()
        return True


# --------------------------------------------------------------------------- #
def create_session(screenplay_path: Path, project_id: str) -> Session:
    script = parse_screenplay(load_screenplay(screenplay_path))
    s = Session(
        id=f"s_{uuid.uuid4().hex[:10]}",
        project_id=project_id,
        screenplay_id=screenplay_path.stem,
        script=script.meta,
    )
    for st in STAGE_ORDER:
        s.stage(st)
    return s


def run_stage(
    session: Session,
    stage: Stage,
    screenplay_path: Path,
    emit: EmitFn,
    *,
    deep_verify: bool = False,
) -> None:
    """Execute one stage against the session's current, human-edited state."""
    st = session.stage(stage)
    st.status = "running"
    st.started_at = _utcnow()
    st.error = None

    try:
        if stage is Stage.BREAKDOWN:
            _run_breakdown(session, screenplay_path, emit)
        elif stage is Stage.TRIAGE:
            _run_triage(session, emit)
        elif stage is Stage.RESEARCH:
            _run_research(session, emit, deep_verify)
        elif stage is Stage.ADJUDICATE:
            _run_adjudicate(session, emit)
        elif stage is Stage.SUBSTITUTE:
            _run_substitute(session, emit)
        elif stage is Stage.REPORT:
            _run_report(session, emit)
        st.status = "awaiting_review"
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage %s failed", stage)
        st.status = "error"
        st.error = str(exc)
        emit(AgentEvent(agent=stage.value, phase="error", message=str(exc)[:400]))
    finally:
        st.finished_at = _utcnow()


# ---- individual stages ----------------------------------------------------- #
def _run_breakdown(session: Session, path: Path, emit: EmitFn) -> None:
    script = parse_screenplay(load_screenplay(path))
    items = BreakdownAgent(emit=emit).run(script)

    # Carry forward anything the ledger already holds at an unchanged depiction.
    ledger = ClearanceLedger(session.project_id, get_settings().data_dir)
    to_clear, reusable, diff = ledger.plan_revision(items, script.meta.draft_label or "Draft")
    if ledger.history:
        emit(
            AgentEvent(
                agent="ledger",
                phase="diff",
                message=(
                    f"Revision against {diff.from_draft}: {len(diff.unchanged)} carry "
                    f"forward, {len(diff.added)} need re-clearing, {len(diff.removed)} removed"
                ),
                payload={"added": diff.added, "removed": diff.removed},
            )
        )
        for iid, entry in reusable.items():
            session.rulings[iid] = Adjudication(
                item_id=iid,
                verdict=entry.verdict,
                risk=entry.risk,
                rationale=entry.rationale,
                rule_applied="CARRIED_FORWARD",
                citations=entry.citations,
            )
        session.carried = list(reusable.keys())

    session.items = items
    pages = script.total_pages
    session.stage(Stage.BREAKDOWN).summary = (
        f"{len(items)} clearable item{'' if len(items) == 1 else 's'} across "
        f"{pages} page{'' if pages == 1 else 's'}"
        + (f" · {len(session.carried)} carried from ledger" if session.carried else "")
    )


def _decisions(session: Session) -> list[TriageDecision]:
    """Triage the items still in play, skipping anything carried or dismissed."""
    pending = [i for i in session.active_items() if i.id not in session.carried]
    return TriageAgent(emit=lambda e: None).run(pending)


def _run_triage(session: Session, emit: EmitFn) -> None:
    decisions = TriageAgent(emit=emit).run(
        [i for i in session.active_items() if i.id not in session.carried]
    )
    by_rule = 0
    for d in decisions:
        if d.settled_by_rule and d.rule:
            by_rule += 1
            session.triage_notes[d.item.id] = f"rule · {d.rule.rule_id}"
            session.rulings[d.item.id] = Adjudication(
                item_id=d.item.id,
                verdict=d.rule.verdict,
                risk=d.rule.risk,
                rationale=d.rule.rationale,
                rule_applied=d.rule.rule_id,
                requires_license_from=d.rule.requires_license_from,
            )
        elif d.plan:
            session.triage_notes[d.item.id] = d.plan.objective

    session.stage(Stage.TRIAGE).summary = (
        f"{by_rule} settled by rule, {len(decisions) - by_rule} routed to research"
    )


def _run_research(session: Session, emit: EmitFn, deep: bool) -> None:
    """Verify the outstanding subjects.

    Two engines, because the right amount of effort is not the same for every
    production. The scripted pass runs one search per subject and is fast enough
    to sit through. The investigator is an ADK agent holding Parallel's
    capabilities as tools, and decides per subject how hard to look — one search
    for a common surname, multi-hop research for a music cue or a hospital shown
    falsifying records. It costs roughly a minute a subject and is worth it on a
    draft going to an insurer.
    """
    decisions = _decisions(session)
    svc = ParallelResearchService()

    if deep:
        ev = InvestigatorAgent(service=svc, emit=emit, max_workers=5).run(decisions)
        engine = "agent-directed"
    else:
        ev = ResearchAgent(service=svc, emit=emit, deep_verify=False).run(decisions)
        engine = "one search per subject"

    session.evidence.update(ev)
    cites = sum(len(e.citations) for e in ev.values())
    escalated = sum(1 for e in ev.values() if e.escalated)
    session.stage(Stage.RESEARCH).summary = (
        f"{len(ev)} subjects verified · {cites} sources · {engine}"
        + (f" · {escalated} escalated to deep research" if escalated else "")
    )


def _run_adjudicate(session: Session, emit: EmitFn) -> None:
    decisions = _decisions(session)
    rulings = AdjudicationAgent(emit=emit).run(decisions, session.evidence)
    session.rulings.update(rulings)

    # Rulings reached independently can contradict each other. Settle those by
    # rule before a reviewer sees them, always upward.
    for change in reconcile(session.active_items(), session.rulings):
        emit(
            AgentEvent(
                agent="adjudicate",
                phase="reconciled",
                message=(
                    f"{change.value}: raised from {change.was.value} to "
                    f"{change.now.value} to match a related subject"
                ),
                payload={"item_id": change.item_id, "was": change.was.value,
                         "now": change.now.value},
            )
        )

    blocking = sum(
        1
        for i in session.active_items()
        if session.effective_verdict(i.id)
        in {Verdict.MUST_CHANGE, Verdict.LICENSE_REQUIRED, Verdict.LEGAL_REVIEW}
    )
    session.stage(Stage.ADJUDICATE).summary = (
        f"{len(session.rulings)} ruled · {blocking} blocking E&O"
    )


def _run_substitute(session: Session, emit: EmitFn) -> None:
    # Respect human overrides: substitute what the reviewer says must change.
    targets = [
        i
        for i in session.active_items()
        if session.effective_verdict(i.id) == Verdict.MUST_CHANGE
    ]
    effective = {
        i.id: Adjudication(
            item_id=i.id,
            verdict=Verdict.MUST_CHANGE,
            risk=(session.rulings.get(i.id).risk if session.rulings.get(i.id) else RiskLevel.HIGH),
            rationale=(
                session.rulings[i.id].rationale
                if i.id in session.rulings
                else "Flagged for replacement by reviewer."
            ),
        )
        for i in targets
    }
    subs = SubstitutionAgent(emit=emit).run(targets, effective)
    session.substitutions.update(subs)
    ok = sum(1 for s in subs.values() if s.verified_clear)
    session.stage(Stage.SUBSTITUTE).summary = f"{ok}/{len(subs)} replacements verified clear"


def _run_report(session: Session, emit: EmitFn) -> None:
    from clearcut.agents.report import ReportAgent

    findings: list[ClearanceFinding] = []
    for it in session.active_items():
        adj = session.rulings.get(it.id)
        d = session.decisions.get(it.id)
        if adj and d and d.verdict_override:
            adj = adj.model_copy(
                update={
                    "verdict": d.verdict_override,
                    "rule_applied": "REVIEWER_OVERRIDE",
                    "rationale": (d.note or adj.rationale),
                }
            )
        sub = session.substitutions.get(it.id)
        if sub and d and d.substitution_accepted is False:
            sub = None  # reviewer rejected the proposal
        findings.append(
            ClearanceFinding(
                item=it, evidence=session.evidence.get(it.id), adjudication=adj, substitution=sub
            )
        )

    report = ClearanceReport(
        report_id=f"CC-{uuid.uuid4().hex[:8].upper()}",
        project_id=session.project_id,
        script=session.script,
        findings=findings,
    )
    out = Path(get_settings().data_dir) / "reports" / f"{report.report_id}.pdf"
    ReportAgent(emit=emit).render_pdf(report, out)

    session.report_id = report.report_id
    session.pdf_path = str(out)

    # Commit to the ledger only now — a report the reviewer signed.
    ledger = ClearanceLedger(session.project_id, get_settings().data_dir)
    ledger.record(
        session.active_items(),
        {f.item.id: f.adjudication for f in findings if f.adjudication},
        session.script.draft_label or "Draft",
    )
    ledger.save()

    overrides = sum(1 for d in session.decisions.values() if d.verdict_override)
    session.stage(Stage.REPORT).summary = (
        f"{report.report_id} · {len(findings)} findings"
        + (f" · {overrides} reviewer override(s)" if overrides else "")
    )
